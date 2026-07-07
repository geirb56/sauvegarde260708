from services.adaptation_engine import adapt_workout_advanced
from fastapi import FastAPI, APIRouter, HTTPException, Query, Request, Depends, Header
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import json
import logging
import secrets
import hashlib
import base64
import httpx
import time
from collections import defaultdict
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone, timedelta
from config.secrets import MissingSecretError
import localization

# Import the analysis engine (NO LLM dependencies)
from analysis_engine import (
    generate_session_analysis,
    generate_weekly_review,
    generate_dashboard_insight,
)

# Import LLM coach module (GPT-4o-mini)
from llm_coach import LLM_MODEL, generate_cycle_week

# Import coach service (cascade strategy)
from coach_service import (
    analyze_workout as coach_analyze_workout,
    weekly_review as coach_weekly_review,
    chat_response as coach_chat_response,
    generate_dynamic_training_plan,
    get_cache_stats,
    clear_cache,
    get_metrics as get_coach_metrics,
    reset_metrics as reset_coach_metrics
)

# Import RAG engine for enriched analyses
from rag_engine import (
    generate_dashboard_rag,
    generate_weekly_review_rag,
    generate_workout_analysis_rag
)

# Import training engine for periodization
from training_engine import (
    GOAL_CONFIG,
    compute_target_km,
    vma_pace,
    vma_pace_range,
    adapt_session_to_readiness,
    compute_week_number,
    determine_phase,
    get_phase_description,
)

# Import Stripe integration
from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout, 
    CheckoutSessionRequest
)

# Import subscription manager
from subscription_manager import (
    get_user_subscription,
    activate_early_adopter,
    cancel_subscription,
    get_trial_days_remaining,
    is_route_protected,
    get_subscription_display,
    SubscriptionStatus,
    FEATURES,
    EARLY_ADOPTER_PRICE
)

from demo_mode import get_demo_subscription, is_subscription_active, patch_subscription_status_response

# Import physiological engine dashboard router
from api.dashboard import dashboard_router
from engine.run_index_engine import calculate_run_index

# Import Terra integration module
from terra_integration import (
    syncDailyMetrics,
    computeRecoveryScore,
    computeTrainingLoad,
    generateWorkoutRecommendation,
    syncTerraWorkouts,
    fetch_terra_user,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Stripe configuration
STRIPE_API_KEY = os.environ.get('STRIPE_API_KEY', '')

# Subscription tiers configuration
SUBSCRIPTION_TIERS = {
    "free": {
        "name": "Free",
        "price_monthly": 0,
        "price_annual": 0,
        "messages_limit": 10,
        "description": "Discovery"
    },
    "starter": {
        "name": "Starter",
        "price_monthly": 4.99,
        "price_annual": 49.99,
        "messages_limit": 25,
        "description": "Getting started"
    },
    "confort": {
        "name": "Confort",
        "price_monthly": 5.99,
        "price_annual": 59.99,
        "messages_limit": 50,
        "description": "Regular usage"
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 9.99,
        "price_annual": 99.99,
        "messages_limit": 150,  # Soft limit (fair-use)
        "unlimited": True,
        "description": "Unlimited"
    }
}



FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Create the main app
app = FastAPI()

# GZip compression for responses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ========== RATE LIMITER ==========

class RateLimiter:
    """Simple in-memory rate limiter"""

    def __init__(self, requests_per_minute: int = 60, burst_limit: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self._last_global_cleanup: float = time.time()

    def _cleanup(self, user_id: str) -> None:
        """Remove old requests outside the window for this user"""
        now = time.time()
        cutoff = now - 60  # 1 minute window
        self.requests[user_id] = [t for t in self.requests[user_id] if t > cutoff]
        # Remove the key entirely when empty to prevent unbounded growth
        if not self.requests[user_id]:
            del self.requests[user_id]

    def _global_cleanup(self) -> None:
        """Periodically purge stale user entries (every 5 minutes)"""
        now = time.time()
        if now - self._last_global_cleanup < 300:
            return
        self._last_global_cleanup = now
        cutoff = now - 60
        stale = [uid for uid, ts in self.requests.items() if not ts or ts[-1] <= cutoff]
        for uid in stale:
            del self.requests[uid]

    def is_limited(self, user_id: str) -> bool:
        """Check if user is rate limited"""
        self._global_cleanup()
        self._cleanup(user_id)

        now = time.time()
        recent = self.requests.get(user_id, [])

        # Check burst (10 requests in last 2 seconds)
        burst_cutoff = now - 2
        burst_count = sum(1 for t in recent if t > burst_cutoff)
        if burst_count >= self.burst_limit:
            return True

        # Check rate (60 requests per minute)
        if len(recent) >= self.requests_per_minute:
            return True

        return False

    def record(self, user_id: str) -> None:
        """Record a request"""
        self.requests[user_id].append(time.time())

    def get_stats(self, user_id: str) -> dict:
        """Get rate limit stats for user"""
        self._cleanup(user_id)
        recent = self.requests.get(user_id, [])
        return {
            "requests_last_minute": len(recent),
            "limit": self.requests_per_minute,
            "remaining": max(0, self.requests_per_minute - len(recent))
        }


# Initialize rate limiter (increased burst for SPA parallel API calls)
rate_limiter = RateLimiter(requests_per_minute=120, burst_limit=30)

# Endpoints exempt from rate limiting
RATE_LIMIT_EXEMPT = {"/api/cache/stats"}


def get_user_id_from_request(request: Request) -> str:
    """Extract user_id from request"""
    # Try query param first
    user_id = request.query_params.get("user_id")
    if user_id:
        return user_id
    
    # Fallback to IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ========== AUTH DEPENDENCY ==========

security = HTTPBearer(auto_error=False)

async def auth_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
) -> dict:
    """
    Flexible authentication dependency.

    Priority order:
    1. Bearer token (JWT to be implemented)
    2. Header X-User-Id
    3. Query param user_id
    4. Fallback "default"
    """
    user_id = None

    # 1. Bearer token (placeholder for JWT)
    if credentials and credentials.credentials:
        token = credentials.credentials
        # TODO: Validate JWT and extract user_id
        # For now, use the token as user_id if not JWT
        if token.startswith("user_"):
            user_id = token

    # 2. Header X-User-Id
    if not user_id and x_user_id:
        user_id = x_user_id

    # 3. Query param
    if not user_id:
        user_id = request.query_params.get("user_id")

    # 4. Fallback
    if not user_id:
        user_id = "default"

    return {"id": user_id, "authenticated": bool(credentials)}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware"""
    # Skip exempt endpoints
    if request.url.path in RATE_LIMIT_EXEMPT:
        return await call_next(request)
    
    # Skip non-API requests
    if not request.url.path.startswith("/api"):
        return await call_next(request)
    
    user_id = get_user_id_from_request(request)
    
    if rate_limiter.is_limited(user_id):
        logger.warning(f"[RateLimit] User {user_id} exceeded rate limit")
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too many requests",
                "retry_after": 60,
                **rate_limiter.get_stats(user_id)
            }
        )
    
    rate_limiter.record(user_id)
    return await call_next(request)


@app.middleware("http")
async def subscription_middleware(request: Request, call_next):
    """Subscription verification middleware.

    Blocks access to protected routes for 'free' users.
    Users with 'trial', 'early_adopter' and 'premium' have full access.
    """
    path = request.url.path
    
    # Skip non-API requests
    if not path.startswith("/api"):
        return await call_next(request)
    
    # Skip public routes (subscription, auth, health, etc.)
    if not is_route_protected(path):
        return await call_next(request)
    
    # Get user ID
    user_id = get_user_id_from_request(request)
    
    try:
        # Get subscription status
        subscription = await get_demo_subscription(db, user_id)
        status = subscription.get("status", SubscriptionStatus.FREE)
        
        # Check if user has access
        if status == SubscriptionStatus.FREE:
            logger.info(f"[Subscription] Blocked {path} for FREE user {user_id}")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "subscription_required",
                    "message": "Subscription required to access this feature",
                    "message_en": "Subscription required to access this feature",
                    "status": status,
                    "upgrade_url": "/subscription"
                }
            )
        
        # Store subscription in request state for later use
        request.state.subscription = subscription
        
    except Exception as e:
        logger.error(f"[Subscription] Error checking subscription: {e}")
        # In case of error, allow access (fail open)
    
    return await call_next(request)


# ========== MODELS ==========

class Workout(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str  # "run", "cycle", "swim"
    name: str
    date: str  # ISO date string
    duration_minutes: int
    distance_km: float
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_pace_min_km: Optional[float] = None  # minutes per km
    avg_speed_kmh: Optional[float] = None
    elevation_gain_m: Optional[int] = None
    calories: Optional[int] = None
    effort_zone_distribution: Optional[dict] = None  # {"z1": 10, "z2": 25, ...}
    notes: Optional[str] = None
    data_source: Optional[str] = "manual"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WorkoutCreate(BaseModel):
    type: str
    name: str
    date: str
    duration_minutes: int
    distance_km: float
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_pace_min_km: Optional[float] = None
    avg_speed_kmh: Optional[float] = None
    elevation_gain_m: Optional[int] = None
    calories: Optional[int] = None
    effort_zone_distribution: Optional[dict] = None
    notes: Optional[str] = None
    data_source: Optional[str] = "manual"

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"run", "cycle", "swim"}
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v < 0:
            raise ValueError("duration_minutes must be non-negative")
        return v

    @field_validator("distance_km")
    @classmethod
    def validate_distance(cls, v: float) -> float:
        if v < 0:
            raise ValueError("distance_km must be non-negative")
        return v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.split("T")[0])
        except (ValueError, AttributeError):
            raise ValueError("date must be a valid ISO date string (YYYY-MM-DD)")
        return v

    @field_validator("notes")
    @classmethod
    def sanitize_notes(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Strip HTML tags to prevent stored XSS
        v = re.sub(r"<[^>]+>", "", v)
        return v[:500]  # Cap length


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CoachRequest(BaseModel):
    message: str
    workout_id: Optional[str] = None
    context: Optional[str] = None  # Additional context like recent stats
    language: Optional[str] = "en"  # "en" or "fr"
    deep_analysis: Optional[bool] = False  # Trigger deep workout analysis
    user_id: Optional[str] = "default"  # For memory persistence


class CoachResponse(BaseModel):
    response: str
    message_id: str


class GuidanceRequest(BaseModel):
    language: Optional[str] = "en"
    user_id: Optional[str] = "default"


class GuidanceResponse(BaseModel):
    status: str  # "maintain", "adjust", "hold_steady"
    guidance: str
    generated_at: str


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    role: str  # "user" or "assistant"
    content: str
    workout_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TrainingStats(BaseModel):
    total_workouts: int
    total_distance_km: float
    total_duration_minutes: int
    avg_heart_rate: Optional[float] = None
    workouts_by_type: dict
    weekly_summary: List[dict]


def calculate_baseline_metrics(workouts: List[dict], current_workout: dict, days: int = 14) -> dict:
    """Calculate baseline metrics from recent workouts for contextual comparison"""
    from datetime import datetime, timedelta
    
    current_date = datetime.fromisoformat(current_workout.get("date", "").replace("Z", "+00:00").split("T")[0])
    cutoff_date = current_date - timedelta(days=days)
    current_type = current_workout.get("type")
    
    # Filter workouts: same type, within date range, excluding current
    baseline_workouts = [
        w for w in workouts
        if w.get("type") == current_type
        and w.get("id") != current_workout.get("id")
        and w.get("date")
    ]
    
    # Filter by date
    filtered = []
    for w in baseline_workouts:
        try:
            w_date = datetime.fromisoformat(w["date"].replace("Z", "+00:00").split("T")[0])
            if cutoff_date <= w_date < current_date:
                filtered.append(w)
        except (ValueError, TypeError):
            continue
    
    if not filtered:
        return None
    
    # Calculate averages
    def safe_avg(values):
        valid = [v for v in values if v is not None]
        return round(sum(valid) / len(valid), 2) if valid else None
    
    baseline = {
        "period_days": days,
        "workout_count": len(filtered),
        "workout_type": current_type,
        "avg_distance_km": safe_avg([w.get("distance_km") for w in filtered]),
        "avg_duration_minutes": safe_avg([w.get("duration_minutes") for w in filtered]),
        "avg_heart_rate": safe_avg([w.get("avg_heart_rate") for w in filtered]),
        "avg_max_heart_rate": safe_avg([w.get("max_heart_rate") for w in filtered]),
    }
    
    # Type-specific metrics
    if current_type == "run":
        baseline["avg_pace_min_km"] = safe_avg([w.get("avg_pace_min_km") for w in filtered])
    elif current_type == "cycle":
        baseline["avg_speed_kmh"] = safe_avg([w.get("avg_speed_kmh") for w in filtered])
    
    # Calculate zone distribution averages
    zone_totals = {"z1": [], "z2": [], "z3": [], "z4": [], "z5": []}
    for w in filtered:
        zones = w.get("effort_zone_distribution", {})
        for z in zone_totals:
            if z in zones:
                zone_totals[z].append(zones[z])
    
    baseline["avg_zone_distribution"] = {
        z: safe_avg(vals) for z, vals in zone_totals.items() if vals
    }
    
    # Calculate load metrics
    total_volume = sum(w.get("distance_km", 0) for w in filtered)
    total_time = sum(w.get("duration_minutes", 0) for w in filtered)
    baseline["total_volume_km"] = round(total_volume, 1)
    baseline["total_time_minutes"] = total_time
    baseline["weekly_avg_distance"] = round(total_volume / (days / 7), 1) if days > 0 else 0
    
    # Compare current workout to baseline
    current_hr = current_workout.get("avg_heart_rate")
    current_dist = current_workout.get("distance_km")
    current_dur = current_workout.get("duration_minutes")
    
    comparison = {}
    if baseline["avg_heart_rate"] and current_hr:
        hr_diff = current_hr - baseline["avg_heart_rate"]
        hr_pct = (hr_diff / baseline["avg_heart_rate"]) * 100
        comparison["heart_rate_vs_baseline"] = {
            "difference_bpm": round(hr_diff, 1),
            "percentage": round(hr_pct, 1),
            "status": "elevated" if hr_pct > 5 else "reduced" if hr_pct < -5 else "normal"
        }
    
    if baseline["avg_distance_km"] and current_dist:
        dist_diff = current_dist - baseline["avg_distance_km"]
        dist_pct = (dist_diff / baseline["avg_distance_km"]) * 100
        comparison["distance_vs_baseline"] = {
            "difference_km": round(dist_diff, 1),
            "percentage": round(dist_pct, 1),
            "status": "longer" if dist_pct > 15 else "shorter" if dist_pct < -15 else "typical"
        }
    
    if current_type == "run" and baseline.get("avg_pace_min_km"):
        current_pace = current_workout.get("avg_pace_min_km")
        if current_pace:
            pace_diff = current_pace - baseline["avg_pace_min_km"]
            comparison["pace_vs_baseline"] = {
                "difference_min_km": round(pace_diff, 2),
                "status": "slower" if pace_diff > 0.15 else "faster" if pace_diff < -0.15 else "consistent"
            }
    
    baseline["comparison"] = comparison
    
    return baseline




# ========== ROUTES ==========

@api_router.get("/")
async def root():
    return {"message": "CardioCoach API"}


@api_router.get("/workouts", response_model=List[dict])
async def get_workouts(user_id: str = "default"):
    """Get all workouts for a user, sorted by date descending"""
    # Search for workouts with user_id OR without user_id (imported workouts)
    workouts = await db.workouts.find(
        {"$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}]}, 
        {"_id": 0}
    ).sort("date", -1).to_list(200)
    return workouts


@api_router.get("/workouts/{workout_id}")
async def get_workout(workout_id: str, user_id: str = "default"):
    """Get a specific workout by ID"""
    # Search with or without user_id
    workout = await db.workouts.find_one(
        {"id": workout_id, "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}]}, 
        {"_id": 0}
    )
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    return workout


@api_router.post("/workouts", response_model=Workout)
async def create_workout(workout: WorkoutCreate, user_id: str = "default"):
    """Create a new workout"""
    workout_obj = Workout(**workout.model_dump())
    doc = workout_obj.model_dump()
    doc["user_id"] = user_id
    await db.workouts.insert_one(doc)
    return workout_obj


# ========== VMA / VO2MAX ESTIMATION ==========

class VMAEstimationResponse(BaseModel):
    has_sufficient_data: bool
    confidence: str  # "high", "medium", "low", "insufficient"
    confidence_score: int  # 1-5 (5 = very confident)
    vma_kmh: Optional[float] = None
    vo2max: Optional[float] = None
    data_source: Optional[str] = None
    training_zones: Optional[dict] = None
    message: str
    recommendations: Optional[List[str]] = None


def estimate_vma_from_race(distance_km: float, time_minutes: int) -> dict:
    """Estimate VMA from race performance using VDOT tables (Jack Daniels)"""
    if distance_km <= 0 or time_minutes <= 0:
        return None
    
    # Calculate pace in min/km
    pace_min_km = time_minutes / distance_km
    
    # Simplified VDOT estimation based on pace
    # These are approximations from Jack Daniels' tables
    speed_kmh = 60 / pace_min_km  # Convert pace to km/h
    
    # VMA is approximately the speed you can sustain for 4-7 minutes
    # From race performance, we estimate VMA based on distance
    # Longer distances = lower % of VMA
    vma_percentage = {
        5: 0.95,      # 5km ≈ 95% VMA
        10: 0.90,     # 10km ≈ 90% VMA
        21.1: 0.85,   # Semi ≈ 85% VMA
        42.195: 0.80  # Marathon ≈ 80% VMA
    }
    
    # Find closest distance
    closest_dist = min(vma_percentage.keys(), key=lambda x: abs(x - distance_km))
    pct = vma_percentage[closest_dist]
    
    vma_kmh = speed_kmh / pct
    vo2max = vma_kmh * 3.5  # Standard formula: VO2max ≈ VMA × 3.5
    
    return {
        "vma_kmh": round(vma_kmh, 1),
        "vo2max": round(vo2max, 1),
        "method": "race_performance",
        "confidence": "high" if distance_km >= 5 else "medium"
    }


def estimate_vma_from_workouts(workouts: list) -> dict:
    """Estimate VMA from training data (Z5 efforts)"""
    
    # Filter running workouts with HR zones
    running_workouts = [
        w for w in workouts 
        if w.get("type") == "run" and w.get("effort_zone_distribution")
    ]
    
    if len(running_workouts) < 3:
        return {
            "has_sufficient_data": False,
            "reason": "need_more_workouts",
            "count": len(running_workouts)
        }
    
    # Analyze Z5 efforts
    z5_efforts = []
    z4_efforts = []
    
    for w in running_workouts:
        zones = w.get("effort_zone_distribution", {})
        z5_pct = zones.get("z5", 0) or 0
        z4_pct = zones.get("z4", 0) or 0
        duration = w.get("duration_minutes", 0)
        
        # Z5 time in minutes
        z5_time = (z5_pct / 100) * duration
        z4_time = (z4_pct / 100) * duration
        
        # Best pace as proxy for VMA effort
        best_pace = w.get("best_pace_min_km")
        avg_pace = w.get("avg_pace_min_km")
        
        if z5_time >= 2 and best_pace:  # At least 2 min in Z5
            z5_efforts.append({
                "workout": w.get("name"),
                "date": w.get("date"),
                "z5_time_min": z5_time,
                "best_pace": best_pace,
                "avg_pace": avg_pace
            })
        
        if z4_time >= 5 and avg_pace:  # At least 5 min in Z4
            z4_efforts.append({
                "workout": w.get("name"),
                "date": w.get("date"),
                "z4_time_min": z4_time,
                "avg_pace": avg_pace
            })
    
    # Priority 1: Use Z5 efforts (most reliable)
    if len(z5_efforts) >= 2:
        # Take best paces from Z5 efforts
        best_paces = [e["best_pace"] for e in z5_efforts if e["best_pace"]]
        if best_paces:
            # VMA ≈ best pace in Z5 (slightly faster)
            avg_best_pace = sum(best_paces) / len(best_paces)
            vma_kmh = 60 / avg_best_pace  # Convert min/km to km/h
            vo2max = vma_kmh * 3.5
            
            return {
                "has_sufficient_data": True,
                "vma_kmh": round(vma_kmh, 1),
                "vo2max": round(vo2max, 1),
                "method": "z5_efforts",
                "confidence": "medium",
                "sample_count": len(z5_efforts),
                "efforts": z5_efforts[:3]  # Return top 3 for reference
            }
    
    # Priority 2: Use Z4 efforts (less reliable)
    if len(z4_efforts) >= 3:
        avg_paces = [e["avg_pace"] for e in z4_efforts if e["avg_pace"]]
        if avg_paces:
            # Z4 pace ≈ 85-90% VMA, so VMA ≈ Z4 pace / 0.87
            avg_z4_pace = sum(avg_paces) / len(avg_paces)
            z4_speed = 60 / avg_z4_pace
            vma_kmh = z4_speed / 0.87
            vo2max = vma_kmh * 3.5
            
            return {
                "has_sufficient_data": True,
                "vma_kmh": round(vma_kmh, 1),
                "vo2max": round(vo2max, 1),
                "method": "z4_extrapolation",
                "confidence": "low",
                "sample_count": len(z4_efforts),
                "warning": "Estimation basée sur Z4 uniquement - moins fiable"
            }
    
    # Not enough high-intensity data
    return {
        "has_sufficient_data": False,
        "reason": "need_high_intensity",
        "z5_count": len(z5_efforts),
        "z4_count": len(z4_efforts)
    }


def calculate_training_zones(vma_kmh: float, language: str = "en") -> dict:
    """Calculate training zones based on VMA"""
    
    def kmh_to_pace(speed_kmh):
        if speed_kmh <= 0:
            return None
        pace = 60 / speed_kmh
        mins = int(pace)
        secs = int((pace - mins) * 60)
        return f"{mins}:{secs:02d}"
    
    zones = {
        "z1": {
            "name": "Recovery" if language == "en" else "Recovery",
            "pct_vma": "60-65%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.60)} - {kmh_to_pace(vma_kmh * 0.65)}"
        },
        "z2": {
            "name": "Endurance" if language == "en" else "Endurance",
            "pct_vma": "65-75%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.65)} - {kmh_to_pace(vma_kmh * 0.75)}"
        },
        "z3": {
            "name": "Tempo" if language == "en" else "Tempo",
            "pct_vma": "75-85%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.75)} - {kmh_to_pace(vma_kmh * 0.85)}"
        },
        "z4": {
            "name": "Threshold" if language == "en" else "Seuil",
            "pct_vma": "85-95%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.85)} - {kmh_to_pace(vma_kmh * 0.95)}"
        },
        "z5": {
            "name": "VMA/VO2max",
            "pct_vma": "95-105%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.95)} - {kmh_to_pace(vma_kmh * 1.05)}"
        }
    }
    
    return zones


@api_router.get("/user/vma-estimate")
async def get_vma_estimate(user_id: str = "default", language: str = "en"):
    """Estimate VMA and VO2max from user data"""
    
    # Check if user has a goal (race performance to use)
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    # Get all running workouts
    all_workouts = await db.workouts.find(
        {"type": "run"}, 
        {"_id": 0}
    ).sort("date", -1).to_list(100)
    
    if not all_workouts:
        return VMAEstimationResponse(
            has_sufficient_data=False,
            confidence="insufficient",
            confidence_score=0,
            message="Insufficient data. No running workouts recorded." if language == "fr" else "Insufficient data. No running workouts recorded.",
            recommendations=[
                "Record some running workouts" if language == "fr" else "Record some running workouts",
                "Do some runs with heart rate monitor" if language == "fr" else "Do some runs with heart rate monitor"
            ]
        )
    
    result = None
    data_source = None
    
    # Priority 1: Use goal race performance if it's a past event or use target
    if user_goal and user_goal.get("target_time_minutes") and user_goal.get("distance_km"):
        race_estimate = estimate_vma_from_race(
            user_goal["distance_km"],
            user_goal["target_time_minutes"]
        )
        if race_estimate:
            result = race_estimate
            data_source = f"Goal: {user_goal['event_name']}" if language == "fr" else f"Goal: {user_goal['event_name']}"
    
    # Priority 2: Analyze workout data
    if not result:
        workout_estimate = estimate_vma_from_workouts(all_workouts)
        
        if not workout_estimate.get("has_sufficient_data"):
            reason = workout_estimate.get("reason")

            if reason == "need_more_workouts":
                msg = f"Insufficient data. Only {workout_estimate.get('count')} workouts with HR data." if language == "fr" else f"Insufficient data. Only {workout_estimate.get('count')} workouts with HR data."
                recs = [
                    "Keep syncing your workouts" if language == "fr" else "Keep syncing your workouts",
                    "At least 3 workouts with HR monitor needed" if language == "fr" else "At least 3 workouts with HR monitor needed"
                ]
            else:  # need_high_intensity
                msg = f"Insufficient data. Not enough high-intensity efforts (Z4/Z5) to estimate VMA." if language == "fr" else f"Insufficient data. Not enough high-intensity efforts (Z4/Z5) to estimate VMA."
                recs = [
                    "Do an interval session or VMA test" if language == "fr" else "Do an interval session or VMA test",
                    f"Z5 sessions found: {workout_estimate.get('z5_count', 0)}, Z4: {workout_estimate.get('z4_count', 0)}"
                ]
            
            return VMAEstimationResponse(
                has_sufficient_data=False,
                confidence="insufficient",
                confidence_score=0,
                message=msg,
                recommendations=recs
            )
        
        result = workout_estimate
        method = result.get("method")
        if method == "z5_efforts":
            data_source = f"Analysis of {result.get('sample_count')} Z5 efforts" if language == "fr" else f"Analysis of {result.get('sample_count')} Z5 efforts"
        else:
            data_source = f"Extrapolation from {result.get('sample_count')} Z4 sessions" if language == "fr" else f"Extrapolation from {result.get('sample_count')} Z4 sessions"
    
    # Calculate training zones
    vma_kmh = result["vma_kmh"]
    vo2max = result["vo2max"]
    training_zones = calculate_training_zones(vma_kmh, language)
    
    # Confidence mapping
    confidence = result.get("confidence", "medium")
    confidence_scores = {"high": 5, "medium": 3, "low": 2}
    confidence_score = confidence_scores.get(confidence, 1)
    
    # Build message
    if confidence == "high":
        msg = f"VMA estimated with good reliability from your race goal." if language == "fr" else "VMA estimated with good reliability from your race goal."
    elif confidence == "medium":
        msg = f"VMA estimated from your intense efforts. Decent reliability." if language == "fr" else "VMA estimated from your intense efforts. Decent reliability."
    else:
        msg = f"VMA estimated by extrapolation. Limited reliability - a VMA test would be more accurate." if language == "fr" else "VMA estimated by extrapolation. Limited reliability - a VMA test would be more accurate."
    
    # Recommendations based on VMA
    if language == "fr":
        recs = [
            f"Easy/endurance pace: {training_zones['z2']['pace_range']}/km",
            f"Threshold (tempo) pace: {training_zones['z4']['pace_range']}/km",
            f"VMA intervals: {training_zones['z5']['pace_range']}/km"
        ]
    else:
        recs = [
            f"Easy/endurance pace: {training_zones['z2']['pace_range']}/km",
            f"Threshold (tempo) pace: {training_zones['z4']['pace_range']}/km",
            f"VMA intervals: {training_zones['z5']['pace_range']}/km"
        ]
    
    return VMAEstimationResponse(
        has_sufficient_data=True,
        confidence=confidence,
        confidence_score=confidence_score,
        vma_kmh=vma_kmh,
        vo2max=vo2max,
        data_source=data_source,
        training_zones=training_zones,
        message=msg,
        recommendations=recs
    )


class DashboardInsightResponse(BaseModel):
    coach_insight: str
    week: dict
    month: dict
    recovery_score: Optional[dict] = None  # New: recovery score
    run_index: Optional[dict] = None


# ========== RECOVERY SCORE CALCULATION ==========

def calculate_recovery_score(workouts: list, language: str = "en") -> dict:
    """Calculate recovery score based on recent training load, intensity, and rest days"""
    today = datetime.now(timezone.utc).date()
    
    # Get workouts from last 7 days
    recent_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            if (today - w_date).days <= 7:
                recent_workouts.append((w, w_date))
        except (ValueError, TypeError):
            continue
    
    # Get baseline (previous 7-14 days) for comparison
    baseline_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            days_ago = (today - w_date).days
            if 7 < days_ago <= 14:
                baseline_workouts.append(w)
        except (ValueError, TypeError):
            continue
    
    # Calculate factors
    # 1. Days since last workout (more rest = higher recovery)
    if recent_workouts:
        last_workout_date = max(w_date for _, w_date in recent_workouts)
        days_since_last = (today - last_workout_date).days
    else:
        days_since_last = 7  # No recent workouts = well rested
    
    # 2. Load comparison (current vs baseline)
    current_load = sum(w.get("distance_km", 0) for w, _ in recent_workouts)
    baseline_load = sum(w.get("distance_km", 0) for w in baseline_workouts)
    
    if baseline_load > 0:
        load_ratio = current_load / baseline_load
    else:
        load_ratio = 1.0 if current_load == 0 else 1.5
    
    # 3. Intensity (hard sessions in last 3 days)
    hard_sessions_recent = 0
    for w, w_date in recent_workouts:
        if (today - w_date).days <= 3:
            zones = w.get("effort_zone_distribution", {})
            if zones:
                hard_pct = zones.get("z4", 0) + zones.get("z5", 0)
                if hard_pct >= 25:
                    hard_sessions_recent += 1
    
    # 4. Session spread (better if spread across days)
    unique_days = len(set(w_date for _, w_date in recent_workouts))
    
    # Calculate score (0-100)
    score = 100
    
    # Penalize if workout was today or yesterday
    if days_since_last == 0:
        score -= 25
    elif days_since_last == 1:
        score -= 15
    elif days_since_last >= 3:
        score += 5  # Bonus for extra rest
    
    # Penalize high load ratio
    if load_ratio > 1.3:
        score -= 20
    elif load_ratio > 1.15:
        score -= 10
    elif load_ratio < 0.7:
        score += 10  # Low load = more recovery
    
    # Penalize hard sessions
    score -= hard_sessions_recent * 15
    
    # Penalize clustered sessions
    if len(recent_workouts) > 0 and unique_days < len(recent_workouts):
        score -= 10  # Multiple sessions on same day
    
    # Clamp score
    score = max(20, min(100, score))
    
    # Determine status and coach phrase
    if score >= 75:
        status = "ready"
        if language == "fr":
            phrase = "Corps repose, pret pour une seance intense si tu veux."
        elif language == "es":
            phrase = "Cuerpo descansado, listo para una sesión intensa."
        else:
            phrase = "Body is rested, ready for an intense session if you want."
    elif score >= 50:
        status = "moderate"
        if language == "fr":
            phrase = "Recuperation correcte, privilegie une seance facile."
        elif language == "es":
            phrase = "Recuperación correcta, favorece una sesión fácil."
        else:
            phrase = "Decent recovery, favor an easy session."
    else:
        status = "low"
        if language == "fr":
            phrase = "Fatigue accumulee, une journee de repos serait ideale."
        elif language == "es":
            phrase = "Fatiga acumulada, un día de descanso sería ideal."
        else:
            phrase = "Accumulated fatigue, a rest day would be ideal."
    
    return {
        "score": score,
        "status": status,
        "phrase": phrase,
        "days_since_last_workout": days_since_last
    }


# ========== USER GOALS ==========

# Distance types with km values
DISTANCE_TYPES = {
    "5k": 5.0,
    "10k": 10.0,
    "semi": 21.1,
    "marathon": 42.195,
    "ultra": 50.0  # Default for ultra, actual distance in event_name
}


def calculate_target_pace(distance_km: float, target_time_minutes: int) -> str:
    """Calculate target pace in min/km format"""
    if distance_km <= 0 or target_time_minutes <= 0:
        return None
    pace_minutes = target_time_minutes / distance_km
    pace_min = int(pace_minutes)
    pace_sec = int((pace_minutes - pace_min) * 60)
    return f"{pace_min}:{pace_sec:02d}"


class UserGoal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    event_name: str
    event_date: str  # ISO date string
    distance_type: str  # 5k, 10k, semi, marathon, ultra
    distance_km: float  # Actual distance in km
    target_time_minutes: Optional[int] = None  # Target time in minutes
    target_pace: Optional[str] = None  # Calculated pace min/km
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class UserGoalCreate(BaseModel):
    event_name: str
    event_date: str
    distance_type: str  # 5k, 10k, semi, marathon, ultra
    target_time_minutes: Optional[int] = None  # Target time in minutes


@api_router.get("/user/goal")
async def get_user_goal(user_id: str = "default"):
    """Get user's current goal"""
    goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    return goal


@api_router.post("/user/goal")
async def set_user_goal(goal: UserGoalCreate, user_id: str = "default"):
    """Set user's goal (event with date, distance, target time)"""
    # Delete existing goal
    await db.user_goals.delete_many({"user_id": user_id})
    
    # Get distance in km
    distance_km = DISTANCE_TYPES.get(goal.distance_type, 42.195)
    
    # Calculate target pace if time provided
    target_pace = None
    if goal.target_time_minutes:
        target_pace = calculate_target_pace(distance_km, goal.target_time_minutes)
    
    # Create new goal
    goal_obj = UserGoal(
        user_id=user_id,
        event_name=goal.event_name,
        event_date=goal.event_date,
        distance_type=goal.distance_type,
        distance_km=distance_km,
        target_time_minutes=goal.target_time_minutes,
        target_pace=target_pace
    )
    doc = goal_obj.model_dump()
    await db.user_goals.insert_one(doc)
    
    # Return without _id
    doc.pop("_id", None)
    
    logger.info(f"Goal set for user {user_id}: {goal.event_name} ({goal.distance_type}) on {goal.event_date}, target: {goal.target_time_minutes}min")
    return {"success": True, "goal": doc}


@api_router.delete("/user/goal")
async def delete_user_goal(user_id: str = "default"):
    """Delete user's goal"""
    result = await db.user_goals.delete_many({"user_id": user_id})
    return {"deleted": result.deleted_count > 0}


def calculate_week_stats(workouts: list) -> dict:
    """Calculate current week statistics"""
    today = datetime.now(timezone.utc).date()
    # Rolling 7-day window (matches /training/metrics "THIS WEEK" and the ACWR
    # acute window) so the Dashboard "this week" stats never contradict it.
    week_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            if 0 <= (today - w_date).days < 7:
                week_workouts.append(w)
        except (ValueError, TypeError):
            continue
    
    total_km = sum(w.get("distance_km", 0) for w in week_workouts)
    sessions = len(week_workouts)
    
    # Load signal based on volume vs typical week
    if total_km > 80:
        load_signal = "high"
    elif total_km > 40:
        load_signal = "balanced"
    else:
        load_signal = "low"
    
    return {
        "sessions": sessions,
        "volume_km": round(total_km, 1),
        "load_signal": load_signal
    }


def calculate_month_stats(workouts: list) -> dict:
    """Calculate last 30 days statistics"""
    today = datetime.now(timezone.utc).date()
    month_start = today - timedelta(days=30)
    prev_month_start = today - timedelta(days=60)
    
    current_month = []
    prev_month = []
    
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            if month_start <= w_date <= today:
                current_month.append(w)
            elif prev_month_start <= w_date < month_start:
                prev_month.append(w)
        except (ValueError, TypeError):
            continue
    
    current_km = sum(w.get("distance_km", 0) for w in current_month)
    prev_km = sum(w.get("distance_km", 0) for w in prev_month)
    
    # Active weeks (weeks with at least one workout)
    active_weeks = len(set(
        datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date().isocalendar()[1]
        for w in current_month if w.get("date")
    ))
    
    # Trend
    if prev_km > 0:
        change = (current_km - prev_km) / prev_km * 100
        if change > 15:
            trend = "up"
        elif change < -15:
            trend = "down"
        else:
            trend = "stable"
    else:
        trend = "up" if current_km > 0 else "stable"
    
    return {
        "volume_km": round(current_km, 1),
        "active_weeks": active_weeks,
        "trend": trend
    }


# Dashboard insight cache (5 minutes TTL)
_dashboard_cache = {}
DASHBOARD_CACHE_TTL = 300  # 5 minutes in seconds


@api_router.get("/dashboard/insight")
async def get_dashboard_insight(language: str = "en", user_id: str = "default"):
    """Get dashboard coach insight with week and month summaries and recovery score - NO LLM"""
    
    # Check cache first
    cache_key = f"{user_id}_{language}"
    now = datetime.now(timezone.utc).timestamp()
    
    if cache_key in _dashboard_cache:
        cached_data, cached_time = _dashboard_cache[cache_key]
        if now - cached_time < DASHBOARD_CACHE_TTL:
            logger.info(f"Dashboard insight cache hit for {cache_key}")
            return cached_data
    
    # Get workouts (user-scoped to avoid mixing other users' data)
    all_workouts = await db.workouts.find({
        "$or": [
            {"user_id": user_id},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ]
    }, {"_id": 0}).sort("date", -1).to_list(200)
    # Calculate stats
    week_stats = calculate_week_stats(all_workouts)
    month_stats = calculate_month_stats(all_workouts)
    
    # Calculate recovery score
    recovery_score = calculate_recovery_score(all_workouts, language)
    run_index = calculate_run_index(all_workouts)

    await db.run_index_scores.update_one(
        {"user_id": user_id, "date": datetime.now(timezone.utc).date().isoformat()},
        {
            "$set": {
                "user_id": user_id,
                "date": datetime.now(timezone.utc).date().isoformat(),
                "computed_at": datetime.now(timezone.utc).isoformat(),
                **run_index,
            }
        },
        upsert=True,
    )
    
    # Generate insight using local engine (NO LLM)
    coach_insight = generate_dashboard_insight(
        week_stats=week_stats,
        month_stats=month_stats,
        recovery_score=recovery_score.get("score") if recovery_score else None,
        language=language
    )
    
    result = DashboardInsightResponse(
        coach_insight=coach_insight,
        week=week_stats,
        month=month_stats,
        recovery_score=recovery_score,
        run_index=run_index,
    )
    
    # Store in cache
    _dashboard_cache[cache_key] = (result, now)
    logger.info(f"Dashboard insight cached for {cache_key}")
    
    return result


@api_router.get("/stats")
async def get_stats():
    """Get training statistics with proper 7-day and 30-day calculations"""
    from datetime import datetime, timedelta
    from collections import defaultdict
    
    # Get all workouts
    workouts = await db.workouts.find({}, {"_id": 0}).to_list(500)
    
    # Build activities list
    all_activities = []
    
    for w in workouts:
        date_str = w.get("date", "")[:10]
        if date_str:
            all_activities.append({
                "date": date_str,
                "distance_km": w.get("distance_km", 0),
                "duration_minutes": w.get("duration_minutes", 0),
                "avg_heart_rate": w.get("avg_heart_rate"),
                "type": w.get("type", "run")
            })
    
    if not all_activities:
        all_activities = [{
            "date": (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"),
            "distance_km": 8 + (i % 5),
            "duration_minutes": 45 + (i % 20),
            "avg_heart_rate": 140,
            "type": "run"
        } for i in range(10)]
    
    # Calculate date boundaries
    today = datetime.now().date()
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)
    
    # Filter activities by period
    last_7_days = []
    last_30_days = []
    
    for a in all_activities:
        try:
            activity_date = datetime.strptime(a["date"], "%Y-%m-%d").date()
            if activity_date >= seven_days_ago:
                last_7_days.append(a)
            if activity_date >= thirty_days_ago:
                last_30_days.append(a)
        except:
            continue
    
    # Calculate 7-day stats
    km_7_days = sum(a.get("distance_km", 0) for a in last_7_days)
    sessions_7_days = len(last_7_days)
    
    # Calculate 30-day stats
    km_30_days = sum(a.get("distance_km", 0) for a in last_30_days)
    sessions_30_days = len(last_30_days)
    
    # Total stats
    total_distance = sum(a.get("distance_km", 0) for a in all_activities)
    total_duration = sum(a.get("duration_minutes", 0) for a in all_activities)
    
    hr_values = [a.get("avg_heart_rate") for a in all_activities if a.get("avg_heart_rate")]
    avg_hr = sum(hr_values) / len(hr_values) if hr_values else None
    
    # Count by type
    by_type = {}
    for a in all_activities:
        t = a.get("type", "other")
        by_type[t] = by_type.get(t, 0) + 1
    
    # Daily breakdown for last 7 days
    daily_data = defaultdict(lambda: {"distance": 0, "duration": 0, "count": 0})
    for a in last_7_days:
        date_str = a.get("date", "")
        daily_data[date_str]["distance"] += a.get("distance_km", 0)
        daily_data[date_str]["duration"] += a.get("duration_minutes", 0)
        daily_data[date_str]["count"] += 1
    
    weekly_summary = []
    for date, data in sorted(daily_data.items()):
        weekly_summary.append({"date": date, **data})
    
    return {
        "total_workouts": len(all_activities),
        "total_distance_km": round(total_distance, 1),
        "total_duration_minutes": int(total_duration),
        "avg_heart_rate": round(avg_hr, 1) if avg_hr else None,
        "workouts_by_type": by_type,
        "weekly_summary": weekly_summary,
        # New fields for precise calculations
        "sessions_7_days": sessions_7_days,
        "km_7_days": round(km_7_days, 1),
        "sessions_30_days": sessions_30_days,
        "km_30_days": round(km_30_days, 1)
    }


@api_router.post("/coach/analyze", response_model=CoachResponse)
async def analyze_with_coach(request: CoachRequest):
    """Conversational Chat Coach with GPT-4o-mini

    The coach has access to:
    - Conversation history
    - Training data (workouts, stats)
    - Fitness context (ACWR, TSB, volume)

    It can respond to open-ended questions about training.
    """
    from llm_coach import enrich_chat_response
    
    user_id = request.user_id or "default"
    language = request.language or "en"
    user_message = request.message or ""

    # 1. Retrieve conversation history (last 5 messages)
    conversation_history = await db.conversations.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(5).to_list(5)
    conversation_history = list(reversed(conversation_history))  # Chronological order

    # 2. Retrieve training data
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    # Training activities
    recent_activities = await db.workouts.find({
        "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}],
        "date": {"$gte": seven_days_ago.isoformat()}
    }).sort("date", -1).to_list(20)
    
    all_activities = await db.workouts.find({
        "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}],
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).sort("date", -1).to_list(100)
    
    # 3. Calculer les métriques de contexte
    def get_distance_km(w):
        dist = w.get("distance", 0)
        if dist > 1000:
            return dist / 1000
        return w.get("distance_km", dist) or 0
    
    km_7 = sum(get_distance_km(w) for w in recent_activities)
    km_28 = sum(get_distance_km(w) for w in all_activities)
    
    # ACWR & TSB
    chronic_avg = km_28 / 4 if km_28 > 0 else 1
    acwr = round(km_7 / chronic_avg, 2) if chronic_avg > 0 else 1.0
    ctl = km_28 / 4
    atl = km_7
    tsb = round(ctl - atl, 1)

    # 4. Prepare summary of ALL sessions (not just 5)
    all_sessions_summary = []
    for act in all_activities:
        name = act.get("name", "Session")
        dist = get_distance_km(act)
        duration = act.get("moving_time", act.get("duration_minutes", 0) * 60)
        if duration > 100:
            duration = duration / 60  # Convertir secondes en minutes
        avg_hr = act.get("average_heartrate", act.get("avg_heart_rate"))
        date_str = act.get("start_date_local", act.get("date", ""))[:10]
        avg_pace = ""
        if dist > 0 and duration > 0:
            pace_sec = (duration * 60) / dist
            pace_min = int(pace_sec // 60)
            pace_sec_rem = int(pace_sec % 60)
            avg_pace = f"{pace_min}:{pace_sec_rem:02d}/km"
        
        session_info = f"- {date_str}: {name}, {dist:.1f}km"
        if duration:
            session_info += f", {int(duration)}min"
        if avg_pace:
            session_info += f", {avg_pace}"
        if avg_hr:
            session_info += f", FC {int(avg_hr)}bpm"
        all_sessions_summary.append(session_info)
    
    # 5. Récupérer le plan d'entraînement actuel
    training_plan_summary = ""
    current_goal = "Non défini"
    sessions_per_week = 4
    try:
        plan_data = await db.training_plans.find_one(
            {"user_id": user_id},
            sort=[("created_at", -1)]
        )
        if plan_data:
            current_goal = plan_data.get("goal", "SEMI")
            sessions_per_week = plan_data.get("sessions_per_week", 4)
            sessions = plan_data.get("sessions", [])
            if sessions:
                training_plan_summary = f"Goal: {current_goal} | {sessions_per_week} sessions/week\n"
                training_plan_summary += "Week schedule:\n"
                for s in sessions:
                    day = s.get("day", "")
                    stype = s.get("type", "")
                    details = s.get("details", "")
                    dist = s.get("distance_km", 0)
                    training_plan_summary += f"  • {day}: {stype}"
                    if dist > 0:
                        training_plan_summary += f" ({dist}km)"
                    if details and stype != "Rest":
                        training_plan_summary += f" - {details[:60]}"
                    training_plan_summary += "\n"
    except Exception as e:
        logger.warning(f"Could not fetch training plan for coach context: {e}")
    
    # 6. Récupérer la VMA et les prédictions depuis l'endpoint existant
    vma_info = ""
    predictions_summary = ""
    try:
        # Utiliser la même logique que /api/training/race-predictions
        sixty_days_ago = today - timedelta(days=60)
        pred_activities = await db.workouts.find({
            "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}],
            "date": {"$gte": sixty_days_ago.isoformat()}
        }).to_list(500)
        
        if pred_activities:
            # Calculate VMA with the correct method
            def get_pred_distance(a):
                dist = a.get("distance", 0)
                if dist > 1000:
                    return dist / 1000
                return a.get("distance_km", dist)
            
            def get_pred_duration(a):
                moving_time = a.get("moving_time", 0)
                if moving_time > 0:
                    return moving_time / 60
                elapsed = a.get("elapsed_time", 0)
                if elapsed > 0:
                    return elapsed / 60
                return a.get("duration_minutes", 0)
            
            def get_pred_pace(a):
                pace = a.get("avg_pace_min_km")
                if pace:
                    return pace
                speed = a.get("average_speed", 0)
                if speed > 0:
                    return (1000 / speed) / 60
                dist = get_pred_distance(a)
                duration_min = get_pred_duration(a)
                if dist > 0 and duration_min > 0:
                    return duration_min / dist
                return None
            
            paces = []
            vma_efforts = []
            MIN_VMA_DURATION = 6
            
            for a in pred_activities:
                dist = get_pred_distance(a)
                pace = get_pred_pace(a)
                duration_min = get_pred_duration(a)
                
                if dist > 0 and pace and 3 < pace < 10:
                    paces.append(pace)
                    # Efforts >= 6 min ET allure rapide (< 5:30/km)
                    if duration_min >= MIN_VMA_DURATION and pace < 5.5:
                        vma_efforts.append({
                            "pace": pace,
                            "duration": duration_min,
                            "speed_kmh": 60 / pace
                        })
            
            if paces:
                avg_pace = sum(paces) / len(paces)

                # Calculate VMA with the correct method
                if vma_efforts:
                    best_vma_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
                    best_sustained_speed = best_vma_effort["speed_kmh"]
                    duration = best_vma_effort["duration"]

                    if duration >= 20:
                        estimated_vma = best_sustained_speed / 0.85
                    elif duration >= 12:
                        estimated_vma = best_sustained_speed / 0.90
                    else:
                        estimated_vma = best_sustained_speed / 0.95
                else:
                    avg_speed_kmh = 60 / avg_pace
                    estimated_vma = avg_speed_kmh / 0.70

                estimated_vma = round(estimated_vma, 1)
                vma_info = f"Estimated VMA: {estimated_vma} km/h"

                # VMA-based predictions
                pred_5k_speed = estimated_vma * 0.95
                pred_5k_pace = 60 / pred_5k_speed
                time_5k = (pred_5k_pace * 5)
                
                pred_10k_speed = estimated_vma * 0.90
                pred_10k_pace = 60 / pred_10k_speed
                time_10k = (pred_10k_pace * 10)
                
                pred_semi_speed = estimated_vma * 0.82
                pred_semi_pace = 60 / pred_semi_speed
                time_semi = (pred_semi_pace * 21.1)
                h_semi = int(time_semi // 60)
                m_semi = int(time_semi % 60)
                
                pred_marathon_speed = estimated_vma * 0.75
                pred_marathon_pace = 60 / pred_marathon_speed
                time_marathon = (pred_marathon_pace * 42.195)
                h_mar = int(time_marathon // 60)
                m_mar = int(time_marathon % 60)
                
                predictions_summary = f"5K: {int(time_5k)}:{int((time_5k % 1) * 60):02d} | 10K: {int(time_10k)}:{int((time_10k % 1) * 60):02d} | Semi: {h_semi}h{m_semi:02d} | Marathon: {h_mar}h{m_mar:02d}"
                
    except Exception as e:
        logger.warning(f"Could not calculate VMA for coach context: {e}")
        vma_info = "VMA: non calculée"
    
    # 7. Construire le contexte complet
    context = {
        "language": language,
        "stats_7j": {
            "km": round(km_7, 1),
            "sessions": len(recent_activities)
        },
        "stats_28j": {
            "km": round(km_28, 1),
            "sessions": len(all_activities)
        },
        "fitness": {
            "acwr": acwr,
            "acwr_status": "optimal" if 0.8 <= acwr <= 1.3 else "attention",
            "tsb": tsb,
            "tsb_status": "fresh" if tsb > 0 else "fatigued" if tsb < -10 else "loaded"
        },
        "all_sessions": "\n".join(all_sessions_summary) if all_sessions_summary else "No recorded sessions",
        "training_plan": training_plan_summary if training_plan_summary else "No active training plan",
        "current_goal": current_goal,
        "vma": vma_info,
        "predictions": predictions_summary
    }

    # 5. If workout_id specified, enrich context with session details
    if request.workout_id:
        workout = await db.workouts.find_one({"id": request.workout_id})
        
        if workout:
            context["workout_detail"] = {
                "name": workout.get("name"),
                "distance_km": get_distance_km(workout),
                "duration_min": workout.get("moving_time", workout.get("duration_minutes", 0) * 60) / 60 if workout.get("moving_time", 0) > 100 else workout.get("duration_minutes", 0),
                "avg_hr": workout.get("average_heartrate", workout.get("avg_heart_rate")),
                "max_hr": workout.get("max_heartrate", workout.get("max_heart_rate")),
                "zones": workout.get("effort_zone_distribution"),
                "km_splits": workout.get("km_splits", [])[:5]  # 5 premiers km
            }
    
    # 6. Stocker le message utilisateur
    user_msg_id = str(uuid.uuid4())
    await db.conversations.insert_one({
        "id": user_msg_id,
        "user_id": user_id,
        "role": "user",
        "content": user_message,
        "workout_id": request.workout_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    # 7. Appeler GPT-4o-mini pour générer la réponse
    llm_response, success, meta = await enrich_chat_response(
        user_message=user_message,
        context=context,
        conversation_history=[{"role": m.get("role"), "content": m.get("content")} for m in conversation_history],
        user_id=user_id
    )
    
    if not success or not llm_response:
        logger.warning(f"LLM chat failed: {meta}")
        raise HTTPException(
            status_code=503,
            detail="Le service de coaching IA n'est pas disponible actuellement." if language == "fr" else "The AI coaching service is currently unavailable."
        )
    
    response_text = llm_response
    
    # 8. Stocker la réponse assistant
    msg_id = str(uuid.uuid4())
    await db.conversations.insert_one({
        "id": msg_id,
        "user_id": user_id,
        "role": "assistant",
        "content": response_text,
        "workout_id": request.workout_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return CoachResponse(response=response_text, message_id=msg_id)



@api_router.get("/coach/history")
async def get_conversation_history(user_id: str = "default", limit: int = 50):
    """Get conversation history for a user"""
    messages = await db.conversations.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(limit)
    return messages


@api_router.delete("/coach/history")
async def clear_conversation_history(user_id: str = "default"):
    """Clear conversation history for a user"""
    result = await db.conversations.delete_many({"user_id": user_id})
    return {"deleted_count": result.deleted_count}


@api_router.get("/messages")
async def get_messages(limit: int = 20):
    """Get recent coach messages (legacy endpoint)"""
    messages = await db.conversations.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return messages


@api_router.post("/coach/guidance", response_model=GuidanceResponse)
async def get_adaptive_guidance(request: GuidanceRequest):
    """Generate adaptive training guidance based on recent workouts - 100% LOCAL ENGINE"""
    
    language = request.language or "en"
    user_id = request.user_id or "default"
    
    # Get recent workouts (last 14 days)
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(100)
    
    # Calculate training summary
    today = datetime.now(timezone.utc).date()
    cutoff_14d = today - timedelta(days=14)
    cutoff_7d = today - timedelta(days=7)
    
    recent_14d = []
    recent_7d = []
    
    for w in all_workouts:
        try:
            w_date = datetime.fromisoformat(w["date"].replace("Z", "+00:00").split("T")[0]).date()
            if w_date >= cutoff_14d:
                recent_14d.append(w)
            if w_date >= cutoff_7d:
                recent_7d.append(w)
        except (ValueError, TypeError, KeyError):
            continue
    
    # Use local engine for weekly review
    review = generate_weekly_review(
        workouts=recent_7d,
        previous_week_workouts=[w for w in recent_14d if w not in recent_7d],
        user_goal=None,
        language=language
    )
    
    # Determine status from metrics
    metrics = review.get("metrics", {})
    volume_change = metrics.get("volume_change_pct", 0)
    total_sessions = metrics.get("total_sessions", 0)
    
    # Calculate zone distribution
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    for w in recent_7d:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z, pct in zones.items():
                if z in zone_totals:
                    zone_totals[z] += (pct or 0)
            zone_count += 1
    
    z4_z5_avg = 0
    if zone_count > 0:
        z4_z5_avg = (zone_totals["z4"] + zone_totals["z5"]) / zone_count
    
    # Determine status
    if total_sessions == 0:
        status = "hold_steady"
    elif volume_change > 20 or z4_z5_avg > 35:
        status = "adjust"  # Need to recover
    elif volume_change < -20 or total_sessions < 2:
        status = "hold_steady"  # Build back up
    else:
        status = "maintain"
    
    # Build guidance text
    guidance_parts = [review["summary"]]
    guidance_parts.append(review["meaning"])
    guidance_parts.append(review["advice"])
    
    guidance = "\n\n".join(guidance_parts)
    
    # Store guidance in DB
    await db.guidance.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "status": status,
        "guidance": guidance,
        "language": language,
        "training_summary": {
            "last_7d": {
                "count": len(recent_7d),
                "total_km": round(sum(w.get("distance_km", 0) for w in recent_7d), 1)
            },
            "last_14d": {
                "count": len(recent_14d),
                "total_km": round(sum(w.get("distance_km", 0) for w in recent_14d), 1)
            }
        },
        "generated_at": datetime.now(timezone.utc).isoformat()
    })
    
    logger.info(f"Guidance generated (LOCAL): status={status}, user={user_id}")
    
    return GuidanceResponse(
        status=status,
        guidance=guidance,
        generated_at=datetime.now(timezone.utc).isoformat()
    )


@api_router.get("/coach/guidance/latest")
async def get_latest_guidance(user_id: str = "default"):
    """Get the most recent guidance for a user"""
    guidance = await db.guidance.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("generated_at", -1)]
    )
    if not guidance:
        return None
    return guidance


# ========== WEEKLY REVIEW (BILAN DE LA SEMAINE) ==========

class WeeklyReviewResponse(BaseModel):
    period_start: str
    period_end: str
    coach_summary: str  # 1 phrase max - CARTE 1
    coach_reading: str  # 2-3 phrases - CARTE 4
    recommendations: List[str]  # 1-2 actions - CARTE 5
    recommendations_followup: Optional[str] = None  # Feedback on last week's recommendations
    metrics: dict  # CARTE 3
    comparison: dict  # vs semaine precedente
    signals: List[dict]  # CARTE 2
    user_goal: Optional[dict] = None  # User's event goal
    generated_at: str


def calculate_review_metrics(workouts: List[dict], baseline_workouts: List[dict]) -> tuple:
    """Calculate metrics and comparison for weekly review"""
    if not workouts:
        metrics = {
            "total_sessions": 0,
            "total_distance_km": 0,
            "total_duration_min": 0,
        }
        comparison = {
            "sessions_diff": 0,
            "distance_diff_km": 0,
            "distance_diff_pct": 0,
            "duration_diff_min": 0,
        }
        return metrics, comparison
    
    # Current week metrics
    total_distance = sum(w.get("distance_km", 0) for w in workouts)
    total_duration = sum(w.get("duration_minutes", 0) for w in workouts)
    
    metrics = {
        "total_sessions": len(workouts),
        "total_distance_km": round(total_distance, 1),
        "total_duration_min": total_duration,
    }
    
    # Baseline comparison
    baseline_sessions = len(baseline_workouts) if baseline_workouts else 0
    baseline_distance = sum(w.get("distance_km", 0) for w in baseline_workouts) if baseline_workouts else 0
    baseline_duration = sum(w.get("duration_minutes", 0) for w in baseline_workouts) if baseline_workouts else 0
    
    # Calculate differences
    distance_diff_pct = 0
    if baseline_distance > 0:
        distance_diff_pct = round(((total_distance - baseline_distance) / baseline_distance) * 100)
    elif total_distance > 0:
        distance_diff_pct = 100
    
    comparison = {
        "sessions_diff": len(workouts) - baseline_sessions,
        "distance_diff_km": round(total_distance - baseline_distance, 1),
        "distance_diff_pct": distance_diff_pct,
        "duration_diff_min": total_duration - baseline_duration,
    }
    
    return metrics, comparison


def generate_review_signals(workouts: List[dict], baseline_workouts: List[dict]) -> List[dict]:
    """Generate visual signal indicators for weekly review - CARTE 2"""
    signals = []
    
    # Calculate volume change
    current_km = sum(w.get("distance_km", 0) for w in workouts)
    baseline_km = sum(w.get("distance_km", 0) for w in baseline_workouts) if baseline_workouts else 0
    
    if baseline_km > 0:
        volume_change = round(((current_km - baseline_km) / baseline_km) * 100)
    else:
        volume_change = 100 if current_km > 0 else 0
    
    # Volume signal
    if volume_change > 15:
        signals.append({"key": "load", "status": "up", "value": f"+{volume_change}%"})
    elif volume_change < -15:
        signals.append({"key": "load", "status": "down", "value": f"{volume_change}%"})
    else:
        signals.append({"key": "load", "status": "stable", "value": f"{volume_change:+}%" if volume_change != 0 else "="})
    
    # Intensity signal based on zone distribution
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    for w in workouts:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z, pct in zones.items():
                if z in zone_totals:
                    zone_totals[z] += pct
            zone_count += 1
    
    if zone_count > 0:
        avg_zones = {z: v / zone_count for z, v in zone_totals.items()}
        easy_pct = avg_zones.get("z1", 0) + avg_zones.get("z2", 0)
        hard_pct = avg_zones.get("z4", 0) + avg_zones.get("z5", 0)
        
        if easy_pct >= 70:
            signals.append({"key": "intensity", "status": "easy", "value": None})
        elif hard_pct >= 30:
            signals.append({"key": "intensity", "status": "hard", "value": None})
        else:
            signals.append({"key": "intensity", "status": "balanced", "value": None})
    else:
        signals.append({"key": "intensity", "status": "balanced", "value": None})
    
    # Regularity signal (sessions spread across days)
    unique_days = len(set(w.get("date", "")[:10] for w in workouts))
    regularity_pct = min(100, round((unique_days / 7) * 100)) if workouts else 0
    
    if regularity_pct >= 60:
        signals.append({"key": "consistency", "status": "high", "value": f"{regularity_pct}%"})
    elif regularity_pct >= 30:
        signals.append({"key": "consistency", "status": "moderate", "value": f"{regularity_pct}%"})
    else:
        signals.append({"key": "consistency", "status": "low", "value": f"{regularity_pct}%"})
    
    return signals


@api_router.get("/coach/digest")
async def get_weekly_review(user_id: str = "default", language: str = "en"):
    """Generate weekly training review (Bilan de la semaine) - 100% LOCAL ENGINE, NO LLM"""
    
    # Get all workouts
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(200)
    
    # Calculate date ranges
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=7)
    baseline_start = today - timedelta(days=14)
    
    # Filter workouts for current week and baseline
    current_week = []
    baseline_week = []
    
    for w in all_workouts:
        try:
            w_date = datetime.fromisoformat(w["date"].replace("Z", "+00:00").split("T")[0]).date()
            if week_start <= w_date <= today:
                current_week.append(w)
            elif baseline_start <= w_date < week_start:
                baseline_week.append(w)
        except (ValueError, TypeError, KeyError):
            continue
    
    # Calculate metrics and comparison (CARTE 3)
    metrics, comparison = calculate_review_metrics(current_week, baseline_week)
    
    # Generate signals (CARTE 2)
    signals = generate_review_signals(current_week, baseline_week)
    
    # Get user goal for context
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    # Generate review content using LOCAL ENGINE (NO LLM)
    review = generate_weekly_review(
        workouts=current_week,
        previous_week_workouts=baseline_week,
        user_goal=user_goal,
        language=language
    )
    
    coach_summary = review["summary"]
    coach_reading = review["meaning"]
    recommendations = [review["advice"]]
    recommendations_followup = review.get("recovery", "")
    
    # Store review
    review_id = str(uuid.uuid4())
    await db.digests.insert_one({
        "id": review_id,
        "user_id": user_id,
        "period_start": week_start.isoformat(),
        "period_end": today.isoformat(),
        "coach_summary": coach_summary,
        "coach_reading": coach_reading,
        "recommendations": recommendations,
        "recommendations_followup": recommendations_followup,
        "metrics": metrics,
        "comparison": comparison,
        "signals": signals,
        "user_goal": user_goal,
        "language": language,
        "generated_at": datetime.now(timezone.utc).isoformat()
    })
    
    logger.info(f"Weekly review generated for user {user_id}: {len(current_week)} workouts (LOCAL ENGINE)")
    
    return WeeklyReviewResponse(
        period_start=week_start.isoformat(),
        period_end=today.isoformat(),
        coach_summary=coach_summary,
        coach_reading=coach_reading,
        recommendations=recommendations,
        recommendations_followup=recommendations_followup,
        metrics=metrics,
        comparison=comparison,
        signals=signals,
        user_goal=user_goal,
        generated_at=datetime.now(timezone.utc).isoformat()
    )


@api_router.get("/coach/digest/latest")
async def get_latest_digest(user_id: str = "default"):
    """Get the most recent digest for a user"""
    digest = await db.digests.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("generated_at", -1)]
    )
    return digest


@api_router.get("/coach/digest/history")
async def get_digest_history(user_id: str = "default", limit: int = 10, skip: int = 0):
    """Get history of weekly digests for a user"""
    digests = await db.digests.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("generated_at", -1).skip(skip).limit(limit).to_list(length=limit)
    
    total = await db.digests.count_documents({"user_id": user_id})
    
    return {
        "digests": digests,
        "total": total,
        "has_more": skip + len(digests) < total
    }


# ========== RAG-ENRICHED ENDPOINTS ==========

@api_router.get("/rag/dashboard")
async def get_rag_dashboard(user_id: str = "default"):
    """Get RAG-enriched dashboard summary"""
    # Fetch workouts - use same logic as /api/workouts (no user_id filter since data has None)
    # This matches the main workouts endpoint behavior
    workouts = await db.workouts.find(
        {},  # No filter - workouts in DB have user_id=None
        {"_id": 0}
    ).sort("date", -1).limit(100).to_list(length=100)
    
    # Fetch previous bilans
    bilans = await db.digests.find(
        {},  # No filter for consistency
        {"_id": 0}
    ).sort("generated_at", -1).limit(8).to_list(length=8)
    
    # Fetch user goal
    user_goal = await db.user_goals.find_one({}, {"_id": 0})
    
    # Generate RAG-enriched summary
    result = generate_dashboard_rag(workouts, bilans, user_goal)
    
    return {
        "rag_summary": result["summary"],
        "metrics": result["metrics"],
        "points_forts": result["points_forts"],
        "points_ameliorer": result["points_ameliorer"],
        "tips": result["tips"],
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@api_router.get("/rag/weekly-review")
async def get_rag_weekly_review(user_id: str = "default", language: str = "fr"):
    """Get RAG-enriched weekly review with GPT-4o-mini enhancement"""
    # Fetch workouts
    workouts = await db.workouts.find(
        {},
        {"_id": 0}
    ).sort("date", -1).limit(50).to_list(length=50)
    
    # Fetch previous bilans
    bilans = await db.digests.find(
        {},
        {"_id": 0}
    ).sort("generated_at", -1).limit(8).to_list(length=8)
    
    # Fetch user goal
    user_goal = await db.user_goals.find_one({}, {"_id": 0})
    
    # Generate RAG-enriched review (calculs 100% Python local)
    result = generate_weekly_review_rag(workouts, bilans, user_goal)
    
    # Enrichissement via coach_service (cascade LLM → déterministe)
    enriched_summary, used_llm = await coach_weekly_review(
        rag_result=result,
        user_id=user_id,
        language=language
    )
    
    return {
        "rag_summary": enriched_summary,
        "metrics": result["metrics"],
        "comparison": result["comparison"],
        "points_forts": result["points_forts"],
        "points_ameliorer": result["points_ameliorer"],
        "tips": result["tips"],
        "enriched_by_llm": used_llm,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@api_router.get("/rag/workout/{workout_id}")
async def get_rag_workout_analysis(workout_id: str, user_id: str = "default", language: str = "fr"):
    """Get RAG-enriched workout analysis with GPT-4o-mini enhancement"""
    # Fetch the workout
    workout = await db.workouts.find_one(
        {"id": workout_id},
        {"_id": 0}
    )
    
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    # Fetch all workouts for comparison
    all_workouts = await db.workouts.find(
        {},
        {"_id": 0}
    ).sort("date", -1).limit(100).to_list(length=100)
    
    # Fetch user goal
    user_goal = await db.user_goals.find_one({}, {"_id": 0})
    
    # Generate RAG-enriched analysis (calculs 100% Python local)
    result = generate_workout_analysis_rag(workout, all_workouts, user_goal)
    
    # Enrichissement via coach_service (cascade LLM → déterministe)
    enriched_summary, used_llm = await coach_analyze_workout(
        workout=workout,
        rag_result=result,
        user_id=user_id,
        language=language
    )
    
    comparison = result["comparison"]
    points_forts = result["points_forts"]
    points_ameliorer = result["points_ameliorer"]

    # Localize the engine's structured English tokens (progression, strengths,
    # areas to improve) into the user's language (cached; EN = no-op).
    if (language or "en").lower() != "en":
        to_loc = {"progression": comparison.get("progression") or ""}
        for i, v in enumerate(points_forts):
            to_loc[f"pf_{i}"] = v
        for i, v in enumerate(points_ameliorer):
            to_loc[f"pa_{i}"] = v
        loc = await localization.localize_fields(to_loc, language, user_id)
        comparison = {**comparison, "progression": loc.get("progression") or comparison.get("progression")}
        points_forts = [loc.get(f"pf_{i}", v) for i, v in enumerate(points_forts)]
        points_ameliorer = [loc.get(f"pa_{i}", v) for i, v in enumerate(points_ameliorer)]

    return {
        "rag_summary": enriched_summary,
        "workout": result["workout"],
        "comparison": comparison,
        "points_forts": points_forts,
        "points_ameliorer": points_ameliorer,
        "tips": result["tips"],
        "rag_sources": result.get("rag_sources", {}),
        "enriched_by_llm": used_llm,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }



class MobileAnalysisResponse(BaseModel):
    workout_id: str
    coach_summary: str
    intensity: dict
    load: dict
    session_type: dict
    insight: Optional[str] = None
    guidance: Optional[str] = None


def calculate_mobile_signals(workout: dict, baseline: dict) -> dict:
    """Calculate signal cards for mobile workout analysis"""
    w_type = workout.get("type", "run")
    
    # Intensity card
    intensity = {
        "pace": None,
        "avg_hr": workout.get("avg_heart_rate"),
        "label": "normal"
    }
    
    if w_type == "run":
        pace = workout.get("avg_pace_min_km")
        if pace:
            mins = int(pace)
            secs = int((pace - mins) * 60)
            intensity["pace"] = f"{mins}:{str(secs).zfill(2)}/km"
    else:
        speed = workout.get("avg_speed_kmh")
        if speed:
            intensity["pace"] = f"{speed:.1f} km/h"
    
    # Compare HR to baseline for intensity label
    hr_score = 0
    if baseline and baseline.get("avg_heart_rate") and workout.get("avg_heart_rate"):
        hr_diff_pct = (workout["avg_heart_rate"] - baseline["avg_heart_rate"]) / baseline["avg_heart_rate"] * 100
        if hr_diff_pct > 5:
            intensity["label"] = "above_usual"
            hr_score = 1
        elif hr_diff_pct < -5:
            intensity["label"] = "below_usual"
            hr_score = -1
    
    # Load card
    distance = workout.get("distance_km", 0)
    duration = workout.get("duration_minutes", 0)
    
    load = {
        "distance_km": round(distance, 1),
        "duration_min": duration,
        "direction": "stable"
    }
    
    load_score = 0
    if baseline and baseline.get("avg_distance_km"):
        dist_diff = (distance - baseline["avg_distance_km"]) / baseline["avg_distance_km"] * 100
        if dist_diff > 15:
            load["direction"] = "up"
            load_score = 1
        elif dist_diff < -15:
            load["direction"] = "down"
            load_score = -1
    
    # Session Type card (Easy / Sustained / Hard)
    # Based on HR intensity + load combined
    combined_score = hr_score + load_score
    
    if combined_score >= 2:
        session_type_label = "hard"
    elif combined_score <= -1:
        session_type_label = "easy"
    elif hr_score == 1 or load_score == 1:
        session_type_label = "sustained"
    else:
        session_type_label = "easy" if hr_score == -1 else "sustained"
    
    # Also check zone distribution if available
    zones = workout.get("effort_zone_distribution", {})
    if zones:
        hard_zones = (zones.get("z4", 0) or 0) + (zones.get("z5", 0) or 0)
        easy_zones = (zones.get("z1", 0) or 0) + (zones.get("z2", 0) or 0)
        
        if hard_zones > 30:
            session_type_label = "hard"
        elif easy_zones > 80:
            session_type_label = "easy"
    
    session_type = {
        "label": session_type_label
    }
    
    return {
        "intensity": intensity,
        "load": load,
        "session_type": session_type
    }


@api_router.get("/coach/workout-analysis/{workout_id}")
async def get_mobile_workout_analysis(workout_id: str, language: str = "en", user_id: str = "default"):
    """Get mobile-first workout analysis with coach summary and signals - 100% LOCAL ENGINE"""
    
    # Get all workouts
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(100)
    
    # Find the workout
    workout = await db.workouts.find_one({"id": workout_id}, {"_id": 0})
    if not workout:
        workout = next((w for w in all_workouts if w["id"] == workout_id), None)
    
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    # Calculate baseline
    baseline = calculate_baseline_metrics(all_workouts, workout, days=14)
    
    # Calculate signal cards
    signals = calculate_mobile_signals(workout, baseline)
    
    # Build workout summary for AI with enriched data
    workout_summary = {
        "type": workout.get("type"),
        "distance_km": workout.get("distance_km"),
        "duration_min": workout.get("duration_minutes"),
        "moving_time_min": workout.get("moving_time_minutes"),
        "avg_hr": workout.get("avg_heart_rate"),
        "max_hr": workout.get("max_heart_rate"),
        "hr_zones": workout.get("effort_zone_distribution"),
        "avg_pace_min_km": workout.get("avg_pace_min_km"),
        "best_pace_min_km": workout.get("best_pace_min_km"),
        "pace_variability": workout.get("pace_stats", {}).get("pace_variability") if workout.get("pace_stats") else None,
        "avg_cadence_spm": workout.get("avg_cadence_spm"),
        "avg_speed_kmh": workout.get("avg_speed_kmh"),
        "max_speed_kmh": workout.get("max_speed_kmh"),
        "elevation_m": workout.get("elevation_gain_m")
    }
    
    baseline_summary = {
        "sessions": baseline.get("workout_count", 0) if baseline else 0,
        "avg_distance": baseline.get("avg_distance_km") if baseline else None,
        "avg_duration": baseline.get("avg_duration_min") if baseline else None,
        "avg_hr": baseline.get("avg_heart_rate") if baseline else None,
        "avg_pace": baseline.get("avg_pace") if baseline else None,
        "avg_cadence": baseline.get("avg_cadence") if baseline else None
    } if baseline else {}
    
    # Generate analysis using LOCAL ENGINE (NO LLM)
    analysis = generate_session_analysis(workout, baseline, language)

    # Localize the free-text fields into the user's language (cached, EN=no-op).
    _loc = await localization.localize_fields(
        {"summary": analysis["summary"], "meaning": analysis["meaning"], "advice": analysis["advice"]},
        language, user_id,
    )
    coach_summary = _loc["summary"]
    insight = _loc["meaning"]
    guidance = _loc["advice"]
    
    return MobileAnalysisResponse(
        workout_id=workout_id,
        coach_summary=coach_summary,
        intensity=signals["intensity"],
        load=signals["load"],
        session_type=signals["session_type"],
        insight=insight,
        guidance=guidance
    )



class DetailedAnalysisResponse(BaseModel):
    workout_id: str
    workout_name: str
    workout_date: str
    workout_type: str
    header: dict
    execution: dict
    meaning: dict
    recovery: dict
    advice: dict
    advanced: Optional[dict] = None


@api_router.get("/coach/detailed-analysis/{workout_id}")
async def get_detailed_analysis(workout_id: str, language: str = "en", user_id: str = "default"):
    """Get card-based detailed analysis for mobile view - 100% LOCAL ENGINE"""
    
    # Get all workouts
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(100)
    
    # Find the workout
    workout = await db.workouts.find_one({"id": workout_id}, {"_id": 0})
    if not workout:
        workout = next((w for w in all_workouts if w["id"] == workout_id), None)
    
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    # Calculate baseline
    baseline = calculate_baseline_metrics(all_workouts, workout, days=14)
    
    # Generate analysis using LOCAL ENGINE (NO LLM)
    analysis = generate_session_analysis(workout, baseline, language)

    # Localize the free-text fields into the user's language (cached, EN=no-op).
    _loc = await localization.localize_fields(
        {"summary": analysis["summary"], "meaning": analysis["meaning"],
         "recovery": analysis["recovery"], "advice": analysis["advice"]},
        language, user_id,
    )
    analysis["summary"] = _loc["summary"]
    analysis["meaning"] = _loc["meaning"]
    analysis["recovery"] = _loc["recovery"]
    analysis["advice"] = _loc["advice"]
    
    # Build header
    session_type = analysis.get("metrics", {}).get("session_type", "moderate")
    intensity_level = analysis.get("metrics", {}).get("intensity_level", "moderate")
    
    session_names = {
        "easy": "Sortie facile" if language == "fr" else "Easy Run",
        "moderate": "Sortie modérée" if language == "fr" else "Moderate Run",
        "hard": "Séance intense" if language == "fr" else "Hard Session",
        "very_hard": "Séance très intense" if language == "fr" else "Very Hard Session",
        "long": "Sortie longue" if language == "fr" else "Long Run",
        "short": "Sortie courte" if language == "fr" else "Short Run"
    }
    
    intensity_labels = {
        "easy": "Facile" if language == "fr" else "Easy",
        "moderate": "Modérée" if language == "fr" else "Moderate",
        "hard": "Soutenue" if language == "fr" else "Sustained",
        "very_hard": "Haute" if language == "fr" else "High"
    }
    
    # Calculate volume comparison
    distance = workout.get("distance_km", 0)
    avg_distance = baseline.get("avg_distance_km", distance) if baseline else distance
    
    if distance > avg_distance * 1.2:
        volume = "Plus long" if language == "fr" else "Longer"
    elif distance < avg_distance * 0.8:
        volume = "Plus court" if language == "fr" else "Shorter"
    else:
        volume = "Habituel" if language == "fr" else "Usual"
    
    # Check pace regularity
    pace_stats = workout.get("pace_stats", {})
    variability = pace_stats.get("pace_variability", 0) if pace_stats else 0
    regularity = "Variable" if variability > 0.5 else "Stable"
    
    header = {
        "context": analysis["summary"],
        "session_name": session_names.get(session_type, workout.get("name", "Séance"))
    }
    
    execution = {
        "intensity": intensity_labels.get(intensity_level, intensity_labels["moderate"]),
        "volume": volume,
        "regularity": regularity
    }
    
    meaning = {"text": analysis["meaning"]}
    recovery = {"text": analysis["recovery"]}
    advice = {"text": analysis["advice"]}
    
    # Build advanced comparisons
    comparison_parts = []
    zones = analysis.get("metrics", {}).get("zones", {})
    if zones:
        easy_pct = zones.get("easy", 0)
        hard_pct = zones.get("hard", 0)
        if language == "fr":
            comparison_parts.append(f"{easy_pct}% du temps en zone facile, {hard_pct}% en zone intense.")
        else:
            comparison_parts.append(f"{easy_pct}% time in easy zone, {hard_pct}% in hard zone.")
    
    if baseline and baseline.get("comparison"):
        hr_comp = baseline["comparison"].get("heart_rate_vs_baseline", {})
        if hr_comp:
            diff = hr_comp.get("difference_bpm", 0)
            if abs(diff) > 3:
                if language == "fr":
                    comparison_parts.append(f"FC {'+' if diff > 0 else ''}{diff:.0f} bpm vs baseline.")
                else:
                    comparison_parts.append(f"HR {'+' if diff > 0 else ''}{diff:.0f} bpm vs baseline.")
    
    advanced = {"comparisons": " ".join(comparison_parts) if comparison_parts else ""}
    
    logger.info(f"Detailed analysis generated (LOCAL) for workout {workout_id}")
    
    return DetailedAnalysisResponse(
        workout_id=workout_id,
        workout_name=workout.get("name", ""),
        workout_date=workout.get("date", ""),
        workout_type=workout.get("type", ""),
        header=header,
        execution=execution,
        meaning=meaning,
        recovery=recovery,
        advice=advice,
        advanced=advanced
    )


# ========== TERRA INTEGRATION ENDPOINTS ==========
# Terra is the primary wearable data aggregator replacing Strava.

class TerraConnectionStatus(BaseModel):
    connected: bool
    last_sync: Optional[str] = None
    workout_count: int = 0
    terra_user_id: Optional[str] = None


class TerraSyncResult(BaseModel):
    success: bool
    synced_count: int
    message: str


class TerraConnectRequest(BaseModel):
    token: str
    terra_user_id: Optional[str] = None


@api_router.get("/terra/status")
async def get_terra_status(user_id: str = "default"):
    """Get Terra connection status for a user."""
    token_doc = await db.terra_tokens.find_one({"user_id": user_id}, {"_id": 0})

    if not token_doc:
        return TerraConnectionStatus(connected=False)

    sync_info = await db.sync_history.find_one(
        {"user_id": user_id, "source": "terra"},
        {"_id": 0},
        sort=[("synced_at", -1)],
    )

    workout_count = await db.workouts.count_documents({
        "data_source": "terra",
        "user_id": user_id,
    })

    return TerraConnectionStatus(
        connected=True,
        last_sync=sync_info.get("synced_at") if sync_info else None,
        workout_count=workout_count,
        terra_user_id=token_doc.get("terra_user_id"),
    )


@api_router.post("/terra/connect")
async def terra_connect(req: TerraConnectRequest, user_id: str = "default"):
    """Save a Terra access token for a user (token-based auth flow).

    In production, replace this with a full Terra OAuth widget flow.
    The client obtains a Terra user token via the Terra Connect Widget and
    posts it here to persist the connection.
    """
    if not req.token:
        raise HTTPException(status_code=400, detail="Terra token is required")

    # Optionally verify the token by fetching the Terra user profile.
    terra_user = await fetch_terra_user(req.token)
    terra_user_id = req.terra_user_id or terra_user.get("user_id") or terra_user.get("id")

    await db.terra_tokens.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "access_token": req.token,
            "terra_user_id": terra_user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

    logger.info("Terra connected for user: %s (terra_user_id=%s)", user_id, terra_user_id)
    return {"success": True, "message": "Terra connected successfully", "terra_user_id": terra_user_id}


@api_router.post("/terra/sync", response_model=TerraSyncResult)
async def sync_terra(user_id: str = "default"):
    """Sync all Terra data for a user: workouts + daily metrics.

    Calls syncTerraWorkouts and syncDailyMetrics then regenerates the
    recovery score, training load, and workout recommendation.
    """
    token_doc = await db.terra_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        return TerraSyncResult(success=False, synced_count=0, message="Not connected to Terra")

    try:
        # Sync workouts from Terra
        workout_result = await syncTerraWorkouts(user_id, db)

        # Sync daily metrics (HRV, RHR, sleep)
        await syncDailyMetrics(user_id, db)

        # Recompute derived scores
        await computeTrainingLoad(user_id, db)
        await computeRecoveryScore(user_id, db)
        await generateWorkoutRecommendation(user_id, db)

        logger.info("Terra full sync completed for user: %s", user_id)
        return TerraSyncResult(
            success=True,
            synced_count=workout_result.get("synced_count", 0),
            message=workout_result.get("message", "Sync completed"),
        )
    except Exception as exc:
        logger.error("Terra sync error for user %s: %s", user_id, exc)
        return TerraSyncResult(success=False, synced_count=0, message=f"Sync failed: {exc}")


@api_router.post("/terra/sync-daily")
async def sync_terra_daily(user_id: str = "default"):
    """Sync daily health metrics from Terra (HRV, RHR, sleep).

    Useful for a lightweight, metrics-only refresh without re-importing workouts.
    """
    token_doc = await db.terra_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        raise HTTPException(status_code=400, detail="Not connected to Terra")

    try:
        metrics = await syncDailyMetrics(user_id, db)
        recovery = await computeRecoveryScore(user_id, db)
        recommendation = await generateWorkoutRecommendation(user_id, db)

        return {
            "success": True,
            "metrics": metrics,
            "recovery_score": recovery.get("recovery_score"),
            "fatigue_score": recovery.get("fatigue_score"),
            "recommendation": {
                "type": recommendation.get("type"),
                "duration": recommendation.get("duration"),
                "intensity": recommendation.get("intensity"),
            },
        }
    except Exception as exc:
        logger.error("Terra daily sync error for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail=f"Daily sync failed: {exc}")


@api_router.delete("/terra/disconnect")
async def disconnect_terra(user_id: str = "default"):
    """Disconnect Terra for a user (remove stored token)."""
    await db.terra_tokens.delete_one({"user_id": user_id})
    logger.info("Terra disconnected for user: %s", user_id)
    return {"success": True, "message": "Terra disconnected"}


@api_router.get("/terra/recovery")
async def get_terra_recovery(user_id: str = "default"):
    """Return the latest persisted recovery score for a user.

    If no score exists for today, triggers a fresh computation.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db.recovery_scores.find_one({"user_id": user_id, "date": today}, {"_id": 0})

    if not doc:
        # Try to compute if Terra is connected.
        token_doc = await db.terra_tokens.find_one({"user_id": user_id})
        if token_doc:
            doc = await computeRecoveryScore(user_id, db)
        else:
            return {"recovery_score": None, "fatigue_score": None, "status": "no_data"}

    return {
        "recovery_score": doc.get("recovery_score"),
        "fatigue_score": doc.get("fatigue_score"),
        "readiness": doc.get("readiness"),
        "status": doc.get("status"),
        "hrv_available": doc.get("hrv_available", False),
        "computed_at": doc.get("computed_at"),
    }


@api_router.get("/terra/recommendation")
async def get_terra_recommendation(user_id: str = "default"):
    """Return today's workout recommendation derived from Terra data.

    Triggers computation if no recommendation exists for today.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db.workout_recommendations.find_one(
        {"user_id": user_id, "date": today}, {"_id": 0}
    )

    if not doc:
        token_doc = await db.terra_tokens.find_one({"user_id": user_id})
        if token_doc:
            doc = await generateWorkoutRecommendation(user_id, db)
        else:
            return {"type": None, "duration": None, "intensity": None, "status": "no_data"}

    return {
        "type": doc.get("type"),
        "duration": doc.get("duration"),
        "intensity": doc.get("intensity"),
        "recovery_score": doc.get("recovery_score"),
        "acwr": doc.get("acwr"),
        "readiness": doc.get("readiness"),
        "computed_at": doc.get("computed_at"),
    }


@api_router.get("/terra/daily-metrics")
async def get_terra_daily_metrics(user_id: str = "default"):
    """Return the latest daily metrics (HRV, RHR, sleep) for a user."""
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db.daily_metrics.find_one({"user_id": user_id, "date": today}, {"_id": 0})

    if not doc:
        # Attempt sync if connected.
        token_doc = await db.terra_tokens.find_one({"user_id": user_id})
        if token_doc:
            doc = await syncDailyMetrics(user_id, db)
        else:
            return {"hrv": None, "rhr": None, "sleep_hours": None, "status": "no_data"}

    return {
        "date": doc.get("date"),
        "hrv": doc.get("hrv"),
        "rhr": doc.get("rhr"),
        "avg_hr": doc.get("avg_hr"),
        "sleep_hours": doc.get("sleep_hours"),
        "sleep_quality": doc.get("sleep_quality"),
        "synced_at": doc.get("synced_at"),
    }


# ========== CARDIO COACH RUNNING SCREEN ==========

# Returned when no wearable (Garmin/Terra) is connected: explicit "no data"
# state so the UI shows an empty/connect prompt instead of fabricated data.
_CARDIO_COACH_NO_DATA = {
    "mock": False,
    "no_data": True,
    "connected": False,
    "source": None,
    "message": "Connect your Garmin to see your readiness and daily metrics.",
    "recommendation": None,
    "recommendation_emoji": None,
    "recommendation_color": "gray",
    "next_workout": None,
    "reasons": [],
    "metrics": None,
    "history": [],
}


@api_router.get("/cardio-coach")
async def get_cardio_coach(user_id: str = "default", language: str = "fr"):
    """Return the full CardioCoach running-screen payload.

    Data source: 100% real Garmin (gccli). Resting HR + sleep come from gccli;
    training load / ACWR / fatigue ratio / readiness are computed from the real
    synced activities.

    Terra is implemented for POSSIBLE FUTURE USE but is NOT connected: when no
    Terra token exists (current state), the endpoint returns a NO_DATA payload
    (never mock data).
    """
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()

    # ----------------------------------------------------------------
    # Prefer REAL Garmin data when the Garmin connector is active.
    # Resting HR + sleep come from gccli; training load / ACWR / fatigue
    # ratio / readiness are computed from the real synced activities.
    # ----------------------------------------------------------------
    garmin_conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if garmin_conn and garmin_conn.get("connected"):
        try:
            from garmin.insights import compute_cardio_coach
            garmin_payload = await compute_cardio_coach(db, user_id, language)
            if garmin_payload:
                return garmin_payload
        except Exception as e:
            logger.warning(f"[cardio-coach] Garmin computation failed, falling back: {e}")

    # ----------------------------------------------------------------
    # Terra fallback — DORMANT (future use). No token = no data (no mock).
    # ----------------------------------------------------------------
    token_doc = await db.terra_tokens.find_one({"user_id": user_id}, {"_id": 0})
    if not token_doc:
        return _CARDIO_COACH_NO_DATA

    # ----------------------------------------------------------------
    # Daily metrics (sync today's if not yet stored).
    # ----------------------------------------------------------------
    daily_doc = await db.daily_metrics.find_one({"user_id": user_id, "date": today_iso})
    if not daily_doc:
        synced = await syncDailyMetrics(user_id, db)
        daily_doc = await db.daily_metrics.find_one({"user_id": user_id, "date": today_iso}) or {}

    hrv_today: Optional[float] = daily_doc.get("hrv")
    rhr_today: Optional[float] = daily_doc.get("rhr")
    raw_sleep_hours: Optional[float] = daily_doc.get("sleep_hours")
    # sleep_quality stored as 0-100 score or 0-1 fraction.
    raw_sleep_quality: Optional[float] = daily_doc.get("sleep_quality")

    # Normalise sleep efficiency to a 0-1 fraction.
    if raw_sleep_quality is not None:
        sleep_efficiency = raw_sleep_quality / 100.0 if raw_sleep_quality > 1.0 else raw_sleep_quality
    else:
        sleep_efficiency = 0.80  # Reasonable default

    sleep_hours = raw_sleep_hours or 7.0

    # ----------------------------------------------------------------
    # Baselines.
    # ----------------------------------------------------------------
    baseline_doc = await db.baselines.find_one({"user_id": user_id}) or {}
    hrv_baseline: Optional[float] = baseline_doc.get("baseline_hrv")
    rhr_baseline: Optional[float] = baseline_doc.get("baseline_rhr")

    # Use rolling 30-day mean from stored daily_metrics when no explicit baseline.
    if hrv_baseline is None or rhr_baseline is None:
        thirty_days_ago = (today - timedelta(days=30)).isoformat()
        hist_cursor = db.daily_metrics.find(
            {"user_id": user_id, "date": {"$gte": thirty_days_ago, "$lt": today_iso}},
            {"hrv": 1, "rhr": 1, "_id": 0},
        )
        hist_docs = await hist_cursor.to_list(30)
        if hist_docs:
            hrv_vals = [d["hrv"] for d in hist_docs if d.get("hrv") is not None]
            rhr_vals = [d["rhr"] for d in hist_docs if d.get("rhr") is not None]
            if hrv_baseline is None and hrv_vals:
                hrv_baseline = sum(hrv_vals) / len(hrv_vals)
            if rhr_baseline is None and rhr_vals:
                rhr_baseline = sum(rhr_vals) / len(rhr_vals)

    # Final fallbacks to sensible population averages.
    hrv_baseline = hrv_baseline or 55.0
    rhr_baseline = rhr_baseline or 55.0
    hrv_today = hrv_today or hrv_baseline

    # ----------------------------------------------------------------
    # Training load (ACWR).
    # ----------------------------------------------------------------
    load_doc = await db.training_load.find_one({"user_id": user_id, "date": today_iso})
    if not load_doc:
        load_doc = await computeTrainingLoad(user_id, db)
    acwr: float = float(load_doc.get("acwr") or 1.0)
    # Clamp to 0.1 minimum: prevents division-by-zero in fatigue_ratio and
    # avoids wild amplification from spuriously low ACWR readings.
    training_load = max(0.1, acwr)

    # ----------------------------------------------------------------
    # Fatigue computations (as specified).
    # hrv_delta: positive value means HRV dropped below baseline (worse recovery).
    # rhr_delta: positive value means RHR rose above baseline (more fatigued).
    # ----------------------------------------------------------------
    hrv_delta = float(hrv_baseline) - float(hrv_today)            # positive → HRV below baseline (bad)
    rhr_delta = float(rhr_today) - float(rhr_baseline)            # positive → RHR above baseline (bad)
    sleep_score = max(0.0, 8.0 - sleep_hours) + (1.0 - sleep_efficiency) * 2.0
    fatigue_physio = 0.5 * hrv_delta + 0.3 * rhr_delta + 0.2 * sleep_score
    # Fatigue Ratio = physiological fatigue only, centred on 1.0 (NOT divided by
    # ACWR; training load is reported separately). Higher = more fatigued.
    fatigue_ratio = 1.0 + max(0.0, fatigue_physio) / 10.0
    # ----------------------------------------------------------------
    # Recommendation.
    # ----------------------------------------------------------------
    if fatigue_ratio > 1.5:
        recommendation = "REST"
        recommendation_emoji = "🔴"
        recommendation_color = "red"
        next_workout_label = "Rest Day"
        next_workout_icon = "rest"
    elif fatigue_ratio > 1.2:
        recommendation = "EASY RUN"
        recommendation_emoji = "🟡"
        recommendation_color = "yellow"
        next_workout_label = "Easy Run – 45 min Z2"
        next_workout_icon = "run"
    else:
        recommendation = "RUN HARD"
        recommendation_emoji = "🟢"
        recommendation_color = "green"
        next_workout_label = "Intervals – 6 x 800 m"
        next_workout_icon = "run"

    # ----------------------------------------------------------------
    # Per-metric status colours.
    # ----------------------------------------------------------------
    hrv_status = "green" if hrv_delta <= 5 else ("yellow" if hrv_delta <= 10 else "red")
    rhr_status = "green" if rhr_delta <= 3 else ("yellow" if rhr_delta <= 7 else "red")
    sleep_status = "green" if sleep_score <= 1.0 else ("yellow" if sleep_score <= 2.5 else "red")
    load_status = "green" if 0.8 <= acwr <= 1.3 else ("yellow" if acwr <= 1.5 else "red")
    fatigue_status = "green" if fatigue_ratio <= 1.2 else ("yellow" if fatigue_ratio <= 1.5 else "red")

    # ----------------------------------------------------------------
    # Human-readable reasons.
    # ----------------------------------------------------------------
    hrv_prefix = "+" if hrv_delta >= 0 else ""  # "+" = below baseline; "-" = above baseline
    rhr_prefix = "+" if rhr_delta >= 0 else ""  # "+" = above baseline
    reasons = [
        f"HRV deviation {hrv_prefix}{hrv_delta:.1f} ms vs baseline",
        f"RHR {rhr_prefix}{rhr_delta:.1f} bpm vs baseline",
        f"Sleep {sleep_hours:.1f} h at {sleep_efficiency * 100:.0f}% efficiency",
        f"Training Load (ACWR) {acwr:.2f}",
        f"Fatigue Ratio {fatigue_ratio:.2f}",
    ]

    # ----------------------------------------------------------------
    # 7-day history from daily_metrics.
    # ----------------------------------------------------------------
    seven_days_ago = (today - timedelta(days=7)).isoformat()
    hist_cursor = db.daily_metrics.find(
        {"user_id": user_id, "date": {"$gte": seven_days_ago, "$lte": today_iso}},
        {"date": 1, "hrv": 1, "rhr": 1, "sleep_hours": 1, "sleep_quality": 1, "_id": 0},
    ).sort("date", 1)
    hist_docs = await hist_cursor.to_list(7)

    history = []
    day_abbrevs = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for doc in hist_docs:
        doc_date = doc.get("date", "")
        try:
            d = datetime.fromisoformat(doc_date)
            day_label = day_abbrevs[d.weekday()]
        except Exception:
            day_label = doc_date[-2:] if doc_date else "?"

        doc_hrv = doc.get("hrv") or hrv_baseline
        doc_hrv_delta = float(hrv_baseline) - float(doc_hrv)
        doc_rhr = doc.get("rhr") or rhr_baseline
        doc_rhr_delta = float(doc_rhr) - float(rhr_baseline)
        doc_sleep = doc.get("sleep_hours") or 7.0
        doc_sq = doc.get("sleep_quality")
        if doc_sq is not None:
            doc_eff = doc_sq / 100.0 if doc_sq > 1.0 else doc_sq
        else:
            doc_eff = 0.80
        doc_sleep_score = max(0.0, 8.0 - doc_sleep) + (1.0 - doc_eff) * 2.0
        doc_fatigue_physio = 0.5 * doc_hrv_delta + 0.3 * doc_rhr_delta + 0.2 * doc_sleep_score
        doc_fatigue_ratio = 1.0 + max(0.0, doc_fatigue_physio) / 10.0

        history.append({
            "day": day_label,
            "date": doc_date,
            "hrv": round(float(doc_hrv), 1),
            "training_load": round(training_load, 2),
            "fatigue_ratio": round(doc_fatigue_ratio, 2),
        })

    # Leave history empty if fewer than 7 days of data (no mock padding).
    if not history:
        history = []

    return {
        "mock": False,
        "recommendation": recommendation,
        "recommendation_emoji": recommendation_emoji,
        "recommendation_color": recommendation_color,
        "next_workout": {"label": next_workout_label, "icon": next_workout_icon},
        "metrics": {
            "hrv_today": round(float(hrv_today), 1),
            "hrv_baseline": round(float(hrv_baseline), 1),
            "hrv_delta": round(hrv_delta, 1),
            "hrv_status": hrv_status,
            "rhr_today": round(float(rhr_today), 1),
            "rhr_baseline": round(float(rhr_baseline), 1),
            "rhr_delta": round(rhr_delta, 1),
            "rhr_status": rhr_status,
            "sleep_hours": round(sleep_hours, 1),
            "sleep_efficiency": round(sleep_efficiency, 2),
            "sleep_score": round(sleep_score, 2),
            "sleep_status": sleep_status,
            "training_load": round(acwr, 2),
            "training_load_status": load_status,
            "fatigue_physio": round(fatigue_physio, 2),
            "fatigue_ratio": round(fatigue_ratio, 2),
            "fatigue_status": fatigue_status,
        },
        "reasons": reasons,
        "history": history,
    }


# ========== PREMIUM SUBSCRIPTION (STRIPE) ==========


class SubscriptionStatusResponse(BaseModel):
    tier: str = "free"
    tier_name: str = "Gratuit"
    is_premium: bool = False
    subscription_id: Optional[str] = None
    billing_period: Optional[str] = None  # "monthly" or "annual"
    expires_at: Optional[str] = None
    messages_used: int = 0
    messages_limit: int = 10
    messages_remaining: int = 10
    is_unlimited: bool = False


class CreateCheckoutRequest(BaseModel):
    origin_url: str
    tier: str = "starter"  # starter, confort, pro
    billing_period: str = "monthly"  # monthly, annual


class CreateCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default"
    use_local_llm: bool = False  # True if using WebLLM on client
    language: Optional[str] = "en"  # Response language: "en" or "fr"


class ChatResponse(BaseModel):
    response: str
    message_id: str
    messages_remaining: int
    messages_limit: int
    is_unlimited: bool = False
    suggestions: List[str] = []  # Suggested follow-up questions
    category: str = ""  # Detected intent category


class ChatHistoryItem(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str


class SubscriptionTierInfo(BaseModel):
    id: str
    name: str
    price_monthly: float
    price_annual: float
    messages_limit: int
    unlimited: bool = False
    description: str


# ========== TRAINING MODELS ==========

class TrainingGoalRequest(BaseModel):
    goal_type: str = Field(..., description="Type d'objectif: 5K, 10K, SEMI, MARATHON, ULTRA")
    event_date: str = Field(..., description="Date de l'événement (YYYY-MM-DD)")
    event_name: Optional[str] = Field(None, description="Nom de la course")

class TrainingGoalResponse(BaseModel):
    success: bool
    goal_type: str
    event_name: Optional[str]
    event_date: str
    cycle_weeks: int
    current_week: int
    phase: str
    phase_info: dict

class TrainingPlanResponse(BaseModel):
    goal: Optional[dict]
    current_week: int
    total_weeks: int
    phase: str
    phase_info: dict
    recommendation: dict
    context: dict
    days_until_event: Optional[int]


# ========== TRAINING ENDPOINTS ==========

@api_router.post("/training/set-goal")
async def set_training_goal(
    goal: str = Query(..., description="10K | SEMI | MARATHON"),
    user: dict = Depends(auth_user)
):
    """
    Définit l'objectif principal du cycle.
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]:
        return {"error": "Invalid goal"}
    
    goal_upper = goal.upper()
    
    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": {
            "goal": goal_upper,
            "start_date": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    
    logger.info(f"[Training] Goal set for user {user['id']}: {goal_upper}")
    
    return {"status": "updated", "goal": goal_upper}


@api_router.get("/training/plan")
async def get_training_plan_v2(user: dict = Depends(auth_user)):
    """
    Generate or update the dynamic training plan
    based on latest fitness data.
    """
    return await generate_dynamic_training_plan(db, user["id"])


@api_router.post("/training/refresh")
async def refresh_training_plan(sessions: int = None, user: dict = Depends(auth_user)):
    """
    Force complete plan recalculation.
    sessions: number of desired sessions (3, 4, 5, 6)
    """
    # Clear cache for this user
    from coach_service import _plan_cache
    keys_to_remove = [k for k in _plan_cache if user["id"] in k]
    for k in keys_to_remove:
        del _plan_cache[k]

    # Save number of sessions if specified
    if sessions and sessions in [3, 4, 5, 6]:
        await db.training_prefs.update_one(
            {"user_id": user["id"]},
            {"$set": {"sessions_per_week": sessions}},
            upsert=True
        )
    
    return await generate_dynamic_training_plan(db, user["id"], sessions_override=sessions)


@api_router.delete("/training/goal")
async def delete_training_goal(user_id: str = "default"):
    """Delete the training goal"""

    result = await db.training_goals.delete_one({"user_id": user_id})
    await db.training_context.delete_one({"user_id": user_id})
    await db.training_cycles.delete_one({"user_id": user_id})

    return {
        "success": result.deleted_count > 0,
        "message": "Goal deleted" if result.deleted_count > 0 else "No goal found"
    }


@api_router.get("/training-plan")
async def get_training_plan(user: dict = Depends(auth_user)):
    """
    Retrieve the dynamic training plan for the user.
    Automatically generates sessions via LLM based on the cycle.
    """
    return await generate_dynamic_training_plan(db, user["id"])


@api_router.post("/training-plan/set-goal")
async def set_training_plan_goal(goal: str, user: dict = Depends(auth_user)):
    """
    Set the training goal (10K, SEMI, MARATHON, etc.)
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]:
        return {"error": "Invalid goal"}
    
    goal_upper = goal.upper()
    config = GOAL_CONFIG[goal_upper]
    
    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": {
            "goal": goal_upper,
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    
    logger.info(f"[Training] Goal updated for user {user['id']}: {goal_upper}")
    
    return {
        "status": "updated",
        "goal": goal_upper,
        "cycle_weeks": config["cycle_weeks"],
        "description": config["description"]
    }


# Garder l'ancien endpoint pour compatibilité
@api_router.get("/training/dynamic-plan")
async def get_dynamic_training_plan_legacy(user_id: str = "default"):
    """Legacy endpoint - utiliser /training-plan à la place"""
    return await generate_dynamic_training_plan(db, user_id)


@api_router.get("/training/goals")
async def get_available_goals():
    """Liste les types d'objectifs disponibles"""
    return {
        "goals": [
            {
                "type": goal_type,
                "description": config["description"],
                "cycle_weeks": config["cycle_weeks"],
                "long_run_ratio": config["long_run_ratio"],
                "intensity_pct": config["intensity_pct"]
            }
            for goal_type, config in GOAL_CONFIG.items()
        ]
    }


@api_router.post("/training/feedback")
async def submit_training_feedback(
    date: str,
    workout_id: str,
    status: str,
    user: dict = Depends(auth_user)
):
    """
    Store user feedback for a training session.

    Args:
        date: ISO date string (YYYY-MM-DD)
        workout_id: Unique identifier for the workout/session
        status: 'done' or 'missed'
    """
    if status not in ["done", "missed"]:
        raise HTTPException(status_code=400, detail="Status must be 'done' or 'missed'")

    feedback_doc = {
        "user_id": user["id"],
        "date": date,
        "workout_id": workout_id,
        "status": status,
        "created_at": datetime.now(timezone.utc)
    }

    # Upsert to avoid duplicates
    await db.training_feedback.update_one(
        {"user_id": user["id"], "date": date, "workout_id": workout_id},
        {"$set": feedback_doc},
        upsert=True
    )

    logger.info(f"[Training] Feedback saved for user {user['id']}: {date} - {workout_id} - {status}")

    return {
        "status": "success",
        "feedback": feedback_doc
    }


@api_router.get("/training/today")
async def get_today_adaptive_session(user: dict = Depends(auth_user)):
    """
    Returns today's adaptive training session.

    Combines:
    - Planned session from LLM-generated plan
    - Current fatigue level from /api/cardio-coach
    - Historical feedback

    Adaptation logic:
    - Green (fatigue_ratio <= 1.2): Keep session as planned
    - Orange (1.2 < fatigue_ratio <= 1.5): Reduce intensity/duration -20%, convert intervals to easy
    - Red (fatigue_ratio > 1.5): Convert to recovery/Z1, reduce duration -40 to -50%
    """
    from datetime import date as date_class

    # Get today's date
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()
    day_name = today.strftime("%A")

    # 1. Get the planned session for this week
    plan = await generate_dynamic_training_plan(db, user["id"])
    sessions = plan.get("plan", {}).get("sessions", [])
    # VMA is the single source of truth for all target paces.
    vma = plan.get("vma") or (plan.get("context", {}) or {}).get("vma")

    # Find today's session by day name
    planned_session = None
    for session in sessions:
        if session.get("day", "").lower() == day_name.lower():
            planned_session = session
            break

    if not planned_session:
        return {
            "status": "no_session",
            "message": "No session planned for today",
            "date": today_iso,
            "day": day_name
        }

    # 2. Get current fatigue level from cardio-coach
    # Use a direct call without auth to avoid circular dependency
    # Falls back to neutral defaults if cardio-coach is unavailable
    fatigue_data_source = "garmin"
    try:
        cardio_coach_data = await get_cardio_coach(user_id=user["id"])
        _cc_metrics = cardio_coach_data.get("metrics", {}) or {}
        fatigue_ratio = _cc_metrics.get("fatigue_ratio")
        fatigue_status = _cc_metrics.get("fatigue_status")
        run_readiness = _cc_metrics.get("run_readiness")
        recommendation = cardio_coach_data.get("recommendation")
        recommendation_color = cardio_coach_data.get("recommendation_color")
        
        # Check if any critical value is None (would cause float() error downstream)
        if fatigue_ratio is None or fatigue_status is None:
            raise ValueError("Missing fatigue metrics from cardio-coach")
            
    except Exception as e:
        # Neutral defaults if cardio-coach is unavailable (no mock dependency).
        logger.warning(f"[TrainingToday] cardio-coach unavailable, using neutral defaults: {e}")
        fatigue_data_source = "default"
        fatigue_ratio = 1.0
        fatigue_status = "green"
        run_readiness = 100
        recommendation = "RUN HARD"
        recommendation_color = "green"

    # 3. Get historical feedback for this user
    feedback_cursor = db.training_feedback.find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).sort("date", -1).limit(10)
    recent_feedback = await feedback_cursor.to_list(10)

    # 4. Apply adaptation logic — the Run Readiness RECOMMENDATION is the SOURCE
    # OF TRUTH. An EASY RUN / REST recommendation can NEVER leave the session
    # unchanged. All target paces are recomputed from the estimated VMA.
    adaptive_session, adaptation_applied, adaptation_reason = adapt_session_to_readiness(
        planned_session, recommendation, recommendation_color, run_readiness, vma
    )


    # 5. Return both original and adaptive sessions
    return {
        "status": "success",
        "date": today_iso,
        "day": day_name,
        "planned_session": planned_session,
        "adaptive_session": adaptive_session if adaptation_applied else None,
        "adaptation_applied": adaptation_applied,
        "adaptation_reason": adaptation_reason,
        "fatigue": {
            "fatigue_ratio": round(fatigue_ratio, 2),
            "fatigue_status": fatigue_status,
            "run_readiness": run_readiness,
            "recommendation": recommendation,
            "recommendation_color": recommendation_color,
            "data_source": fatigue_data_source
        },
        "vma": vma,
        "vma_confidence": plan.get("vma_confidence"),
        "recent_feedback": recent_feedback
    }


@api_router.get("/training/metrics")
async def get_training_metrics(user: dict = Depends(auth_user)):
    """
    Returns training metrics: ACWR, TSB, load, monotony.
    Used by Dashboard to display fitness status.
    """
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)

    # Retrieve activities (user-scoped to avoid mixing other users' data)
    user_filter = {
        "$or": [
            {"user_id": user["id"]},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ]
    }
    activities_7 = await db.workouts.find({
        **user_filter,
        "date": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)

    activities_28 = await db.workouts.find({
        **user_filter,
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)
    
    # Calculer les charges (en km, simplifié)
    def get_distance(a):
        dist = a.get("distance_km", 0)
        return dist
    
    load_7 = sum(get_distance(a) for a in activities_7)
    load_28 = sum(get_distance(a) for a in activities_28)
    
    # ACWR & TSB — distance-based fallback (used only if no Garmin activities)
    chronic_avg = load_28 / 4 if load_28 > 0 else 1
    acwr = round(load_7 / chronic_avg, 2) if chronic_avg > 0 else 1.0
    ctl = load_28 / 4  # Approximation fitness
    atl = load_7  # Fatigue récente
    tsb = round(ctl - atl, 1)

    # SINGLE SOURCE OF TRUTH: align ACWR/CTL/ATL/TSB with the Dashboard
    # (duration-based load on real Garmin activities). load_7/load_28 below
    # stay distance-based (km) for the "THIS WEEK" / "28D LOAD" cards.
    try:
        from garmin.insights import compute_training_load_metrics
        load_metrics = await compute_training_load_metrics(db, user["id"])
        if load_metrics:
            acwr = load_metrics["acwr"]
            ctl = load_metrics["ctl"]
            atl = load_metrics["atl"]
            tsb = load_metrics["tsb"]
    except Exception as e:
        logger.warning(f"[training/metrics] Garmin load metrics unavailable, using distance fallback: {e}")
    
    # Calculer la monotonie (7 derniers jours)
    daily_loads = []
    for i in range(7):
        day = (today - timedelta(days=i)).date()
        day_load = 0
        for a in activities_7:
            try:
                a_date_str = a.get("start_date_local", a.get("date", ""))
                if a_date_str:
                    a_date = datetime.fromisoformat(a_date_str.replace("Z", "+00:00")).date()
                    if a_date == day:
                        day_load += get_distance(a)
            except:
                pass
        daily_loads.append(day_load)
    
    # Monotonie = moyenne / écart-type
    if daily_loads and len(daily_loads) >= 2:
        avg_load = sum(daily_loads) / len(daily_loads)
        variance = sum((x - avg_load) ** 2 for x in daily_loads) / len(daily_loads)
        std = variance ** 0.5
        monotony = round(avg_load / std, 2) if std > 0 else 0
    else:
        monotony = 0
    
    # Strain = Load * Monotony
    strain = round(load_7 * monotony, 0) if monotony > 0 else 0
    
    # Interpréter ACWR
    if acwr < 0.8:
        acwr_status = "low"
        acwr_label = "Sous-entraînement"
    elif acwr <= 1.3:
        acwr_status = "optimal"
        acwr_label = "Zone optimale"
    elif acwr <= 1.5:
        acwr_status = "warning"
        acwr_label = "Zone à risque"
    else:
        acwr_status = "danger"
        acwr_label = "Danger"
    
    # Interpréter TSB
    if tsb > 10:
        tsb_status = "fresh"
        tsb_label = "Très frais"
    elif tsb > 0:
        tsb_status = "ready"
        tsb_label = "Prêt"
    elif tsb > -10:
        tsb_status = "training"
        tsb_label = "En charge"
    else:
        tsb_status = "fatigued"
        tsb_label = "Fatigué"
    
    return {
        "acwr": acwr,
        "acwr_status": acwr_status,
        "acwr_label": acwr_label,
        "tsb": tsb,
        "tsb_status": tsb_status,
        "tsb_label": tsb_label,
        "load_7": round(load_7, 1),
        "load_28": round(load_28, 1),
        "monotony": monotony,
        "strain": strain,
        "ctl": round(ctl, 1),
        "atl": round(atl, 1)
    }


@api_router.get("/training/race-predictions")
async def get_race_predictions(user: dict = Depends(auth_user)):
    """
    Prédit les temps de course pour 5K, 10K, Semi, Marathon, Ultra
    basé sur le profil d'entraînement de l'athlète.
    Utilise une fenêtre de 6 semaines (42 jours) pour la VMA.
    """
    today = datetime.now(timezone.utc)
    six_weeks_ago = today - timedelta(days=42)  # 6 semaines comme pour VO2MAX
    
    # Récupérer les activités des 6 dernières semaines
    activities = await db.workouts.find({
        "date": {"$gte": six_weeks_ago.isoformat()}
    }).to_list(500)
    
    if not activities:
        return {
            "has_data": False,
            "message": "Not enough data to predict. Keep training!",
            "predictions": []
        }

    # Extract key metrics
    def get_distance(a):
        dist = a.get("distance", 0)
        if dist > 1000:
            return dist / 1000
        return a.get("distance_km", dist)
    
    def get_duration_minutes(a):
        """Retourne la durée en minutes"""
        moving_time = a.get("moving_time", 0)
        if moving_time > 0:
            return moving_time / 60
        elapsed = a.get("elapsed_time", 0)
        if elapsed > 0:
            return elapsed / 60
        return a.get("duration_minutes", 0)
    
    def get_pace(a):
        # Pace en min/km
        pace = a.get("avg_pace_min_km")
        if pace:
            return pace
        # Calculer depuis vitesse moyenne (m/s)
        speed = a.get("average_speed", 0)
        if speed > 0:
            return (1000 / speed) / 60
        # Calculer depuis distance/durée
        dist = get_distance(a)
        duration_min = get_duration_minutes(a)
        if dist > 0 and duration_min > 0:
            return duration_min / dist
        return None
    
    # Collecter les données
    total_km = 0
    total_sessions = 0
    paces = []
    long_runs = []  # Sorties > 15km
    vma_efforts = []  # Efforts >= 6 min pour calcul VMA
    distances = []
    
    MIN_VMA_DURATION = 6  # Minutes minimum pour calcul VMA
    
    for a in activities:
        dist = get_distance(a)
        pace = get_pace(a)
        duration_min = get_duration_minutes(a)
        
        if dist > 0:
            total_km += dist
            total_sessions += 1
            distances.append(dist)
            
            if pace and 3 < pace < 10:  # Pace réaliste
                paces.append(pace)
                
                # Pour la VMA : effort >= 6 minutes ET allure rapide (< 5:30/km)
                if duration_min >= MIN_VMA_DURATION and pace < 5.5:
                    vma_efforts.append({
                        "distance": dist, 
                        "pace": pace, 
                        "duration": duration_min,
                        "speed_kmh": 60 / pace
                    })
                
                if dist >= 15:  # Sortie longue
                    long_runs.append({"distance": dist, "pace": pace})
    
    if not paces:
        return {
            "has_data": False,
            "message": "Not enough pace data. Make sure your sessions have GPS data.",
            "predictions": []
        }

    # Calculate basic metrics
    weekly_km = total_km / 6  # 6 semaines
    avg_pace = sum(paces) / len(paces)
    best_pace = min(paces) if paces else avg_pace
    max_long_run = max(distances) if distances else 0
    
    # Estimer la VMA (Vitesse Maximale Aérobie)
    # Basé sur les efforts >= 6 minutes (physiologiquement représentatif)
    vma_method = "estimated"
    
    if vma_efforts:
        # Prendre le meilleur effort de >= 6 minutes
        best_vma_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
        best_sustained_speed = best_vma_effort["speed_kmh"]
        
        # La VMA est environ 5-10% au-dessus de l'allure soutenue sur 6+ min
        # Plus l'effort est long, plus on est proche de la VMA
        duration = best_vma_effort["duration"]
        if duration >= 20:
            # Effort long (20+ min) = environ 85% VMA → VMA = vitesse / 0.85
            estimated_vma = best_sustained_speed / 0.85
        elif duration >= 12:
            # Effort moyen (12-20 min) = environ 90% VMA
            estimated_vma = best_sustained_speed / 0.90
        else:
            # Effort court (6-12 min) = environ 95% VMA
            estimated_vma = best_sustained_speed / 0.95
        
        vma_method = f"effort_{int(duration)}min"
    else:
        # Pas d'effort rapide >= 6 min, estimation depuis allure moyenne
        # L'allure moyenne d'endurance est environ 70% VMA
        avg_speed_kmh = 60 / avg_pace
        estimated_vma = avg_speed_kmh / 0.70
        vma_method = "from_avg_pace"
    
    # Prédictions basées sur VMA et volume
    predictions = []
    
    # Facteurs de prédiction par distance
    race_configs = [
        {
            "distance": "5K",
            "km": 5,
            "vma_pct": 0.95,  # 5K = ~95% VMA
            "min_weekly_km": 15,
            "min_long_run": 8,
            "description": "5 kilomètres"
        },
        {
            "distance": "10K",
            "km": 10,
            "vma_pct": 0.90,  # 10K = ~90% VMA
            "min_weekly_km": 25,
            "min_long_run": 12,
            "description": "10 kilomètres"
        },
        {
            "distance": "Semi",
            "km": 21.1,
            "vma_pct": 0.82,  # Semi = ~82% VMA
            "min_weekly_km": 35,
            "min_long_run": 18,
            "description": "Semi-marathon"
        },
        {
            "distance": "Marathon",
            "km": 42.195,
            "vma_pct": 0.75,  # Marathon = ~75% VMA
            "min_weekly_km": 50,
            "min_long_run": 30,
            "description": "Marathon"
        },
        {
            "distance": "Ultra",
            "km": 50,
            "vma_pct": 0.65,  # Ultra = ~65% VMA
            "min_weekly_km": 70,
            "min_long_run": 35,
            "description": "Ultra-trail (50km)"
        }
    ]
    
    for config in race_configs:
        # Vitesse de course prédite
        race_speed = estimated_vma * config["vma_pct"]
        race_pace = 60 / race_speed  # min/km
        
        # Temps prédit
        predicted_minutes = config["km"] * race_pace
        
        # Ajuster selon le volume d'entraînement
        volume_factor = min(1.0, weekly_km / config["min_weekly_km"])
        if volume_factor < 0.7:
            # Volume insuffisant = temps plus lent
            predicted_minutes *= (1 + (1 - volume_factor) * 0.15)
        
        # Ajuster selon sortie longue max
        endurance_factor = min(1.0, max_long_run / config["min_long_run"])
        if endurance_factor < 0.8 and config["km"] > 10:
            predicted_minutes *= (1 + (1 - endurance_factor) * 0.10)
        
        # Formater le temps
        hours = int(predicted_minutes // 60)
        mins = int(predicted_minutes % 60)
        secs = int((predicted_minutes % 1) * 60)
        
        if hours > 0:
            time_str = f"{hours}h{mins:02d}"
            time_range = f"{hours}h{max(0,mins-3):02d} - {hours}h{mins+5:02d}"
        else:
            time_str = f"{mins}:{secs:02d}"
            time_range = f"{max(0,mins-2)}:{secs:02d} - {mins+3}:{secs:02d}"
        
        # Évaluer la capacité
        readiness_score = (volume_factor * 0.5 + endurance_factor * 0.5) * 100
        
        if readiness_score >= 80:
            readiness = "ready"
            readiness_label = "Prêt"
            readiness_color = "#22c55e"
        elif readiness_score >= 60:
            readiness = "possible"
            readiness_label = "Possible"
            readiness_color = "#f59e0b"
        elif readiness_score >= 40:
            readiness = "challenging"
            readiness_label = "Ambitieux"
            readiness_color = "#f97316"
        else:
            readiness = "not_ready"
            readiness_label = "Pas prêt"
            readiness_color = "#ef4444"
        
        # Allure prédite formatée
        pace_mins = int(race_pace)
        pace_secs = int((race_pace % 1) * 60)
        pace_str = f"{pace_mins}:{pace_secs:02d}/km"
        
        predictions.append({
            "distance": config["distance"],
            "distance_km": config["km"],
            "description": config["description"],
            "predicted_time": time_str,
            "predicted_range": time_range,
            "predicted_pace": pace_str,
            "readiness": readiness,
            "readiness_label": readiness_label,
            "readiness_color": readiness_color,
            "readiness_score": round(readiness_score),
            "volume_factor": round(volume_factor * 100),
            "endurance_factor": round(endurance_factor * 100)
        })
    
    return {
        "has_data": True,
        "athlete_profile": {
            "weekly_km": round(weekly_km, 1),
            "avg_pace": f"{int(avg_pace)}:{int((avg_pace % 1) * 60):02d}/km",
            "best_pace": f"{int(best_pace)}:{int((best_pace % 1) * 60):02d}/km",
            "max_long_run": round(max_long_run, 1),
            "estimated_vma": round(estimated_vma, 1),
            "estimated_vo2max": round(estimated_vma * 3.5, 1),
            "vma_method": vma_method,
            "vma_efforts_count": len(vma_efforts),
            "total_sessions_6w": total_sessions,
            "calculation_window": "6 weeks"
        },
        "predictions": predictions,
        "methodology": {
            "vma_min_duration": f"{MIN_VMA_DURATION} min",
            "vma_calculation": "Basé sur le meilleur effort ≥ 6 min. Effort 6-12min = ~95% VMA, 12-20min = ~90% VMA, 20+min = ~85% VMA.",
            "vo2max_formula": "VO2MAX (ml/kg/min) = VMA (km/h) × 3.5",
            "note": "Les prédictions sont des estimations. Un test VMA réel ou des temps de course donnent des prédictions plus précises."
        }
    }


@api_router.get("/training/vma-history")
async def get_vma_history(user: dict = Depends(auth_user)):
    """
    Retourne l'historique du VO2MAX sur les 12 derniers mois.
    2 points par mois (1ère et 2ème quinzaine).
    VO2MAX (ml/kg/min) = VMA (km/h) × 3.5
    """
    today = datetime.now(timezone.utc)
    twelve_months_ago = today - timedelta(days=365)
    
    # Récupérer toutes les activités des 12 derniers mois
    activities = await db.workouts.find({
        "date": {"$gte": twelve_months_ago.isoformat()}
    }).to_list(2000)
    
    if not activities:
        return {"has_data": False, "history": []}
    
    # Helper functions
    def get_distance(a):
        return a.get("distance_km", 0)
    
    def get_duration(a):
        moving_time = a.get("moving_time", 0)
        if moving_time > 0:
            return moving_time / 60
        elapsed = a.get("elapsed_time", 0)
        if elapsed > 0:
            return elapsed / 60
        return a.get("duration_minutes", 0)
    
    def get_pace(a):
        pace = a.get("avg_pace_min_km")
        if pace:
            return pace
        speed = a.get("average_speed", 0)
        if speed > 0:
            return (1000 / speed) / 60
        dist = get_distance(a)
        duration_min = get_duration(a)
        if dist > 0 and duration_min > 0:
            return duration_min / dist
        return None
    
    def get_activity_date(a):
        date_str = a.get("start_date_local", a.get("date", ""))
        if date_str:
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                try:
                    return datetime.strptime(date_str[:10], "%Y-%m-%d")
                except:
                    return None
        return None
    
    # Helper function to calculate VO2MAX for a given set of activities
    def calculate_vo2max_for_activities(acts):
        MIN_VMA_DURATION = 6
        vma_efforts = []
        paces = []
        
        for a in acts:
            dist = get_distance(a)
            pace = get_pace(a)
            duration_min = get_duration(a)
            
            if dist > 0 and pace and 3 < pace < 10:
                paces.append(pace)
                # Efforts >= 6 min avec allure rapide
                if duration_min >= MIN_VMA_DURATION and pace < 5.5:
                    vma_efforts.append({
                        "pace": pace,
                        "duration": duration_min,
                        "speed_kmh": 60 / pace
                    })
        
        if not paces:
            return None, None
        
        avg_pace = sum(paces) / len(paces)
        
        if vma_efforts:
            best_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
            best_speed = best_effort["speed_kmh"]
            duration = best_effort["duration"]
            
            if duration >= 20:
                estimated_vma = best_speed / 0.85
            elif duration >= 12:
                estimated_vma = best_speed / 0.90
            else:
                estimated_vma = best_speed / 0.95
        else:
            avg_speed = 60 / avg_pace
            estimated_vma = avg_speed / 0.70
        
        vo2max = round(estimated_vma * 3.5, 1)
        
        # Exclude unrealistic values
        if vo2max > 70:
            return None, None
        
        return round(estimated_vma, 1), vo2max
    
    # Generate data points for 12 months (24 half-month periods)
    # Each point uses a ROLLING 6-WEEK WINDOW ending at that date
    month_names_fr = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    vo2max_history = []
    
    for i in range(24):  # 24 half-month periods over 12 months
        # Calculate the end date for this period
        months_back = 11 - (i // 2)
        half = 1 if (i % 2 == 0) else 2
        
        # Target date for this data point
        target_month_date = today - timedelta(days=30 * months_back)
        year = target_month_date.year
        month = target_month_date.month
        
        # End of period: 15th or end of month
        if half == 1:
            period_end = datetime(year, month, 15, tzinfo=timezone.utc)
        else:
            # Last day of month
            if month == 12:
                period_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
            else:
                period_end = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        
        # 6-week window ending at period_end
        period_start = period_end - timedelta(days=42)
        
        # Filter activities within this 6-week window
        def is_in_window(a):
            activity_date = get_activity_date(a)
            if activity_date is None:
                return False
            if activity_date.tzinfo is None:
                activity_date = activity_date.replace(tzinfo=timezone.utc)
            return period_start <= activity_date <= period_end
        
        window_activities = [a for a in activities if is_in_window(a)]
        
        # Calculate VO2MAX for this window
        vma, vo2max = calculate_vo2max_for_activities(window_activities)
        
        month_name = month_names_fr[month - 1]
        period_label = f"{month_name} {half}"
        period_key = f"{year}-{month:02d}-{half}"
        
        vo2max_history.append({
            "period": period_key,
            "period_label": period_label,
            "month": f"{year}-{month:02d}",
            "month_label": month_name,
            "half": half,
            "vma": vma,
            "vo2max": vo2max,
            "sessions": len(window_activities),
            "window_days": 42
        })
    
    result_history = vo2max_history
    
    # Current VO2MAX = last non-null value from the graph (already based on 6 weeks)
    current_vma = None
    current_vo2max = None
    for h in reversed(result_history):
        if h["vma"] is not None:
            current_vma = h["vma"]
            current_vo2max = h["vo2max"]
            break
    
    # Calculate trend (based on VO2MAX over 12 months)
    valid_vo2max = [h["vo2max"] for h in result_history if h["vo2max"] is not None]
    if len(valid_vo2max) >= 2:
        trend = valid_vo2max[-1] - valid_vo2max[0]
        trend_pct = (trend / valid_vo2max[0]) * 100 if valid_vo2max[0] > 0 else 0
    else:
        trend = 0
        trend_pct = 0
    
    return {
        "has_data": len(valid_vo2max) > 0 or current_vo2max is not None,
        "current_vma": current_vma,
        "current_vo2max": current_vo2max,
        "calculation_window": "6 weeks",
        "trend": round(trend, 1),
        "trend_pct": round(trend_pct, 1),
        "period_count": 24,
        "months": 12,
        "history": result_history
    }


@api_router.get("/training/full-cycle")
async def get_full_training_cycle(
    user: dict = Depends(auth_user),
    lang: str = Query("en", description="Language for phase and session labels (en, fr)")
):
    """
    Returns the full training cycle overview with all weeks.
    Phase names/focus and session type keys are returned; frontend translates keys via i18n.
    """
    # Retrieve user cycle
    cycle = await db.training_cycles.find_one({"user_id": user["id"]})

    if not cycle:
        # Create a default cycle
        default_cycle = {
            "user_id": user["id"],
            "goal": "SEMI",
            "start_date": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc)
        }
        await db.training_cycles.insert_one(default_cycle)
        cycle = await db.training_cycles.find_one({"user_id": user["id"]})

    goal = cycle.get("goal", "SEMI")
    config = GOAL_CONFIG.get(goal, GOAL_CONFIG["SEMI"])
    # Use readiness-adjusted cycle length stored by the detailed plan engine so
    # phases (and therefore target_km per week) match the detailed plan exactly.
    total_weeks = cycle.get("adjusted_weeks") or config["cycle_weeks"]

    # Retrieve session preferences
    prefs = await db.training_prefs.find_one({"user_id": user["id"]})
    sessions_per_week = prefs.get("sessions_per_week", 4) if prefs else 4

    # Calculate current week
    start_date = cycle.get("start_date")
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    current_week = compute_week_number(start_date.date() if isinstance(start_date, datetime) else start_date)

    # Retrieve athlete's current volume (based on last 28 days)
    today = datetime.now(timezone.utc)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    workouts_28 = await db.workouts.find({
        "$or": [
            {"user_id": user["id"]},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ],
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)
    
    km_28 = sum(w.get("distance_km", 0) for w in workouts_28)
    base_weekly_km = km_28 / 4 if km_28 > 0 else 25  # Base weekly volume (athlete's recent avg)

    # Generate overview of all weeks
    weeks_overview = []
    
    for week_num in range(1, total_weeks + 1):
        phase = determine_phase(week_num, total_weeks)
        phase_info = get_phase_description(phase, lang)
        
        # Target volume — SAME engine as the detailed week plan so cards match sessions
        target_km = compute_target_km(base_weekly_km, goal, phase)
        
        # Session type keys (frontend translates via i18n trainingPlan.sessionType.*)
        if phase == "build":
            session_types = ["endurance", "endurance", "long_run"] if sessions_per_week <= 3 else ["endurance", "endurance", "fartlek", "long_run"]
        elif phase == "deload":
            session_types = ["recovery", "easy", "short_easy"]
        elif phase == "intensification":
            session_types = ["endurance", "tempo", "intervals", "long_run"]
        elif phase == "taper":
            session_types = ["easy", "speed_reminder", "easy_run"]
        elif phase == "race":
            session_types = ["activation", "race"]
        else:
            session_types = ["endurance", "long_run"]
        
        weeks_overview.append({
            "week": week_num,
            "phase": phase,
            "phase_name": phase_info.get("name", phase),
            "phase_focus": phase_info.get("focus", ""),
            "target_km": target_km,
            "sessions": sessions_per_week if phase not in ["taper", "race"] else min(3, sessions_per_week),
            "session_types": session_types[:sessions_per_week],
            "is_current": week_num == current_week,
            "is_completed": week_num < current_week,
            "intensity_pct": phase_info.get("intensity_pct", 15)
        })
    
    return {
        "goal": goal,
        "goal_description": config["description"],
        "total_weeks": total_weeks,
        "current_week": current_week,
        "start_date": start_date.isoformat() if start_date else None,
        "sessions_per_week": sessions_per_week,
        "base_weekly_km": round(base_weekly_km),
        "weeks": weeks_overview
    }


@api_router.get("/training/week-plan")
async def get_week_plan(user_id: str = "default"):
    """
    Génère un plan d'entraînement détaillé pour la semaine via LLM.
    Utilise le contexte d'entraînement et l'objectif défini.
    """
    # Récupérer l'objectif
    goal = await db.training_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    if not goal:
        raise HTTPException(status_code=400, detail="No goal defined. Use /api/training/set-goal first.")

    # Retrieve recent data for context
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    workouts_7 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)
    
    workouts_28 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(100)
    
    # Calculer les métriques
    km_7 = sum(w.get("distance_km", 0) or 0 for w in workouts_7)
    km_28 = sum(w.get("distance_km", 0) or 0 for w in workouts_28)
    load_7 = km_7 * 10
    load_28 = km_28 * 10
    
    # Construire le contexte
    context = {
        "ctl": load_28 / 4 if load_28 > 0 else 30,
        "atl": load_7 if load_7 > 0 else 35,
        "tsb": (load_28 / 4 - load_7) if load_28 > 0 else -5,
        "acwr": (load_7 / (load_28 / 4)) if load_28 > 0 else 1.0,
        "weekly_km": km_28 / 4 if km_28 > 0 else 20
    }
    
    # Calculer la phase
    start_date = goal["start_date"]
    cycle_weeks = goal["cycle_weeks"]
    
    if isinstance(start_date, datetime) and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    
    if today < start_date:
        current_week = 0
    else:
        delta_days = (today - start_date).days
        current_week = min(delta_days // 7 + 1, cycle_weeks + 1)
    
    phase = determine_phase(current_week, cycle_weeks)
    
    # Calculer la charge cible
    from training_engine import determine_target_load
    target_load = determine_target_load(context, phase)
    
    # Générer le plan via LLM
    plan, success, metadata = await generate_cycle_week(
        context=context,
        phase=phase,
        target_load=target_load,
        goal=goal["goal_type"],
        user_id=user_id
    )
    
    if not success or not plan:
        # Fallback: plan générique basé sur la phase
        plan = _generate_fallback_week_plan(context, phase, target_load, goal["goal_type"])
    
    return {
        "goal": {
            "type": goal["goal_type"],
            "name": goal["event_name"],
            "event_date": goal["event_date"].isoformat() if isinstance(goal["event_date"], datetime) else goal["event_date"]
        },
        "current_week": current_week,
        "total_weeks": cycle_weeks,
        "phase": phase,
        "context": context,
        "plan": plan,
        "generated_by": "llm" if success else "fallback",
        "metadata": metadata
    }


def _generate_fallback_week_plan(context: dict, phase: str, target_load: int, goal: str) -> dict:
    """Génère un plan de secours basé sur des templates."""
    weekly_km = context.get("weekly_km", 30)
    
    # Ajuster selon la phase
    phase_multipliers = {
        "build": 1.0,
        "deload": 0.7,
        "intensification": 1.05,
        "taper": 0.6,
        "race": 0.25
    }
    adjusted_km = weekly_km * phase_multipliers.get(phase, 1.0)
    
    # Allures de référence (à personnaliser selon le profil utilisateur)
    # Format: allure en min:sec/km
    paces = {
        "z1": "6:30-7:00",  # Récupération
        "z2": "5:45-6:15",  # Endurance fondamentale
        "z3": "5:15-5:30",  # Tempo / Allure marathon
        "z4": "4:45-5:00",  # Seuil
        "z5": "4:15-4:30",  # VMA
        "semi": "5:00-5:15", # Allure semi-marathon
        "10k": "4:40-4:55",  # Allure 10K
    }
    
    # FC cibles (à personnaliser selon FC max utilisateur ~185 bpm)
    hr_zones = {
        "z1": "120-135",
        "z2": "135-150", 
        "z3": "150-165",
        "z4": "165-175",
        "z5": "175-185",
    }
    
    # Templates by phase with enriched details
    if phase == "deload":
        sessions = [
            {"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Stretching or yoga", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Tuesday", "type": "Endurance", "duration": "30min", "details": f"5 km • {paces['z1']}/km • HR {hr_zones['z1']} bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": 5},
            {"day": "Wednesday", "type": "Rest", "duration": "0min", "details": "Active recovery • Walk or light swimming", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Thursday", "type": "Endurance", "duration": "35min", "details": f"6 km • {paces['z2']}/km • HR {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": 6},
            {"day": "Friday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Sleep priority", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Saturday", "type": "Endurance", "duration": "40min", "details": f"7 km progressive • {paces['z2']}/km → {paces['z3']}/km • HR {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 35, "distance_km": 7},
            {"day": "Sunday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Prepare for next week", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    elif phase == "taper":
        sessions = [
            {"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Hydration ++", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Tuesday", "type": "Endurance", "duration": "30min", "details": f"5 km + 4×100m fast • {paces['z2']}/km then sprint • HR {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": 5.5},
            {"day": "Wednesday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Mental preparation", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Thursday", "type": "Short tempo", "duration": "25min", "details": f"4 km including 2 km at race pace • {paces['semi']}/km • HR {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": 35, "distance_km": 4},
            {"day": "Friday", "type": "Rest", "duration": "0min", "details": "Total rest • Final gear preparation", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Saturday", "type": "Activation", "duration": "20min", "details": f"3 km + 3×200m race pace • {paces['z2']}/km • HR {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": 3.6},
            {"day": "Sunday", "type": "Rest", "duration": "0min", "details": "RACE EVE • Total rest, carb loading", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    else:  # build, intensification
        sessions = [
            {"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Stretching recommended", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Tuesday", "type": "Endurance", "duration": "50min", "details": f"8 km • {paces['z2']}/km • HR {hr_zones['z2']} bpm • Strict Zone 2", "intensity": "easy", "estimated_tss": 50, "distance_km": 8},
            {"day": "Wednesday", "type": "Threshold", "duration": "40min", "details": f"7 km including 20min at {paces['z4']}/km • HR {hr_zones['z4']} bpm • 2min recovery between blocks", "intensity": "hard", "estimated_tss": 55, "distance_km": 7},
            {"day": "Thursday", "type": "Recovery", "duration": "30min", "details": f"5 km very easy • {paces['z1']}/km • HR <{hr_zones['z1'].split('-')[1]} bpm max", "intensity": "easy", "estimated_tss": 25, "distance_km": 5},
            {"day": "Friday", "type": "Rest", "duration": "0min", "details": "Complete recovery • Cross-training possible (cycling, swimming)", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Saturday", "type": "Tempo", "duration": "45min", "details": f"8 km including 25min at {paces['semi']}/km • HR {hr_zones['z3']} bpm • Half-marathon pace", "intensity": "moderate", "estimated_tss": 60, "distance_km": 8},
            {"day": "Sunday", "type": "Long run", "duration": "70min", "details": f"12 km progressive • {paces['z2']}/km → {paces['z3']}/km • HR {hr_zones['z2']} → {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": 45, "distance_km": 12},
        ]
    
    total_tss = sum(s["estimated_tss"] for s in sessions)
    total_km = sum(s.get("distance_km", 0) for s in sessions)
    
    return {
        "focus": phase,
        "planned_load": target_load,
        "weekly_km": round(total_km, 1),
        "sessions": sessions,
        "total_tss": total_tss,
        "advice": get_phase_description(phase).get("advice", "Keep it up!")
    }


@api_router.get("/subscription/tiers")
async def get_subscription_tiers():
    """Get all available subscription tiers"""
    tiers = []
    for tier_id, config in SUBSCRIPTION_TIERS.items():
        tiers.append(SubscriptionTierInfo(
            id=tier_id,
            name=config["name"],
            price_monthly=config["price_monthly"],
            price_annual=config["price_annual"],
            messages_limit=config["messages_limit"],
            unlimited=config.get("unlimited", False),
            description=config["description"]
        ))
    return tiers


@api_router.get("/subscription/status")
async def get_subscription_status(user_id: str = "default"):
    """Check user's subscription status"""
    
    # Check subscription in DB
    subscription = await db.subscriptions.find_one(
        {"user_id": user_id},
        {"_id": 0}
    )
    
    # Default to free tier
    tier = "free"
    tier_config = SUBSCRIPTION_TIERS["free"]
    is_premium = False
    billing_period = None
    expires_at = None
    subscription_id = None
    
    if subscription and subscription.get("status") == "active":
        expires_at = subscription.get("expires_at")
        
        # Check if subscription is still valid
        if expires_at:
            try:
                exp_date = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_date < datetime.now(timezone.utc):
                    # Subscription expired - revert to free
                    await db.subscriptions.update_one(
                        {"user_id": user_id},
                        {"$set": {"status": "expired"}}
                    )
                else:
                    # Active subscription
                    tier = subscription.get("tier", "starter")
                    tier_config = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS["starter"])
                    is_premium = True
                    billing_period = subscription.get("billing_period", "monthly")
                    subscription_id = subscription.get("subscription_id")
            except (ValueError, TypeError):
                pass

    # Get message count for current month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    message_count = await db.chat_messages.count_documents({
        "user_id": user_id,
        "role": "user",
        "timestamp": {"$gte": month_start.isoformat()}
    })

    messages_limit = tier_config.get("messages_limit", 10)
    is_unlimited = tier_config.get("unlimited", False)
    
    result = SubscriptionStatusResponse(
        tier=tier,
        tier_name=tier_config["name"],
        is_premium=is_premium,
        subscription_id=subscription_id,
        billing_period=billing_period,
        expires_at=expires_at,
        messages_used=message_count,
        messages_limit=messages_limit,
        messages_remaining=max(0, messages_limit - message_count) if not is_unlimited else 999,
        is_unlimited=is_unlimited
    )
    patched = patch_subscription_status_response(result.model_dump(), user_id)
    if patched.get("_demo_mode"):
        return SubscriptionStatusResponse(
            tier=patched["tier"],
            tier_name=patched["tier_name"],
            is_premium=patched["is_premium"],
            subscription_id=result.subscription_id,
            billing_period=result.billing_period,
            expires_at=result.expires_at,
            messages_used=result.messages_used,
            messages_limit=patched["messages_limit"],
            messages_remaining=patched["messages_remaining"],
            is_unlimited=patched["is_unlimited"]
        )
    return result


# Keep old endpoint for backward compatibility
@api_router.get("/premium/status")
async def get_premium_status(user_id: str = "default"):
    """Check if user has active premium subscription (backward compat)"""
    status = await get_subscription_status(user_id)
    return {
        "is_premium": status.is_premium or status.tier != "free",
        "subscription_id": status.subscription_id,
        "expires_at": status.expires_at,
        "messages_used": status.messages_used,
        "messages_remaining": status.messages_remaining,
        "tier": status.tier,
        "tier_name": status.tier_name,
        "messages_limit": status.messages_limit,
        "is_unlimited": status.is_unlimited
    }


@api_router.post("/subscription/checkout", response_model=CreateCheckoutResponse)
async def create_subscription_checkout(request: CreateCheckoutRequest, http_request: Request, user_id: str = "default"):
    """Create Stripe checkout session for subscription"""
    
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    # Validate tier
    if request.tier not in ["starter", "confort", "pro"]:
        raise HTTPException(status_code=400, detail="Invalid subscription tier")
    
    tier_config = SUBSCRIPTION_TIERS[request.tier]
    
    # Get price based on billing period
    if request.billing_period == "annual":
        amount = tier_config["price_annual"]
    else:
        amount = tier_config["price_monthly"]
    
    # Build URLs
    success_url = f"{request.origin_url}/settings?session_id={{CHECKOUT_SESSION_ID}}&subscription=success"
    cancel_url = f"{request.origin_url}/settings?subscription=cancelled"
    
    # Initialize Stripe
    webhook_url = f"{str(http_request.base_url)}api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    # Create checkout session
    checkout_request = CheckoutSessionRequest(
        amount=amount,
        currency="eur",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": user_id,
            "product": f"cardiocoach_{request.tier}",
            "tier": request.tier,
            "billing_period": request.billing_period,
            "type": "subscription"
        }
    )
    
    try:
        session = await stripe_checkout.create_checkout_session(checkout_request)
        
        # Record transaction as pending
        await db.payment_transactions.insert_one({
            "session_id": session.session_id,
            "user_id": user_id,
            "amount": amount,
            "currency": "eur",
            "tier": request.tier,
            "billing_period": request.billing_period,
            "status": "pending",
            "product": f"cardiocoach_{request.tier}",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Checkout session created for user {user_id}: {request.tier} ({request.billing_period})")
        
        return CreateCheckoutResponse(
            checkout_url=session.url,
            session_id=session.session_id
        )
    
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create checkout: {str(e)}")


# Keep old endpoint for backward compatibility
@api_router.post("/premium/checkout", response_model=CreateCheckoutResponse)
async def create_premium_checkout_compat(request: CreateCheckoutRequest, http_request: Request, user_id: str = "default"):
    """Create Stripe checkout session (backward compat)"""
    # Convert old request to new format - default to starter monthly
    new_request = CreateCheckoutRequest(
        origin_url=request.origin_url,
        tier=getattr(request, 'tier', 'starter'),
        billing_period=getattr(request, 'billing_period', 'monthly')
    )
    return await create_subscription_checkout(new_request, http_request, user_id)


@api_router.get("/subscription/checkout/status/{session_id}")
async def check_subscription_status(session_id: str, http_request: Request, user_id: str = "default"):
    """Check status of a checkout session and activate subscription if paid"""
    
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    # Check if already processed
    existing = await db.payment_transactions.find_one({"session_id": session_id})
    if existing and existing.get("status") == "completed":
        return {"status": "completed", "message": "Already processed"}
    
    # Initialize Stripe
    webhook_url = f"{str(http_request.base_url)}api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    try:
        status = await stripe_checkout.get_checkout_status(session_id)
        
        if status.payment_status == "paid":
            # Get tier and billing from transaction
            transaction = await db.payment_transactions.find_one({"session_id": session_id})
            actual_user_id = transaction.get("user_id", user_id) if transaction else user_id
            tier = transaction.get("tier", "starter") if transaction else "starter"
            billing_period = transaction.get("billing_period", "monthly") if transaction else "monthly"
            
            # Update transaction
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {
                    "status": "completed",
                    "payment_status": status.payment_status,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            # Calculate expiration (30 days for monthly, 365 for annual)
            days = 365 if billing_period == "annual" else 30
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            
            # Create/update subscription
            await db.subscriptions.update_one(
                {"user_id": actual_user_id},
                {"$set": {
                    "user_id": actual_user_id,
                    "subscription_id": session_id,
                    "tier": tier,
                    "billing_period": billing_period,
                    "status": "active",
                    "amount": transaction.get("amount") if transaction else 0,
                    "currency": "eur",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": expires_at
                }},
                upsert=True
            )
            
            tier_name = SUBSCRIPTION_TIERS.get(tier, {}).get("name", "Starter")
            logger.info(f"Subscription activated for user {actual_user_id}: {tier} ({billing_period})")
            
            return {
                "status": "completed",
                "payment_status": status.payment_status,
                "tier": tier,
                "message": f"Abonnement {tier_name} activé ! Bienvenue dans CardioCoach."
            }
        
        elif status.payment_status == "unpaid":
            return {"status": "pending", "payment_status": status.payment_status}
        
        else:
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {"status": status.payment_status}}
            )
            return {"status": status.status, "payment_status": status.payment_status}
    
    except Exception as e:
        logger.error(f"Checkout status error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check status: {str(e)}")


# Backward compat endpoint
@api_router.get("/premium/checkout/status/{session_id}")
async def check_checkout_status_compat(session_id: str, http_request: Request, user_id: str = "default"):
    """Check checkout status (backward compat)"""
    return await check_subscription_status(session_id, http_request, user_id)


@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks"""
    
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    body = await request.body()
    signature = request.headers.get("Stripe-Signature")
    
    webhook_url = f"{str(request.base_url)}api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    try:
        webhook_response = await stripe_checkout.handle_webhook(body, signature)
        
        logger.info(f"Stripe webhook: {webhook_response.event_type} - {webhook_response.session_id}")
        
        if webhook_response.payment_status == "paid":
            # Activate premium (same logic as checkout status)
            user_id = webhook_response.metadata.get("user_id", "default")
            
            await db.payment_transactions.update_one(
                {"session_id": webhook_response.session_id},
                {"$set": {
                    "status": "completed",
                    "payment_status": "paid",
                    "webhook_event": webhook_response.event_type,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            await db.subscriptions.update_one(
                {"user_id": user_id},
                {"$set": {
                    "status": "active",
                    "expires_at": expires_at
                }},
                upsert=True
            )
        
        return {"received": True}
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")


# ========== CHAT COACH (PREMIUM ONLY) ==========

def build_chat_context(workouts: list, user_goal: dict = None) -> dict:
    """
    Construit le contexte utilisateur pour le chat coach (LLM ou templates).
    # LLM serveur uniquement – pas d'exécution client-side
    """
    from datetime import timedelta
    
    context = {
        "km_semaine": 0,
        "nb_seances": 0,
        "allure": "N/A",
        "cadence": 0,
        "zones": {},
        "ratio": 1.0,
        "recent_workouts": [],
        "rag_tips": [],
    }
    
    if not workouts:
        return context
    
    # Filtrer les workouts de la semaine
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    
    week_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00")).date()
            if w_date >= week_start:
                week_workouts.append(w)
        except (ValueError, TypeError, AttributeError):
            pass
    
    # Stats de la semaine
    context["km_semaine"] = round(sum(w.get("distance_km", 0) for w in week_workouts), 1)
    context["nb_seances"] = len(week_workouts)
    
    # Allure moyenne
    total_time = sum(w.get("duration_minutes", 0) for w in week_workouts)
    total_km = context["km_semaine"]
    if total_km > 0 and total_time > 0:
        pace_min = total_time / total_km
        context["allure"] = f"{int(pace_min)}:{int((pace_min % 1) * 60):02d}"
    
    # Cadence moyenne
    cadences = [w.get("average_cadence", 0) for w in week_workouts if w.get("average_cadence")]
    if cadences:
        context["cadence"] = round(sum(cadences) / len(cadences))
    
    # Zones moyennes
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    for w in week_workouts:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z, pct in zones.items():
                if z in zone_totals:
                    zone_totals[z] += pct
            zone_count += 1
    
    if zone_count > 0:
        context["zones"] = {z: round(v / zone_count) for z, v in zone_totals.items()}
    
    # Ratio charge (simplifié)
    prev_week_km = sum(
        w.get("distance_km", 0) for w in workouts
        if (datetime.fromisoformat(w.get("date", "2000-01-01").replace("Z", "+00:00")).date() 
            >= week_start - timedelta(days=7))
        and (datetime.fromisoformat(w.get("date", "2000-01-01").replace("Z", "+00:00")).date() 
             < week_start)
    )
    if prev_week_km > 0:
        context["ratio"] = round(context["km_semaine"] / prev_week_km, 2)
    
    # Workouts récents (5 derniers)
    context["recent_workouts"] = [
        {
            "name": w.get("name", "Run"),
            "distance_km": w.get("distance_km", 0),
            "duration_min": w.get("duration_minutes", 0),
            "date": w.get("date", ""),
        }
        for w in workouts[:5]
    ]
    
    # Goal
    if user_goal:
        context["objectif_nom"] = user_goal.get("race_name", "")
        context["jours_course"] = user_goal.get("days_until", None)
    
    return context

@api_router.post("/chat/send", response_model=ChatResponse)
async def send_chat_message(request: ChatRequest):
    """Send a message to the chat coach (with tier-based limits)"""
    
    user_id = request.user_id
    
    # Get subscription status
    subscription = await db.subscriptions.find_one(
        {"user_id": user_id},
        {"_id": 0}
    )
    
    # Determine tier and limits
    tier = "free"
    tier_config = SUBSCRIPTION_TIERS["free"]
    
    if subscription and subscription.get("status") == "active":
        # Check expiration
        expires_at = subscription.get("expires_at")
        if expires_at:
            try:
                exp_date = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_date >= datetime.now(timezone.utc):
                    tier = subscription.get("tier", "starter")
                    tier_config = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS["starter"])
            except (ValueError, TypeError):
                pass

    messages_limit = tier_config.get("messages_limit", 10)
    is_unlimited = tier_config.get("unlimited", False)

    # Get message count for current month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    message_count = await db.chat_messages.count_documents({
        "user_id": user_id,
        "role": "user",
        "timestamp": {"$gte": month_start.isoformat()}
    })
    
    # Check limit (soft limit for unlimited tier)
    if message_count >= messages_limit:
        if is_unlimited and message_count < 200:  # Hard cap for fair-use
            pass  # Allow but warn
        else:
            tier_name = tier_config.get("name", "Free")
            raise HTTPException(
                status_code=429,
                detail=f"You've reached your limit of {messages_limit} messages this month ({tier_name}). Upgrade to the next tier to continue!"
            )
    
    # Get user's recent workouts for context
    workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(50)
    
    # Get user goal
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    # Generate response using local chat engine (NO LLM) - fallback mode
    # Note: If client uses WebLLM, it sends use_local_llm=True and we just store the message
    # Server-side LLM only – no client-side execution
    response_text = ""
    suggestions = []
    category = ""
    used_llm = False
    llm_metadata = {}
    
    if request.use_local_llm:
        # Client is using WebLLM, we just need to store messages and track count
        response_text = ""  # Client will generate this
    else:
        # Construire le contexte pour le LLM/RAG
        language = (request.language or "en").lower()
        if language not in ("en", "fr"):
            language = "en"
        context = build_chat_context(workouts, user_goal)
        context["language"] = language
        
        # Récupérer l'historique de conversation récent
        recent_messages = await db.chat_messages.find(
            {"user_id": user_id},
            {"_id": 0, "role": 1, "content": 1}
        ).sort("timestamp", -1).limit(8).to_list(8)
        recent_messages.reverse()  # Ordre chronologique
        
        # Cascade LLM → Templates via coach_service
        response_text, used_llm, llm_metadata = await coach_chat_response(
            message=request.message,
            context=context,
            history=recent_messages,
            user_id=user_id,
            workouts=workouts,
            user_goal=user_goal
        )
        
        if isinstance(llm_metadata, dict):
            suggestions = llm_metadata.get("suggestions", [])
        
        # Fallback suggestions in user language if LLM gave none
        if used_llm and not suggestions:
            allure = context.get("allure", "6:00")
            if language == "fr":
                suggestions = [
                    "Comment équilibrer mes zones d'entraînement ?",
                    f"Comment améliorer mon allure de {allure}/km ?",
                    "Quels exercices de renforcement faire ?",
                    "Comment travailler plus en endurance fondamentale ?",
                ]
            else:
                suggestions = [
                    "How do I balance my training zones?",
                    f"How can I improve my {allure}/km pace?",
                    "What strength exercises should I do?",
                    "How to train more in base endurance?",
                ]
    
    # Store user message
    user_msg_id = str(uuid.uuid4())
    await db.chat_messages.insert_one({
        "id": user_msg_id,
        "user_id": user_id,
        "role": "user",
        "content": request.message,
        "timestamp": now.isoformat()
    })
    
    # Store assistant response only if generated server-side
    assistant_msg_id = str(uuid.uuid4())
    if response_text:
        await db.chat_messages.insert_one({
            "id": assistant_msg_id,
            "user_id": user_id,
            "role": "assistant",
            "content": response_text,
            "suggestions": suggestions,  # Store suggestions too
            "timestamp": now.isoformat()
        })
    
    messages_remaining = max(0, messages_limit - message_count - 1) if not is_unlimited else 999
    
    source = f"Emergent LLM ({LLM_MODEL})" if used_llm else "Templates Python"
    duration_info = f" en {llm_metadata.get('duration_sec', 0)}s" if used_llm else ""
    logger.info(f"Chat message processed for user {user_id} (tier={tier}, source={source}{duration_info}). Remaining: {messages_remaining}")
    
    return ChatResponse(
        response=response_text,
        message_id=assistant_msg_id,
        messages_remaining=messages_remaining,
        messages_limit=messages_limit,
        is_unlimited=is_unlimited,
        suggestions=suggestions,
        category=category
    )


@api_router.post("/chat/store-response")
async def store_chat_response(user_id: str, message_id: str, response: str):
    """Store a response generated by client-side WebLLM"""
    await db.chat_messages.insert_one({
        "id": message_id,
        "user_id": user_id,
        "role": "assistant",
        "content": response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "webllm"
    })
    return {"success": True}


@api_router.get("/chat/history")
async def get_chat_history(user_id: str = "default", limit: int = 50):
    """Get chat history for a user"""
    
    messages = await db.chat_messages.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    # Reverse to chronological order
    messages.reverse()
    
    return messages


@api_router.delete("/chat/history")
async def clear_chat_history(user_id: str = "default"):
    """Clear chat history for a user"""
    
    result = await db.chat_messages.delete_many({"user_id": user_id})
    
    logger.info(f"Chat history cleared for user {user_id}: {result.deleted_count} messages")
    
    return {"success": True, "deleted_count": result.deleted_count}


@api_router.get("/cache/stats")
async def get_coach_cache_stats():
    """Get coach service cache statistics"""
    return get_cache_stats()


@api_router.delete("/cache/clear")
async def clear_coach_cache():
    """Clear all coach service caches"""
    result = clear_cache()
    logger.info(f"Cache cleared: {result}")
    return {"success": True, **result}


@api_router.get("/metrics")
async def get_service_metrics():
    """Get coach service metrics (LLM success rate, latency, etc.)"""
    return {
        "coach": get_coach_metrics(),
        "cache": get_cache_stats()
    }


@api_router.delete("/metrics/reset")
async def reset_service_metrics():
    """Reset coach service metrics"""
    old_metrics = reset_coach_metrics()
    logger.info(f"Metrics reset. Previous: {old_metrics}")
    return {"success": True, "previous": old_metrics}


# ========== SUBSCRIPTION SYSTEM (Early Adopter) ==========

class SubscriptionInfo(BaseModel):
    """Informations d'abonnement utilisateur"""
    user_id: str
    status: str  # trial, free, early_adopter, premium
    display: Dict
    features: Dict
    trial_days_remaining: Optional[int] = None
    price_locked: Optional[float] = None
    stripe_customer_id: Optional[str] = None


class ActivateSubscriptionRequest(BaseModel):
    """Requête pour activer un abonnement"""
    user_id: str = "default"
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None


@api_router.get("/subscription/info")
async def get_subscription_info(user_id: str = "default", language: str = "en"):
    """
    Retrieves complete subscription information for a user.
    
    Returns:
    - status: trial, free, early_adopter, premium
    - display: Localized UI texts
    - features: Accessible features
    - trial_days_remaining: Remaining days if in trial
    """
    subscription = await get_demo_subscription(db, user_id)
    status = subscription.get("status", SubscriptionStatus.FREE)
    
    return {
        "user_id": user_id,
        "status": status,
        "display": get_subscription_display(subscription, language),
        "features": FEATURES.get(status, FEATURES[SubscriptionStatus.FREE]),
        "trial_days_remaining": get_trial_days_remaining(subscription),
        "price_locked": subscription.get("price_locked"),
        "stripe_customer_id": subscription.get("stripe_customer_id"),
        "created_at": subscription.get("created_at"),
        "activated_at": subscription.get("activated_at")
    }


@api_router.post("/subscription/activate-early-adopter")
async def activate_early_adopter_subscription(request: ActivateSubscriptionRequest):
    """
    Active l'abonnement Early Adopter pour un utilisateur.
    Prix garanti à vie: 4.99€/mois
    
    Appelé après un paiement Stripe réussi.
    """
    subscription = await activate_early_adopter(
        db,
        request.user_id,
        request.stripe_customer_id or f"cus_simulated_{request.user_id}",
        request.stripe_subscription_id or f"sub_simulated_{request.user_id}"
    )
    
    return {
        "success": True,
        "status": subscription.get("status"),
        "message": "Abonnement Early Adopter activé ! Prix garanti à vie: 4.99€/mois",
        "subscription": subscription
    }


@api_router.post("/subscription/cancel")
async def cancel_user_subscription(user_id: str = "default"):
    """
    Annule l'abonnement d'un utilisateur.
    Le statut passe à 'free'.
    """
    subscription = await cancel_subscription(db, user_id)
    
    return {
        "success": True,
        "status": subscription.get("status"),
        "message": "Abonnement annulé"
    }


@api_router.post("/subscription/simulate-trial-end")
async def simulate_trial_end(user_id: str = "default"):
    """
    [DEV ONLY] Simulate end of free trial to test paywall.
    """
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "trial_end": datetime.now(timezone.utc).isoformat(),
                "status": SubscriptionStatus.FREE
            }
        }
    )

    return {
        "success": True,
        "message": "Trial ended, user set to FREE"
    }


@api_router.post("/subscription/reset-to-trial")
async def reset_to_trial(user_id: str = "default"):
    """
    [DEV ONLY] Reset user to 7-day free trial.
    """
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=7)

    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.TRIAL,
                "trial_start": now.isoformat(),
                "trial_end": trial_end.isoformat(),
                "updated_at": now.isoformat()
            }
        },
        upsert=True
    )

    return {
        "success": True,
        "message": f"Free trial reactivated until {trial_end.isoformat()}"
    }


@api_router.get("/subscription/early-adopter-offer")
async def get_early_adopter_offer(language: str = "en"):
    """
    Returns details of the Early Adopter offer.
    """
    if language == "fr":
        return {
            "title": "Active ton coach running",
            "subtitle": "Ton plan d'entraînement personnalisé est prêt",
            "description": "Active ton abonnement pour y accéder.",
            "offer_name": "Early Adopter",
            "price": EARLY_ADOPTER_PRICE,
            "price_display": f"{EARLY_ADOPTER_PRICE:.2f} € / mois",
            "price_guarantee": "Prix garanti à vie",
            "features": [
                "Plan d'entraînement personnalisé",
                "Adaptation automatique du plan",
                "Analyse intelligente des séances",
                "Coach IA conversationnel",
                "Synchronisation montres/apps",
                "Prédictions de course"
            ],
            "cta_button": "Activer mon coach",
            "trial_cta": "Profite de ton essai gratuit"
        }
    elif language == "es":
        return {
            "title": "Activa tu coach de running",
            "subtitle": "Tu plan personalizado está listo",
            "description": "Activa tu suscripción para acceder.",
            "offer_name": "Early Adopter",
            "price": EARLY_ADOPTER_PRICE,
            "price_display": f"{EARLY_ADOPTER_PRICE:.2f} € / mes",
            "price_guarantee": "Precio garantizado de por vida",
            "features": [
                "Plan de entrenamiento personalizado",
                "Adaptación automática del plan",
                "Análisis inteligente de sesiones",
                "Coach IA conversacional",
                "Sincronización relojes/apps",
                "Predicciones de carrera"
            ],
            "cta_button": "Activar mi coach",
            "trial_cta": "Disfruta tu prueba gratuita"
        }
    else:
        return {
            "title": "Activate your running coach",
            "subtitle": "Your personalized training plan is ready",
            "description": "Activate your subscription to access it.",
            "offer_name": "Early Adopter",
            "price": EARLY_ADOPTER_PRICE,
            "price_display": f"€{EARLY_ADOPTER_PRICE:.2f} / month",
            "price_guarantee": "Price guaranteed for life",
            "features": [
                "Personalized training plan",
                "Automatic plan adaptation",
                "Smart session analysis",
                "AI conversational coach",
                "Watch/app synchronization",
                "Race predictions"
            ],
            "cta_button": "Activate my coach",
            "trial_cta": "Enjoy your free trial"
        }


@api_router.post("/subscription/early-adopter/checkout")
async def create_early_adopter_checkout(http_request: Request, user_id: str = "default", origin_url: str = None):
    """
    Create a Stripe Checkout session for the Early Adopter offer.
    Price: 4.99€/month, guaranteed for life.
    """
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    # Determine origin URL
    if not origin_url:
        origin_url = str(http_request.base_url).rstrip('/')
        # In preview, use frontend URL
        if "preview.emergentagent.com" in origin_url:
            origin_url = origin_url.replace("/api", "").rstrip('/')

    # Redirect URLs
    success_url = f"{origin_url}/settings?session_id={{CHECKOUT_SESSION_ID}}&subscription=early_adopter_success"
    cancel_url = f"{origin_url}/settings?subscription=cancelled"

    # Webhook URL
    webhook_url = f"{str(http_request.base_url).rstrip('/')}/api/webhook/stripe/early-adopter"

    # Initialize Stripe
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)

    # Create checkout session
    checkout_request = CheckoutSessionRequest(
        amount=float(EARLY_ADOPTER_PRICE),  # In euros (float format required by Stripe Emergent)
        currency="eur",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": user_id,
            "product": "cardiocoach_early_adopter",
            "price_locked": str(EARLY_ADOPTER_PRICE),
            "type": "subscription",
            "plan": "early_adopter"
        }
    )
    
    try:
        session = await stripe_checkout.create_checkout_session(checkout_request)
        
        # Enregistrer la transaction en attente
        await db.payment_transactions.insert_one({
            "session_id": session.session_id,
            "user_id": user_id,
            "amount": EARLY_ADOPTER_PRICE,
            "currency": "eur",
            "plan": "early_adopter",
            "status": "pending",
            "product": "cardiocoach_early_adopter",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Early Adopter checkout session created for user {user_id}: {session.session_id}")
        
        return {
            "checkout_url": session.url,
            "session_id": session.session_id
        }
    
    except Exception as e:
        logger.error(f"Early Adopter Stripe checkout error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create checkout: {str(e)}")


@api_router.post("/webhook/stripe/early-adopter")
async def stripe_early_adopter_webhook(request: Request):
    """
    Webhook Stripe pour les paiements Early Adopter.
    Active l'abonnement une fois le paiement confirmé.
    """
    try:
        payload = await request.body()
        event = json.loads(payload)
        
        event_type = event.get("type", "")
        logger.info(f"Early Adopter webhook received: {event_type}")
        
        if event_type == "checkout.session.completed":
            session = event.get("data", {}).get("object", {})
            metadata = session.get("metadata", {})
            
            user_id = metadata.get("user_id", "default")
            session_id = session.get("id")
            customer_id = session.get("customer")
            subscription_id = session.get("subscription")
            
            # Activer l'abonnement Early Adopter
            await activate_early_adopter(
                db,
                user_id,
                customer_id or f"cus_{session_id}",
                subscription_id or f"sub_{session_id}"
            )
            
            # Mettre à jour la transaction
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "status": "completed",
                        "stripe_customer_id": customer_id,
                        "stripe_subscription_id": subscription_id,
                        "completed_at": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
            
            logger.info(f"Early Adopter activated for user {user_id}")
        
        return {"received": True}
    
    except Exception as e:
        logger.error(f"Early Adopter webhook error: {e}")
        return {"received": True, "error": str(e)}


@api_router.get("/subscription/verify-checkout/{session_id}")
async def verify_checkout_session(session_id: str, user_id: str = "default"):
    """
    Vérifie le statut d'une session checkout et active l'abonnement si payé.
    Appelé par le frontend après retour de Stripe.
    """
    try:
        # Vérifier la transaction
        transaction = await db.payment_transactions.find_one({"session_id": session_id})
        
        if not transaction:
            return {"success": False, "error": "Session not found"}
        
        if transaction.get("status") == "completed":
            # Déjà traité
            subscription = await get_user_subscription(db, user_id)
            return {
                "success": True,
                "status": subscription.get("status"),
                "already_processed": True
            }
        
        # Pour les tests, activer directement si la session existe
        # En production, cela serait vérifié via l'API Stripe
        if transaction.get("plan") == "early_adopter":
            await activate_early_adopter(
                db,
                user_id,
                f"cus_{session_id}",
                f"sub_{session_id}"
            )
            
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}}
            )
            
            return {
                "success": True,
                "status": "early_adopter",
                "message": "Abonnement Early Adopter activé !"
            }
        
        return {"success": False, "error": "Unknown plan"}
    
    except Exception as e:
        logger.error(f"Verify checkout error: {e}")
        return {"success": False, "error": str(e)}


# Register Garmin connector endpoints under /api (/api/garmin/*)
from api.garmin import garmin_router
api_router.include_router(garmin_router)

# Include the router
app.include_router(api_router)

# Include the physiological engine dashboard router
app.include_router(dashboard_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def create_db_indexes():
    """Create MongoDB indexes for common query patterns"""
    # Expose db via app.state so sub-routers can access it via request.app.state.db
    app.state.db = db
    # Ensure the gccli Garmin connector is installed + logged in (best-effort,
    # survives fresh deploys; never blocks startup on failure).
    try:
        from garmin.bootstrap import bootstrap as garmin_bootstrap
        garmin_bootstrap()
    except MissingSecretError:
        # Fail-fast: gccli must authenticate but a required secret is missing.
        raise
    except Exception as e:
        logger.warning(f"gccli bootstrap skipped: {e}")
    try:
        # Workouts: filter + sort by user and date
        await db.workouts.create_index([("user_id", 1), ("date", -1)])
        await db.workouts.create_index([("id", 1)], sparse=True)
        # Conversations / chat messages
        await db.conversations.create_index([("user_id", 1), ("timestamp", 1)])
        await db.chat_messages.create_index([("user_id", 1), ("timestamp", 1)])
        # OAuth state store: auto-expire after TTL (expires_at stored as datetime)
        await db.oauth_states.create_index("state", unique=True)
        await db.oauth_states.create_index("expires_at", expireAfterSeconds=0)
        # Subscriptions / tokens
        await db.subscriptions.create_index("user_id", sparse=True)
        # Terra integration collections
        await db.terra_tokens.create_index("user_id", sparse=True)
        await db.daily_metrics.create_index([("user_id", 1), ("date", -1)])
        await db.baselines.create_index("user_id", sparse=True)
        await db.training_load.create_index([("user_id", 1), ("date", -1)])
        await db.recovery_scores.create_index([("user_id", 1), ("date", -1)])
        await db.run_index_scores.create_index([("user_id", 1), ("date", -1)])
        await db.workout_recommendations.create_index([("user_id", 1), ("date", -1)])
        # Garmin connector collections
        await db.garmin_connections.create_index("user_id", unique=True, sparse=True)
        await db.garmin_activities.create_index([("user_id", 1), ("external_id", 1)], unique=True, sparse=True)
        await db.garmin_activities.create_index([("user_id", 1), ("start_time", -1)])
        await db.garmin_daily_metrics.create_index([("user_id", 1), ("date", -1)], unique=True, sparse=True)
        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Could not create some MongoDB indexes: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

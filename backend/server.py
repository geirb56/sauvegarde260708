from services.run_index_history import get_run_index_history_payload, upsert_run_index_snapshot
from fastapi import FastAPI, APIRouter, HTTPException, Query, Request, Depends, Header
from fastapi.responses import RedirectResponse, JSONResponse
from middleware import SSEAwareGZipMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Auth module — JWT-based multi-user identity
from auth.router import auth_router
from auth.oauth_router import oauth_router
from auth.dependencies import get_current_user, require_admin
from admin.router import admin_router
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
from llm_coach import LLM_MODEL

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
from training_v2.training_load import build_training_load
from training_v2.training_history import build_training_history
from training_v2.runner_profile import build_runner_profile
from training_v2.training_state import build_training_state
from training_v2.readiness_decision import (
    ReadinessBand,
    ReadinessDecision,
    build_readiness_decision,
)
from training_v2.daily_adaptation import (
    DailyAdaptationAction,
    DailyAdaptationResult,
    build_daily_adaptation,
)
from training_v2.training_response import build_recent_training_response
from training_v2.workout_generator import WorkoutPrescription
from training_v2.training_week_response import TrainingWeekV2Response  # PR167
from training_v2.daily_runtime_helpers import (
    BAND_TO_RECOMMENDATION,
    runtime_session_to_prescription,
    prescription_to_runtime_session,
)
from garmin.readiness_adapter import build_readiness_v2_from_garmin_data
from garmin.domain_adapter import mongo_garmin_activities_to_domain
from training_engine import (
    DEFAULT_WEEKLY_KM,
    compute_current_weekly_km,
    compute_cycle_dates,
    compute_target_km,
    apply_resume_guard,
    resolve_chronic_base,
    resolve_reprise_plan,
    REPRISE_STABLE_WEEKS,
    compute_week_number,
    determine_phase,
    get_phase_description,
    is_running,
    normalized_distance_km,
)

from config.training_goals import GOAL_CONFIG  # noqa: E402  # PR145: single source

# Import subscription manager
from subscription_manager import (
    get_user_subscription,
    cancel_subscription,
    get_trial_days_remaining,
    is_route_protected,
    get_subscription_display,
    SubscriptionStatus,
    FEATURES,
    TRIAL_DURATION_DAYS
)

from demo_mode import (
    get_demo_subscription,
    is_subscription_active,
    patch_subscription_status_response,
    validate_demo_mode_safety,
    validate_environment_configuration,
    log_demo_mode_status,
)
from access_control import (
    get_user_access,
    get_route_access,
    Tier,
    RouteAccess,
    CHAT_QUOTA_FREE,
    CHAT_ANTIABUSE_CAP,
)
from services.paddle_webhook_security import verify_and_parse_paddle_event, PaddleWebhookError

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

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").strip().lower()

# ── Paddle configuration (new payment provider) ───────────────────────────────
# PADDLE_API_KEY:        Paddle seller/API key (server-side only)
# PADDLE_WEBHOOK_SECRET: Webhook notification secret from Paddle dashboard
# PADDLE_ENVIRONMENT:    "sandbox" | "production"
# PADDLE_PRICE_ID:       Price ID for Premium 4.99 EUR/month
# PADDLE_CLIENT_TOKEN:   Paddle.js client-side token (safe to expose to browser)
PADDLE_API_KEY        = os.environ.get("PADDLE_API_KEY", "")
PADDLE_WEBHOOK_SECRET = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
PADDLE_ENVIRONMENT    = os.environ.get("PADDLE_ENVIRONMENT", "sandbox").strip().lower()
PADDLE_PRICE_ID       = os.environ.get("PADDLE_PRICE_ID", "")
PADDLE_CLIENT_TOKEN   = os.environ.get("PADDLE_CLIENT_TOKEN", "")

# Paddle API base URLs
_PADDLE_API_BASES = {
    "sandbox":    "https://sandbox-api.paddle.com",
    "production": "https://api.paddle.com",
}
PADDLE_API_BASE = _PADDLE_API_BASES.get(PADDLE_ENVIRONMENT, _PADDLE_API_BASES["sandbox"])

# Subscription tiers configuration
SUBSCRIPTION_TIERS = {
    "free": {
        "name": "Free",
        "price_monthly": 0,
        "price_annual": 0,
        "messages_limit": 10,
        "description": "Discovery"
    },
    "premium": {
        "name": "Premium",
        "price_monthly": 4.99,
        "price_annual": 49.99,
        "messages_limit": 25,
        "description": "Full access"
    }
}



FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')


def _compute_cors_origins() -> List[str]:
    """
    CORS policy:
    - production: strictly FRONTEND_URL only
    - development: localhost defaults (+ optional CORS_ORIGINS and FRONTEND_URL)
    """
    if ENVIRONMENT == "production":
        return [FRONTEND_URL.rstrip("/")]

    origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        FRONTEND_URL.rstrip("/"),
    }
    extra = os.environ.get("CORS_ORIGINS", "")
    if extra:
        origins.update(origin.strip().rstrip("/") for origin in extra.split(",") if origin.strip())
    return sorted(origins)

# Create the main app
app = FastAPI()

# GZip compression for responses > 1KB — SSE (text/event-stream) is exempt.
app.add_middleware(SSEAwareGZipMiddleware, minimum_size=1000)

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
    """Extract user_id from request.

    Resolution order (Step 2: JWT-only for client identity):
    1. JWT ****** — Authorization: ****** (sub claim)
    2. IP address        — last-resort fallback
    """
    # 1. Try JWT ****** first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        try:
            from auth.jwt_utils import decode_access_token
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if user_id:
                return user_id
        except Exception:
            pass  # Fall through to next resolution method

    # 2. Fallback to IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ========== AUTH DEPENDENCY ==========

security = HTTPBearer(auto_error=False)

async def auth_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Authentication dependency.

    Validates a JWT token produced by /api/auth/login or /api/auth/register.
    Raises 401 if no valid JWT is present (Step 2: legacy fallbacks removed).

    Returns dict with at least {"id": "<user_id>", "authenticated": True}.
    """
    import jwt as _jwt
    from auth.jwt_utils import decode_access_token

    _raise_401 = HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials or not credentials.credentials:
        raise _raise_401

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise _raise_401
    except _jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except _jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"id": user_id, "authenticated": True}


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

    Uses access_control.get_route_access() for route classification and
    access_control.get_user_access() for per-user tier resolution.

    - PUBLIC routes: pass through (no auth required).
    - FREE routes: pass through (any authenticated user).
    - PREMIUM routes: require TRIAL or PREMIUM tier; fail-closed on errors.
    """
    path = request.url.path

    # Skip non-API requests
    if not path.startswith("/api"):
        return await call_next(request)

    # Classify the route
    route_access = get_route_access(path)

    # Public and free-tier routes need no subscription check
    if route_access != RouteAccess.PREMIUM:
        return await call_next(request)

    # Premium route — verify user's subscription tier
    user_id = get_user_id_from_request(request)

    try:
        user_access = await get_user_access(db, user_id)

        if not user_access.has_premium_access:
            logger.info(f"[Subscription] Blocked {path} for FREE user '{user_id}'")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "subscription_required",
                    "message": "Subscription required to access this feature",
                    "message_en": "Subscription required to access this feature",
                    "status": user_access.tier.value,
                    "upgrade_url": "/subscription",
                },
            )

        # Store resolved access in request state for downstream handlers
        request.state.user_access = user_access

    except Exception as e:
        logger.error(f"[Subscription] Error checking subscription for '{user_id}': {e}")
        # Fail-closed: if we cannot verify access, deny premium routes
        return JSONResponse(
            status_code=403,
            content={
                "error": "subscription_check_failed",
                "message": "Could not verify subscription status. Please try again.",
            },
        )

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


class CoachResponse(BaseModel):
    response: str
    message_id: str


class GuidanceRequest(BaseModel):
    language: Optional[str] = "en"


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
    return {"message": "RunIndex API"}


@api_router.get("/workouts", response_model=List[dict])
async def get_workouts(user: dict = Depends(auth_user)):
    """Get all workouts for a user, sorted by date descending"""
    user_id = user["id"]
    workouts = await db.workouts.find(
        {"user_id": user_id}, 
        {"_id": 0}
    ).sort("date", -1).to_list(200)
    return workouts


@api_router.get("/workouts/{workout_id}")
async def get_workout(workout_id: str, user: dict = Depends(auth_user)):
    """Get a specific workout by ID"""
    user_id = user["id"]
    workout = await db.workouts.find_one(
        {"id": workout_id, "user_id": user_id}, 
        {"_id": 0}
    )
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    return workout


@api_router.post("/workouts", response_model=Workout)
async def create_workout(workout: WorkoutCreate, user: dict = Depends(auth_user)):
    """Create a new workout"""
    user_id = user["id"]
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
async def get_vma_estimate(user: dict = Depends(auth_user), language: str = "en"):
    """Estimate VMA and VO2max from user data"""
    
    user_id = user["id"]
    # Check if user has a goal (race performance to use)
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    # Get all running workouts (scoped to authenticated user)
    all_workouts = await db.workouts.find(
        {"type": "run", "user_id": user_id},
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
async def get_user_goal(user: dict = Depends(auth_user)):
    """Get user's current goal"""
    user_id = user["id"]
    goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    return goal


@api_router.post("/user/goal")
async def set_user_goal(goal: UserGoalCreate, user: dict = Depends(auth_user)):
    """Set user's goal (event with date, distance, target time)"""
    user_id = user["id"]
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
async def delete_user_goal(user: dict = Depends(auth_user)):
    """Delete user's goal"""
    user_id = user["id"]
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
async def get_dashboard_insight(language: str = "en", user: dict = Depends(auth_user)):
    """Get dashboard coach insight with week and month summaries and recovery score - NO LLM"""
    
    user_id = user["id"]
    # Check cache first
    cache_key = f"{user_id}_{language}"
    now = datetime.now(timezone.utc).timestamp()
    
    if cache_key in _dashboard_cache:
        cached_data, cached_time = _dashboard_cache[cache_key]
        if now - cached_time < DASHBOARD_CACHE_TTL:
            logger.info(f"Dashboard insight cache hit for {cache_key}")
            return cached_data
    
    # Get workouts (user-scoped)
    all_workouts = await db.workouts.find({
        "user_id": user_id
    }, {"_id": 0}).sort("date", -1).to_list(200)
    # Calculate stats
    week_stats = calculate_week_stats(all_workouts)
    month_stats = calculate_month_stats(all_workouts)
    
    # Calculate recovery score
    recovery_score = calculate_recovery_score(all_workouts, language)
    run_index = calculate_run_index(all_workouts)

    await upsert_run_index_snapshot(db, user_id, all_workouts)
    
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
async def get_stats(user: dict = Depends(auth_user)):
    """Get training statistics with proper 7-day and 30-day calculations"""
    from datetime import datetime, timedelta
    from collections import defaultdict
    user_id = user["id"]
    
    # Get all workouts
    workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    
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
async def analyze_with_coach(request: CoachRequest, user: dict = Depends(auth_user)):
    """Conversational Chat Coach with GPT-4o-mini

    The coach has access to:
    - Conversation history
    - Training data (workouts, stats)
    - Fitness context (ACWR, TSB, volume)

    It can respond to open-ended questions about training.
    """
    from llm_coach import enrich_chat_response
    
    user_id = user["id"]
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
        "user_id": user_id,
        "date": {"$gte": seven_days_ago.isoformat()}
    }).sort("date", -1).to_list(20)
    
    all_activities = await db.workouts.find({
        "user_id": user_id,
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
    
    # ACWR — TrainingLoad V2 not available in this context (no garmin_activities).
    # CTL/ATL/TSB km-based aliases removed (PR #127 — faux physiological metrics).
    # km_7/(km_28/4) must NOT be exposed as ACWR (#127 pre-merge corrections).
    acwr: Optional[float] = None

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
            "user_id": user_id,
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
            "acwr_status": (
                "unavailable" if acwr is None
                else ("optimal" if 0.8 <= acwr <= 1.3 else "attention")
            ),
            # TSB removed (PR #127): no V2 equivalent; use None.
            "tsb": None,
            "tsb_status": "unavailable",
        },
        "all_sessions": "\n".join(all_sessions_summary) if all_sessions_summary else "No recorded sessions",
        "training_plan": training_plan_summary if training_plan_summary else "No active training plan",
        "current_goal": current_goal,
        "vma": vma_info,
        "predictions": predictions_summary
    }

    # 5. If workout_id specified, enrich context with session details
    if request.workout_id:
        workout = await db.workouts.find_one({"id": request.workout_id, "user_id": user_id})
        
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
async def get_conversation_history(user: dict = Depends(auth_user), limit: int = 50):
    """Get conversation history for a user"""
    user_id = user["id"]
    messages = await db.conversations.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(limit)
    return messages


@api_router.delete("/coach/history")
async def clear_conversation_history(user: dict = Depends(auth_user)):
    """Clear conversation history for a user"""
    user_id = user["id"]
    result = await db.conversations.delete_many({"user_id": user_id})
    return {"deleted_count": result.deleted_count}


@api_router.get("/messages")
async def get_messages(user: dict = Depends(auth_user), limit: int = 20):
    """Get recent coach messages (legacy endpoint)"""
    user_id = user["id"]
    messages = await db.conversations.find({"user_id": user_id}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return messages


@api_router.post("/coach/guidance", response_model=GuidanceResponse)
async def get_adaptive_guidance(request: GuidanceRequest, user: dict = Depends(auth_user)):
    """Generate adaptive training guidance based on recent workouts - 100% LOCAL ENGINE"""
    
    language = request.language or "en"
    user_id = user["id"]
    
    # Get recent workouts (last 14 days)
    all_workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(100)
    
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
async def get_latest_guidance(user: dict = Depends(auth_user)):
    """Get the most recent guidance for a user"""
    user_id = user["id"]
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
async def get_weekly_review(user: dict = Depends(auth_user), language: str = "en"):
    """Generate weekly training review (Bilan de la semaine) - 100% LOCAL ENGINE, NO LLM"""
    
    user_id = user["id"]
    all_workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(200)
    
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
async def get_latest_digest(user: dict = Depends(auth_user)):
    """Get the most recent digest for a user"""
    user_id = user["id"]
    digest = await db.digests.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("generated_at", -1)]
    )
    return digest


@api_router.get("/coach/digest/history")
async def get_digest_history(user: dict = Depends(auth_user), limit: int = 10, skip: int = 0):
    """Get history of weekly digests for a user"""
    user_id = user["id"]
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
async def get_rag_dashboard(user: dict = Depends(auth_user)):
    """Get RAG-enriched dashboard summary"""
    user_id = user["id"]
    workouts = await db.workouts.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("date", -1).limit(100).to_list(length=100)
    
    bilans = await db.digests.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("generated_at", -1).limit(8).to_list(length=8)
    
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
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
async def get_rag_weekly_review(user: dict = Depends(auth_user), language: str = "fr"):
    """Get RAG-enriched weekly review with GPT-4o-mini enhancement"""
    user_id = user["id"]
    workouts = await db.workouts.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("date", -1).limit(50).to_list(length=50)
    
    bilans = await db.digests.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("generated_at", -1).limit(8).to_list(length=8)
    
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
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
async def get_rag_workout_analysis(workout_id: str, user: dict = Depends(auth_user), language: str = "fr"):
    """Get RAG-enriched workout analysis with GPT-4o-mini enhancement"""
    user_id = user["id"]
    # Fetch the workout
    workout = await db.workouts.find_one(
        {"id": workout_id, "user_id": user_id},
        {"_id": 0}
    )
    
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    all_workouts = await db.workouts.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("date", -1).limit(100).to_list(length=100)
    
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
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
async def get_mobile_workout_analysis(workout_id: str, language: str = "en", user: dict = Depends(auth_user)):
    """Get mobile-first workout analysis with coach summary and signals - 100% LOCAL ENGINE"""
    
    user_id = user["id"]
    all_workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(100)
    
    # Find the workout (only within user's own workouts to prevent IDOR)
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
async def get_detailed_analysis(workout_id: str, language: str = "en", user: dict = Depends(auth_user)):
    """Get card-based detailed analysis for mobile view - 100% LOCAL ENGINE"""
    
    user_id = user["id"]
    all_workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(100)
    
    # Find the workout (only within user's own workouts to prevent IDOR)
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
async def get_terra_status(user: dict = Depends(auth_user)):
    """Get Terra connection status for a user."""
    user_id = user["id"]
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
async def terra_connect(req: TerraConnectRequest, user: dict = Depends(auth_user)):
    """Save a Terra access token for a user (token-based auth flow).

    In production, replace this with a full Terra OAuth widget flow.
    The client obtains a Terra user token via the Terra Connect Widget and
    posts it here to persist the connection.
    """
    user_id = user["id"]
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
async def sync_terra(user: dict = Depends(auth_user)):
    """Sync all Terra data for a user: workouts + daily metrics.

    Calls syncTerraWorkouts and syncDailyMetrics then regenerates the
    recovery score, training load, and workout recommendation.
    """
    user_id = user["id"]
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
async def sync_terra_daily(user: dict = Depends(auth_user)):
    """Sync daily health metrics from Terra (HRV, RHR, sleep).

    Useful for a lightweight, metrics-only refresh without re-importing workouts.
    """
    user_id = user["id"]
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
async def disconnect_terra(user: dict = Depends(auth_user)):
    """Disconnect Terra for a user (remove stored token)."""
    user_id = user["id"]
    await db.terra_tokens.delete_one({"user_id": user_id})
    logger.info("Terra disconnected for user: %s", user_id)
    return {"success": True, "message": "Terra disconnected"}


@api_router.get("/terra/recovery")
async def get_terra_recovery(user: dict = Depends(auth_user)):
    """Return the latest persisted recovery score for a user.

    If no score exists for today, triggers a fresh computation.
    """
    user_id = user["id"]
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
async def get_terra_recommendation(user: dict = Depends(auth_user)):
    """Return today's workout recommendation derived from Terra data.

    Triggers computation if no recommendation exists for today.
    """
    user_id = user["id"]
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
async def get_terra_daily_metrics(user: dict = Depends(auth_user)):
    """Return the latest daily metrics (HRV, RHR, sleep) for a user."""
    user_id = user["id"]
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
    "reasons": [],
    "metrics": None,
    "history": [],
}


@api_router.get("/run-index")
async def get_run_index(user: dict = Depends(auth_user), language: str = "fr"):
    """Return the full RunIndex running-screen payload.

    Data source: 100% real Garmin (gccli). Resting HR + sleep come from gccli;
    training load / ACWR / readiness are computed from the real synced activities.

    Terra is implemented for POSSIBLE FUTURE USE but is NOT connected: when no
    Terra token exists (current state), the endpoint returns a NO_DATA payload
    (never mock data).
    """
    user_id = user["id"]
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
            from garmin.insights import compute_run_index
            garmin_payload = await compute_run_index(db, user_id, language)
            if garmin_payload:
                return garmin_payload
        except Exception as e:
            logger.warning(f"[run-index] Garmin computation failed, falling back: {e}")

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

    # Training load — TrainingLoad V2 (PR #127 correction: no None→0.0→0.1 clamp).
    # Fetch Terra workouts and adapt them to the TrainingLoad V2 domain format so
    # that build_training_load() can compute ACWR from duration data.
    # If no duration data is present, acwr stays None — no numeric fallback.
    # ----------------------------------------------------------------
    _twenty_eight_days_ago = (today - timedelta(days=28)).isoformat()
    _terra_workouts = await db.workouts.find(
        {"user_id": user_id, "date": {"$gte": _twenty_eight_days_ago}},
        {"type": 1, "date": 1, "distance_km": 1, "duration_minutes": 1, "_id": 0},
    ).to_list(200)

    def _adapt_workout_for_v2(w: dict) -> dict:
        """Map a db.workouts document to a TrainingLoad V2-compatible activity dict."""
        wtype = (w.get("type") or "").lower()
        if wtype == "run":
            act_type = "running"
        elif wtype == "trail":
            act_type = "trail_running"
        elif wtype == "treadmill":
            act_type = "treadmill_running"
        else:
            act_type = wtype  # non-running types are filtered out by build_training_load
        dur_min = w.get("duration_minutes")
        dist_km = w.get("distance_km")
        return {
            "activity_type": act_type,
            "start_time": w.get("date"),
            "distance_m": dist_km * 1000.0 if dist_km is not None else None,
            "duration_s": dur_min * 60.0 if dur_min is not None else None,
        }

    _v2_activities = [_adapt_workout_for_v2(w) for w in _terra_workouts]
    _load_snapshot = build_training_load(_v2_activities, today)
    acwr: Optional[float] = _load_snapshot.acwr
    # training_load mirrors acwr — None when unavailable (no 0.0/0.1 clamp).
    training_load: Optional[float] = acwr

    # ----------------------------------------------------------------
    # Recommendation — Terra path.
    # Terra is currently non-connected / future use.  Readiness V2 is NOT
    # available on this path, so no physiological formula is invented.
    # A neutral UNAVAILABLE state is returned explicitly.
    # ----------------------------------------------------------------
    hrv_delta = float(hrv_baseline) - float(hrv_today)            # positive → HRV below baseline (bad)
    rhr_delta = float(rhr_today) - float(rhr_baseline)            # positive → RHR above baseline (bad)
    sleep_score = max(0.0, 8.0 - sleep_hours) + (1.0 - sleep_efficiency) * 2.0

    # Readiness V2 unavailable on Terra path — no parallel physio formula.
    recommendation = "UNAVAILABLE"
    recommendation_emoji = "⚫"
    recommendation_color = "gray"

    # ----------------------------------------------------------------
    # Per-metric status colours (raw data preserved for display/debug).
    # ----------------------------------------------------------------
    hrv_status = "green" if hrv_delta <= 5 else ("yellow" if hrv_delta <= 10 else "red")
    rhr_status = "green" if rhr_delta <= 3 else ("yellow" if rhr_delta <= 7 else "red")
    sleep_status = "green" if sleep_score <= 1.0 else ("yellow" if sleep_score <= 2.5 else "red")
    load_status = (
        "gray" if acwr is None
        else ("green" if 0.8 <= acwr <= 1.3 else ("yellow" if acwr <= 1.5 else "red"))
    )

    # ----------------------------------------------------------------
    # Human-readable reasons.
    # ----------------------------------------------------------------
    hrv_prefix = "+" if hrv_delta >= 0 else ""  # "+" = below baseline; "-" = above baseline
    rhr_prefix = "+" if rhr_delta >= 0 else ""  # "+" = above baseline
    reasons = [
        f"HRV deviation {hrv_prefix}{hrv_delta:.1f} ms vs baseline",
        f"RHR {rhr_prefix}{rhr_delta:.1f} bpm vs baseline",
        f"Sleep {sleep_hours:.1f} h at {sleep_efficiency * 100:.0f}% efficiency",
        f"Training Load (ACWR) {acwr:.2f}" if acwr is not None else "Training Load (ACWR) unavailable",
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

        history.append({
            "day": day_label,
            "date": doc_date,
            "hrv": round(float(doc_hrv), 1),
            "training_load": round(training_load, 2) if training_load is not None else None,
        })

    # Leave history empty if fewer than 7 days of data (no mock padding).
    if not history:
        history = []

    return {
        "mock": False,
        "recommendation": recommendation,
        "recommendation_emoji": recommendation_emoji,
        "recommendation_color": recommendation_color,
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
            "training_load": round(acwr, 2) if acwr is not None else None,
            "training_load_status": load_status,
        },
        "reasons": reasons,
        "history": history,
    }


@api_router.get("/run-index/history")
async def get_run_index_history(
    user: dict = Depends(auth_user),
    period: str = Query("6m", description="Period key: 3m, 6m or 12m"),
    months: Optional[int] = Query(None, description="Legacy period in months: 3, 6 or 12"),
    language: str = Query("fr", description="Language for AI analysis"),
):
    """
    Return the historical evolution of the RunIndex and its pillars.

    Data source: run_index_scores collection.
    Returns period-aware weekly or monthly points for the selected period.
    """
    user_id = user["id"]
    payload = await get_run_index_history_payload(db, user_id, period=period, months=months)
    payload["ai_analysis"] = _generate_run_index_analysis(
        current_run_index=payload["current_run_index"],
        trend=payload["trend"],
        months=payload["period_months"],
        pillars=payload["pillars"],
        language=language,
    )
    return payload


def _generate_run_index_analysis(
    current_run_index: Optional[int],
    trend: int,
    months: int,
    pillars: dict,
    language: str,
) -> str:
    """Generate a template-based analysis of RunIndex evolution (no LLM required)."""
    if current_run_index is None:
        if language == "fr":
            return "Pas encore assez de données pour analyser ta progression."
        if language == "es":
            return "Todavía no hay suficientes datos para analizar tu progresión."
        return "Not enough data yet to analyse your progression."

    # Find best and worst improving pillar
    pillar_names_fr = {
        "speed": "vitesse",
        "endurance": "endurance",
        "consistency": "régularité",
        "efficiency": "efficacité",
    }
    pillar_names_en = {
        "speed": "speed",
        "endurance": "endurance",
        "consistency": "consistency",
        "efficiency": "efficiency",
    }
    pillar_names_es = {
        "speed": "velocidad",
        "endurance": "resistencia",
        "consistency": "consistencia",
        "efficiency": "eficiencia",
    }
    if language == "fr":
        names = pillar_names_fr
    elif language == "es":
        names = pillar_names_es
    else:
        names = pillar_names_en

    evolutions = {
        p: data.get("evolution") or 0
        for p, data in pillars.items()
        if data.get("evolution") is not None
    }

    best_pillar = max(evolutions, key=lambda p: evolutions[p]) if evolutions else None
    worst_pillar = min(evolutions, key=lambda p: evolutions[p]) if evolutions else None

    if language == "fr":
        parts = []
        if trend > 0:
            parts.append(f"Ton RunIndex a progressé de {trend} points en {months} mois.")
        elif trend < 0:
            parts.append(f"Ton RunIndex a reculé de {abs(trend)} points en {months} mois.")
        else:
            parts.append(f"Ton RunIndex est stable sur les {months} derniers mois.")

        if best_pillar and evolutions.get(best_pillar, 0) > 0:
            parts.append(f"Ta plus forte amélioration vient de ta {names[best_pillar]}.")

        if worst_pillar and evolutions.get(worst_pillar, 0) < 0:
            tips = {
                "speed": "Un travail de seuil ou d'intervalles pourrait accélérer ta progression.",
                "endurance": "Augmenter progressivement ton volume hebdomadaire t'aidera.",
                "consistency": "La régularité est la clé : essaie de courir au moins 3 fois par semaine.",
                "efficiency": "Des séances à allure modérée avec FC contrôlée améliorent l'efficacité.",
            }
            parts.append(
                f"Ta {names[worst_pillar]} est en recul. "
                + tips.get(worst_pillar, "Continue à t'entraîner régulièrement.")
            )
        elif worst_pillar and best_pillar and worst_pillar != best_pillar:
            tips = {
                "speed": "Un travail de seuil pourrait accélérer ta progression.",
                "endurance": "Augmenter ton volume de sortie longue t'aidera.",
                "consistency": "Maintenir une cadence régulière est clé pour progresser.",
                "efficiency": "Des sorties à allure aérobie améliorent ton efficacité cardiaque.",
            }
            parts.append(
                f"Ta {names[worst_pillar]} progresse plus lentement. "
                + tips.get(worst_pillar, "Continue ton entraînement régulier.")
            )

        return " ".join(parts)

    elif language == "es":
        parts = []
        if trend > 0:
            parts.append(f"Tu RunIndex ha mejorado {trend} puntos en {months} meses.")
        elif trend < 0:
            parts.append(f"Tu RunIndex ha bajado {abs(trend)} puntos en {months} meses.")
        else:
            parts.append(f"Tu RunIndex está estable en los últimos {months} meses.")

        if best_pillar and evolutions.get(best_pillar, 0) > 0:
            parts.append(f"Tu mayor mejora proviene de tu {names[best_pillar]}.")

        if worst_pillar and evolutions.get(worst_pillar, 0) < 0:
            tips = {
                "speed": "El trabajo de umbral o intervalos puede acelerar tu progresión.",
                "endurance": "Aumentar progresivamente tu volumen semanal te ayudará.",
                "consistency": "La constancia es clave: intenta correr al menos 3 veces por semana.",
                "efficiency": "Las salidas aeróbicas fáciles con FC controlada mejoran la eficiencia.",
            }
            parts.append(
                f"Tu {names[worst_pillar]} está en retroceso. "
                + tips.get(worst_pillar, "Continúa entrenando regularmente.")
            )
        elif worst_pillar and best_pillar and worst_pillar != best_pillar:
            tips = {
                "speed": "El trabajo de umbral puede acelerar tu progresión.",
                "endurance": "Aumentar el volumen de tu salida larga te ayudará.",
                "consistency": "Mantener una cadencia regular es clave para progresar.",
                "efficiency": "Las salidas aeróbicas mejoran tu eficiencia cardíaca.",
            }
            parts.append(
                f"Tu {names[worst_pillar]} progresa más lentamente. "
                + tips.get(worst_pillar, "Continúa con tu entrenamiento regular.")
            )

        return " ".join(parts)

    else:
        parts = []
        if trend > 0:
            parts.append(f"Your RunIndex improved by {trend} points over {months} months.")
        elif trend < 0:
            parts.append(f"Your RunIndex dropped by {abs(trend)} points over {months} months.")
        else:
            parts.append(f"Your RunIndex is stable over the last {months} months.")

        if best_pillar and evolutions.get(best_pillar, 0) > 0:
            parts.append(f"Your biggest improvement comes from your {names[best_pillar]}.")

        if worst_pillar and evolutions.get(worst_pillar, 0) < 0:
            tips = {
                "speed": "Threshold or interval work could accelerate your progress.",
                "endurance": "Gradually increasing your weekly volume will help.",
                "consistency": "Consistency is key: aim for at least 3 runs per week.",
                "efficiency": "Easy aerobic runs with controlled HR improve efficiency.",
            }
            parts.append(
                f"Your {names[worst_pillar]} is declining. "
                + tips.get(worst_pillar, "Keep training regularly.")
            )
        elif worst_pillar and best_pillar and worst_pillar != best_pillar:
            tips = {
                "speed": "Threshold work could accelerate your progress.",
                "endurance": "Increasing your long run volume will help.",
                "consistency": "Maintaining a regular cadence is key to progress.",
                "efficiency": "Easy aerobic runs improve your cardiac efficiency.",
            }
            parts.append(
                f"Your {names[worst_pillar]} is progressing more slowly. "
                + tips.get(worst_pillar, "Keep up your regular training.")
            )

        return " ".join(parts)


# ========== PREMIUM SUBSCRIPTION ==========


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


class ChatRequest(BaseModel):
    message: str
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
async def delete_training_goal(user: dict = Depends(auth_user)):
    """Delete the training goal"""
    user_id = user["id"]
    result_context = await db.training_context.delete_one({"user_id": user_id})
    result_cycles = await db.training_cycles.delete_one({"user_id": user_id})

    deleted = result_context.deleted_count + result_cycles.deleted_count
    return {
        "success": deleted > 0,
        "message": "Goal deleted" if deleted > 0 else "No goal found"
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
async def get_dynamic_training_plan_legacy(user: dict = Depends(auth_user)):
    """Legacy endpoint - utiliser /training-plan à la place"""
    user_id = user["id"]
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


# ──────────────────────────────────────────────────────────────────────────────
# PR137 — Daily Runtime Migration V2
# Helper functions are in training_v2/daily_runtime_helpers.py (pure, testable).
# ──────────────────────────────────────────────────────────────────────────────


@api_router.get("/training/today")
async def get_today_adaptive_session(user: dict = Depends(auth_user)):
    """
    Returns today's adaptive training session.

    Runtime path (PR137 — Daily Runtime Migration V2):
        plan V2 (#135)
          ↓
        séance prévue aujourd'hui (WorkoutPrescription)
          ↓
        ReadinessResult V2
          ↓
        ReadinessDecision V2 (#133)
          ↓
        DailyAdaptation V2 (#133)
          ↓
        séance du jour adaptée → payload /training/today

    ReadinessDecision is the single readiness translation layer.
    DailyAdaptation only adapts (keep or reduce), never increases.
    None ≠ 0: absent data is never treated as bad readiness.
    """
    # Anchor date determined here at the runtime boundary, then passed explicitly
    # to all V2 pure layers (no hidden now()/today() inside business functions).
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()
    day_name = today.strftime("%A")

    # ── 1. Plan V2 — source of the planned session ────────────────────────────
    plan = await generate_dynamic_training_plan(db, user["id"])
    if plan is None:
        return {
            "has_plan": False,
            "message": "Aucun plan d'entraînement actif",
            "suggestion": "Créez un objectif pour générer votre plan personnalisé.",
        }
    sessions = (plan.get("plan") or {}).get("sessions", [])
    vma = plan.get("vma") or (plan.get("context", {}) or {}).get("vma")

    # Find today's planned session by day name
    planned_session_runtime: Optional[dict] = None
    for session in sessions:
        if session.get("day", "").lower() == day_name.lower():
            planned_session_runtime = session
            break

    if not planned_session_runtime:
        return {
            "status": "no_session",
            "message": "No session planned for today",
            "date": today_iso,
            "day": day_name,
        }

    # ── 2. Convert runtime dict → WorkoutPrescription (V2 contract) ───────────
    planned_prescription = runtime_session_to_prescription(planned_session_runtime)

    # ── 3. ReadinessResult V2 — from Garmin data (no legacy proxy) ───────────
    readiness_result = None
    training_load = None
    recent_response = None
    readiness_data_source = "unavailable"

    garmin_conn = await db.garmin_connections.find_one({"user_id": user["id"]}, {"_id": 0})
    if garmin_conn and garmin_conn.get("connected"):
        try:
            metrics_docs = await (
                db.garmin_daily_metrics.find({"user_id": user["id"]}, {"_id": 0})
                .sort("date", -1)
                .limit(30)
                .to_list(length=30)
            )
            garmin_activities = await (
                db.garmin_activities.find({"user_id": user["id"]}, {"_id": 0})
                .sort("start_time", -1)
                .limit(200)
                .to_list(length=200)
            )
            # ── Mongo → DomainActivity boundary (PR137) ──────────────────────
            # Raw MongoDB documents are never passed directly to Training V2
            # modules.  The explicit adapter resolves the garmin_activity
            # sub-document (normalized field names) with fallback to top-level
            # aliases for legacy documents.
            domain_activities = mongo_garmin_activities_to_domain(garmin_activities)
            # TrainingLoadSnapshot — single computation shared with ReadinessResult V2
            training_load = build_training_load(domain_activities, today)
            # ReadinessResult V2 (reuses pre-built load_snapshot, no duplicate computation)
            readiness_result = build_readiness_v2_from_garmin_data(
                metrics_docs, domain_activities, today, load_snapshot=training_load
            )
            # RecentTrainingResponse V2 (#132)
            recent_response = build_recent_training_response(domain_activities, today)
            readiness_data_source = "garmin"
        except Exception as exc:
            logger.warning(f"[TrainingToday] Garmin V2 readiness build failed: {exc}")

    # ── 4. ReadinessDecision V2 — canonical translation (no thresholds in endpoint) ─
    readiness_decision: ReadinessDecision = build_readiness_decision(readiness_result)

    # ── 5. DailyAdaptation V2 — engine #133 (keep or reduce, never increase) ──
    adaptation_result: DailyAdaptationResult = build_daily_adaptation(
        workout=planned_prescription,
        readiness_decision=readiness_decision,
        training_load=training_load,
        recent_response=recent_response,
    )

    # ── 6. Map adapted prescription back to runtime dict format ──────────────
    # original_prescription: derived directly from planned_session_runtime to
    # avoid any implicit divergence via the WorkoutPrescription round-trip.
    adapted_runtime = prescription_to_runtime_session(adaptation_result.adapted_workout)
    adaptation_applied = adaptation_result.action != DailyAdaptationAction.KEEP
    adaptation_reason = ", ".join(adaptation_result.reason_codes)

    # ── 7. Legacy compat: recommendation / recommendation_color derived from V2 ─
    # These fields remain temporarily because the frontend may still consume them.
    # Direction: V2 ReadinessDecision → compatibility adapter. Never legacy → V2.
    recommendation, recommendation_color = BAND_TO_RECOMMENDATION[readiness_decision.band]

    # ── 8. Historical feedback (unchanged) ────────────────────────────────────
    feedback_cursor = db.training_feedback.find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).sort("date", -1).limit(10)
    recent_feedback = await feedback_cursor.to_list(10)

    return {
        "status": "success",
        "date": today_iso,
        "day": day_name,
        # Original planned session (runtime dict from plan V2)
        "planned_session": planned_session_runtime,
        # V2 prescription objects (preferred by new consumers)
        "original_prescription": planned_session_runtime,
        "adapted_prescription": adapted_runtime,
        # Legacy compat: adaptive_session present when adaptation changed the session
        "adaptive_session": adapted_runtime if adaptation_applied else None,
        "adaptation_applied": adaptation_applied,
        "adaptation_reason": adaptation_reason,
        "adaptation_action": adaptation_result.action.value,
        "reason_codes": list(adaptation_result.reason_codes),
        # ReadinessDecision V2 block
        "readiness": {
            "band": readiness_decision.band.value,
            "score": readiness_decision.score,
            "confidence": readiness_decision.confidence.value,
            "sufficiency_level": readiness_decision.sufficiency_level.value,
            "available": readiness_decision.band != ReadinessBand.UNAVAILABLE,
            "data_source": readiness_data_source,
        },
        # Legacy compat: fatigue block derived from V2 (no fatigue_ratio/fatigue_status/fatigue_physio)
        "fatigue": {
            "run_readiness": readiness_decision.score,
            "recommendation": recommendation,
            "recommendation_color": recommendation_color,
            "data_source": readiness_data_source,
        },
        "vma": vma,
        "vma_confidence": plan.get("vma_confidence"),
        "recent_feedback": recent_feedback,
    }


@api_router.get("/training/metrics")
async def get_training_metrics(user: dict = Depends(auth_user)):
    """
    Returns training metrics: ACWR, TSB, load, monotony.
    Used by Dashboard to display fitness status.

    ACWR and load (duration-based) come from TrainingLoadSnapshot V2
    (build_training_load) — the SINGLE SOURCE OF TRUTH, aligned with /run-index.
    load_7 / load_28 remain distance-based (km) for the "THIS WEEK" / "28D LOAD"
    display cards; they do NOT feed ACWR or TSB.

    None semantics:
    - acwr is None when there is no valid Garmin duration data (build_training_load
      returns acwr=None when chronic load is zero or no running activities have
      a valid duration).
    - No ACWR=1.0 fallback.  No distance→duration estimation.
    """
    today = datetime.now(timezone.utc)
    today_date = today.date()
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)

    # --- Distance-based display cards (km) — user workout records ---
    user_filter = {"user_id": user["id"]}
    activities_7 = await db.workouts.find({
        **user_filter,
        "date": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)

    activities_28 = await db.workouts.find({
        **user_filter,
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)

    def get_distance(a):
        return a.get("distance_km", 0) or 0

    load_7 = sum(get_distance(a) for a in activities_7)
    load_28 = sum(get_distance(a) for a in activities_28)

    # --- TrainingLoadSnapshot V2 — SINGLE SOURCE OF TRUTH ---
    # Fetch real Garmin activities (same collection as /run-index).
    garmin_activities = await (
        db.garmin_activities.find({"user_id": user["id"]}, {"_id": 0})
        .sort("start_time", -1)
        .limit(200)
        .to_list(length=200)
    )
    # PR #143: convert to DomainActivity before passing to V2 layers.
    domain_activities = mongo_garmin_activities_to_domain(garmin_activities)
    load_snapshot = build_training_load(domain_activities, today_date)

    # ACWR — None when no chronic load (no fallback to 1.0)
    acwr: Optional[float] = load_snapshot.acwr

    # TSB — LEGACY distance-based (km).
    # TSB — legacy km-based formula removed (PR #127).
    # No V2 TSS-based equivalent is available.  Frontend consumers (TrainingPlan,
    # Dashboard) handle None via the tsb_status / tsb_label fields.
    # ctl/atl: also None (not consumed by the frontend).
    tsb: Optional[float] = None

    # --- Monotonie (distance-based, 7-day display only) ---
    daily_loads = []
    for i in range(7):
        day = (today - timedelta(days=i)).date()
        day_load = 0.0
        for a in activities_7:
            try:
                a_date_str = a.get("start_date_local", a.get("date", ""))
                if a_date_str:
                    a_date = datetime.fromisoformat(a_date_str.replace("Z", "+00:00")).date()
                    if a_date == day:
                        day_load += get_distance(a)
            except Exception:
                pass
        daily_loads.append(day_load)

    if daily_loads and len(daily_loads) >= 2:
        avg_load = sum(daily_loads) / len(daily_loads)
        variance = sum((x - avg_load) ** 2 for x in daily_loads) / len(daily_loads)
        std = variance ** 0.5
        monotony = round(avg_load / std, 2) if std > 0 else 0
    else:
        monotony = 0

    strain = round(load_7 * monotony, 0) if monotony > 0 else 0

    # --- ACWR reliability: based on TrainingState V2 (reprise detection) ---
    # PR #143: migrate from legacy classify_training_state to V2 chain.
    # Reuses domain_activities already converted above.
    training_history = build_training_history(domain_activities, today_date)
    runner_profile = build_runner_profile(
        training_history=training_history,
        training_load=load_snapshot,
        reference_date=today_date,
    )
    training_state = build_training_state(
        training_history=training_history,
        training_load=load_snapshot,
        runner_profile=runner_profile,
        reference_date=today_date,
    )
    reprise_state = training_state.continuity_state
    acwr_reliable = reprise_state not in ("deep_reprise", "partial_reprise")

    # --- Interpréter ACWR ---
    if acwr is None:
        acwr_status = "unavailable"
        acwr_label = "Données insuffisantes"
    elif not acwr_reliable:
        acwr_status = "building"
        acwr_label = "Base en construction"
    elif acwr < 0.8:
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

    # --- Interpréter TSB ---
    # TSB needs a stable training base; mark "building" during reprise.
    # tsb_reliable mirrors acwr_reliable: both are unreliable when the athlete
    # is in deep_reprise or partial_reprise, regardless of history depth.
    tsb_reliable = acwr_reliable
    if tsb is None:
        tsb_status = "unavailable"
        tsb_label = "Données insuffisantes"
    elif not tsb_reliable:
        tsb_status = "building"
        tsb_label = "Base en construction"
    elif tsb > 10:
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
        "acwr_reliable": acwr_reliable,
        "tsb": tsb,
        "tsb_status": tsb_status,
        "tsb_label": tsb_label,
        "tsb_reliable": tsb_reliable,
        "load_7": round(load_7, 1),
        "load_28": round(load_28, 1),
        "monotony": monotony,
        "strain": strain,
        # ctl/atl: not consumed by the frontend; set to None until a dedicated
        # migration PR replaces them with V2-aligned duration-based values.
        "ctl": None,
        "atl": None,
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
    
    user_id = user["id"]
    # Récupérer les activités des 6 dernières semaines (scoped to authenticated user)
    activities = await db.workouts.find({
        "user_id": user_id,
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
    user_id = user["id"]
    # Récupérer toutes les activités des 12 derniers mois (scoped to authenticated user)
    activities = await db.workouts.find({
        "user_id": user_id,
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
    Cycle dates are anchored to user_goals.event_date (single source of truth).
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
    standard_weeks = cycle.get("adjusted_weeks") or config["cycle_weeks"]

    # Retrieve session preferences
    prefs = await db.training_prefs.find_one({"user_id": user["id"]})
    sessions_per_week = prefs.get("sessions_per_week", 4) if prefs else 4

    # --- Temporal alignment: anchor cycle to event_date (user_goals) ---
    user_goal = await db.user_goals.find_one({"user_id": user["id"]})
    raw_event_date = (user_goal or {}).get("event_date") if user_goal else None
    event_date_obj = None
    if raw_event_date:
        try:
            if isinstance(raw_event_date, str):
                event_date_obj = datetime.fromisoformat(raw_event_date.split("T")[0]).date()
            elif hasattr(raw_event_date, "date"):
                event_date_obj = raw_event_date.date()
        except (ValueError, AttributeError):
            event_date_obj = None

    today_date = datetime.now(timezone.utc).date()

    # Cap standard_weeks to weeks available before the race
    if event_date_obj is not None:
        weeks_available = max(1, (event_date_obj - today_date).days // 7)
        total_weeks = min(standard_weeks, weeks_available)
    else:
        total_weeks = standard_weeks

    cycle_dates = compute_cycle_dates(
        event_date=event_date_obj,
        total_weeks=total_weeks,
        today=today_date,
    )
    current_week = cycle_dates["current_week"]
    cycle_status = cycle_dates["status"]

    # Retrieve athlete's current volume (based on last 28 days)
    today = datetime.now(timezone.utc)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    workouts_28 = await db.workouts.find({
        "user_id": user["id"],
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)
    
    km_28 = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))
    base_weekly_km = compute_current_weekly_km(workouts_28)
    # PR76b: use an active-weeks base so a comeback (sparse data) is not
    # diluted by the fixed /4 divisor, and a genuine 0 km resolves to a
    # conservative reprise base instead of the 20 km default.
    target_base_km = resolve_chronic_base(workouts_28)

    # PR76 resume guard: also look at last 7 days to detect resuming athletes
    seven_days_ago = today - timedelta(days=7)
    workouts_7 = [w for w in workouts_28 if (w.get("date") or "") >= seven_days_ago.isoformat()]
    km_7 = sum(normalized_distance_km(w) for w in workouts_7 if is_running(w))

    # Reprise-aware target/state for the CURRENT week (single source of truth).
    current_phase = determine_phase(current_week, total_weeks)
    reprise = resolve_reprise_plan(workouts_28, goal, current_phase, km_7=km_7)
    reprise_state = reprise["state"]
    reprise_active = reprise_state in ("deep_reprise", "partial_reprise")
    # Projected calendar week where intensity is re-introduced (reprise_exit):
    # once REPRISE_STABLE_WEEKS active weeks are completed.
    reprise_transition_week = (
        current_week + max(0, REPRISE_STABLE_WEEKS - reprise["active_weeks"])
        if reprise_active else None
    )

    # Generate overview of all weeks
    weeks_overview = []
    
    for week_num in range(1, total_weeks + 1):
        phase = determine_phase(week_num, total_weeks)
        phase_info = get_phase_description(phase, lang)
        
        # Target volume — SAME engine as the detailed week plan so cards match sessions.
        # The current week uses the reprise-aware target; future weeks project normally.
        is_current_week = cycle_status == "active" and week_num == current_week
        if is_current_week:
            target_km = reprise["target_km"]
        else:
            target_km = compute_target_km(target_base_km, goal, phase)
            target_km = apply_resume_guard(target_km, km_7, target_base_km)
        
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

        # Reprise: the current week is easy-only (no threshold/tempo/long run).
        is_reprise_week = is_current_week and reprise_state in ("deep_reprise", "partial_reprise")
        if is_reprise_week:
            session_types = ["endurance", "recovery", "endurance"]

        if is_reprise_week:
            week_sessions = len(session_types)
        elif phase in ["taper", "race"]:
            week_sessions = min(3, sessions_per_week)
        else:
            week_sessions = sessions_per_week

        weeks_overview.append({
            "week": week_num,
            "phase": phase,
            "phase_name": phase_info.get("name", phase),
            "phase_focus": phase_info.get("focus", ""),
            "target_km": target_km,
            "sessions": week_sessions,
            "session_types": session_types[:sessions_per_week],
            "is_current": is_current_week,
            "is_completed": cycle_status == "active" and week_num < current_week,
            "is_reprise": is_reprise_week,
            "is_reprise_transition": reprise_active and reprise_transition_week is not None and week_num == reprise_transition_week,
            "intensity_pct": phase_info.get("intensity_pct", 15)
        })
    
    current_target_km = reprise["target_km"]

    return {
        "goal": goal,
        "goal_description": config["description"],
        "total_weeks": total_weeks,
        "current_week": current_week,
        "start_date": cycle_dates["start_date"].isoformat(),
        "end_date": cycle_dates["end_date"].isoformat(),
        "event_date": event_date_obj.isoformat() if event_date_obj else None,
        "days_to_race": cycle_dates["days_to_race"],
        "status": cycle_status,
        "sessions_per_week": sessions_per_week,
        "base_weekly_km": round(base_weekly_km),
        "debug_volume": {
            "km_7": round(km_7, 1),
            "km_28": round(km_28, 1),
            "current_weekly_km": round(base_weekly_km, 1),
            "target_km": current_target_km,
            "phase": current_phase,
        },
        "weeks": weeks_overview
    }


@api_router.get("/training/week-plan")
async def get_week_plan(user: dict = Depends(auth_user)):
    """
    Génère un plan d'entraînement détaillé pour la semaine via LLM.
    Utilise le contexte d'entraînement et l'objectif défini.

    PR149: Weekly prescription is now sourced from WeeklyTarget V2.
    PR157: determine_target_load removed from this path (display context only).
    """
    user_id = user["id"]
    # PR155: Read from canonical sources instead of legacy db.training_goals
    cycle = await db.training_cycles.find_one({"user_id": user_id}, {"_id": 0})

    if not cycle:
        raise HTTPException(status_code=400, detail="No goal defined. Use /api/training/set-goal first.")

    goal_type = cycle.get("goal")
    if not goal_type or goal_type not in GOAL_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown or missing goal type: {goal_type}")

    start_date_raw = cycle.get("start_date")
    if not start_date_raw:
        raise HTTPException(status_code=400, detail="No start_date in training cycle.")

    # Optional race metadata from user_goals
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    event_name = user_goal.get("event_name") if user_goal else None
    event_date = user_goal.get("event_date") if user_goal else None

    # Build normalized goal dict matching legacy shape consumed downstream
    goal = {
        "goal_type": goal_type,
        "start_date": start_date_raw,
        "cycle_weeks": GOAL_CONFIG[goal_type]["cycle_weeks"],
        "event_name": event_name,
        "event_date": event_date,
    }

    # Retrieve recent data for context
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    ninety_days_ago = today - timedelta(days=90)

    workouts_7 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)

    workouts_28 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(100)

    # PR149: 90-day window for V2 chain (matches coach_service pattern).
    workouts_90 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": ninety_days_ago.isoformat()}
    }).to_list(1000)

    # Calculer les métriques
    km_7 = sum(w.get("distance_km", 0) or 0 for w in workouts_7)
    km_28 = sum(w.get("distance_km", 0) or 0 for w in workouts_28)
    km_7_running = sum(normalized_distance_km(w) for w in workouts_7 if is_running(w))
    km_28_running = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))
    load_7 = km_7 * 10
    load_28 = km_28 * 10

    # ── PR149/PR163: WeeklyTarget V2 + WorkoutGenerator V2 ──────────────────
    # PR163: use build_weekly_plan_from_workouts so WorkoutGenerator V2 is the
    # authority on session distribution (long_easy distance in particular).
    from training_v2.week_plan_bridge import build_weekly_plan_from_workouts

    goal_start_date = goal["start_date"]
    if isinstance(goal_start_date, datetime) and goal_start_date.tzinfo is None:
        goal_start_date = goal_start_date.replace(tzinfo=timezone.utc)

    race_date_raw = goal.get("event_date")
    race_date_v2 = None
    if isinstance(race_date_raw, datetime):
        race_date_v2 = race_date_raw.date() if race_date_raw.tzinfo else race_date_raw.replace(tzinfo=timezone.utc).date()
    elif isinstance(race_date_raw, str):
        try:
            race_date_v2 = datetime.fromisoformat(race_date_raw.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            pass

    cycle_start_v2 = goal_start_date.date() if isinstance(goal_start_date, datetime) else goal_start_date

    weekly_target, weekly_plan_v2 = build_weekly_plan_from_workouts(
        workouts=workouts_90,
        goal_type=goal["goal_type"],
        race_date=race_date_v2,
        cycle_start_date=cycle_start_v2,
        reference_date=today.date(),
    )

    # PR149: V2 prescription → target_km_protected (distance-based only).
    # When duration-based: target_km_protected = None (no invented km).
    if weekly_target.target_basis == "distance" and weekly_target.target_km is not None:
        target_km_protected = weekly_target.target_km
    else:
        target_km_protected = None

    # PR163: extract long_easy distance from WorkoutGenerator V2 — single authority.
    # None for duration-based weeks (no artificial km injected).
    long_run_km_v2 = next(
        (s.distance_km for s in weekly_plan_v2.sessions if s.workout_type == "long_easy"),
        None,
    )

    # ── Legacy compat context (LLM) ─────────────────────────────────────────
    # ctl/atl/tsb km-based aliases removed (PR #127 — faux physiological metrics).
    # load_7/load_28 kept for context transparency; no longer consumed by
    # determine_target_load (PR #157 — removed from this path).
    # acwr=None — km_7/(km_28/4) must NOT be exposed as ACWR (#127 pre-merge corrections).
    context = {
        "ctl": None,
        "atl": None,
        "tsb": None,
        "acwr": None,
        "weekly_km": km_28_running / 4.0,
        "load_7": load_7,
        "load_28": load_28,
    }

    # Calculer la phase (legacy — kept for LLM/fallback compat)
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

    # PR157: determine_target_load removed — target_load is display context only,
    # never drives distances / durations / intensity.  planned_load → None.

    # PR149: V2 decides the prescription; legacy compat projects from V2.
    # target_km_protected is from WeeklyTarget V2 (or None for duration-based).
    context["target_km_protected"] = target_km_protected
    context["km_7"] = round(km_7_running, 1)
    context["training_state"] = weekly_target.continuity_state
    # PR149: transport V2 duration target for duration-based states.
    if weekly_target.target_basis == "duration":
        context["target_duration_minutes"] = weekly_target.target_duration_minutes
    # PR163: pass WorkoutGenerator V2 long_easy distance — display context only.
    if long_run_km_v2 is not None:
        context["long_run_km_v2"] = long_run_km_v2

    # PR165: WeeklyPlan V2 is the single prescription authority.
    # The adapter converts V2 sessions to the legacy JSON contract.
    # generate_cycle_week is NO LONGER called in this path.
    from training_v2.week_plan_adapter import adapt_weekly_plan_to_legacy
    plan = adapt_weekly_plan_to_legacy(weekly_plan_v2, weekly_target, phase)
    metadata = {
        "model": "deterministic_v2",
        "provider": "WeeklyPlan_V2",
        "context_type": "cycle_week",
        "duration_sec": 0,
        "success": True,
    }

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
        "debug_volume": {
            "km_7": round(km_7_running, 1),
            "km_28": round(km_28_running, 1),
            "current_weekly_km": round(context.get("weekly_km", DEFAULT_WEEKLY_KM), 1),
            "target_km": target_km_protected,
            "target_basis": weekly_target.target_basis,
            "target_duration_minutes": weekly_target.target_duration_minutes,
            "continuity_state": weekly_target.continuity_state,
            "phase": phase,
            "prescription_source": "WeeklyPlan_V2",
        },
        "plan": plan,
        "generated_by": "weekly_plan_v2",
        "metadata": metadata
    }


# ---------------------------------------------------------------------------
# PR167 — GET /training/v2/week
# Native V2 endpoint: returns WeeklyTarget + WeeklyPlan without any legacy
# adapter. Uses the same canonical builder as /training/week-plan so that
# WeeklyTarget and WeeklyPlan are computed exactly once and never duplicated.
# ---------------------------------------------------------------------------

@api_router.get("/training/v2/week", response_model=TrainingWeekV2Response)
async def get_training_v2_week(user: dict = Depends(auth_user)):
    """Return the current week's V2 native prescription.

    Pipeline (reuses the canonical builder from week_plan_bridge):
      TrainingHistory → TrainingState → PlanGoal → Periodization
      → WeeklyTarget → WorkoutGenerator → WeeklyPlan

    No legacy adapter applied. None stays None (None != 0 doctrine).
    """
    from training_v2.week_plan_bridge import build_weekly_plan_from_workouts
    from training_v2.training_week_response import (
        WeekV2GoalResponse,
        WeekV2PlanResponse,
        WeekV2SessionResponse,
        WeekV2StateResponse,
        WeekV2TargetResponse,
    )

    user_id = user["id"]

    # ── Single clock: resolve now_utc ONCE to avoid midnight-boundary skew ─
    now_utc = datetime.now(timezone.utc)
    reference_date = now_utc.date()

    # ── Goal & cycle from canonical sources (same as /training/week-plan) ─
    cycle = await db.training_cycles.find_one({"user_id": user_id}, {"_id": 0})
    if not cycle:
        raise HTTPException(
            status_code=400,
            detail="No training goal defined. Use /api/training/set-goal first.",
        )

    goal_type = cycle.get("goal")
    if not goal_type or goal_type not in GOAL_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or missing goal type: {goal_type}",
        )

    start_date_raw = cycle.get("start_date")
    if not start_date_raw:
        raise HTTPException(status_code=400, detail="No start_date in training cycle.")

    # ── Optional race metadata from user_goals ────────────────────────────
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})

    race_date_raw = user_goal.get("event_date") if user_goal else None
    race_date_v2 = None
    if isinstance(race_date_raw, datetime):
        race_date_v2 = (
            race_date_raw.date()
            if race_date_raw.tzinfo
            else race_date_raw.replace(tzinfo=timezone.utc).date()
        )
    elif isinstance(race_date_raw, str):
        try:
            race_date_v2 = datetime.fromisoformat(
                race_date_raw.replace("Z", "+00:00")
            ).date()
        except (ValueError, TypeError):
            pass

    target_time_minutes_raw = user_goal.get("target_time_minutes") if user_goal else None
    # Convert minutes→seconds at the API boundary (canonical DB field is target_time_minutes)
    if isinstance(target_time_minutes_raw, (int, float)) and not isinstance(target_time_minutes_raw, bool) and target_time_minutes_raw > 0:
        target_time_seconds = int(target_time_minutes_raw * 60)
    else:
        target_time_seconds = None

    cycle_start_v2: Optional[date] = None
    if isinstance(start_date_raw, datetime):
        cycle_start_v2 = (
            start_date_raw.date()
            if start_date_raw.tzinfo
            else start_date_raw.replace(tzinfo=timezone.utc).date()
        )
    elif isinstance(start_date_raw, str):
        try:
            cycle_start_v2 = datetime.fromisoformat(
                start_date_raw.replace("Z", "+00:00")
            ).date()
        except (ValueError, TypeError):
            pass

    # ── Workouts — 90-day window (same as /training/week-plan) ───────────
    ninety_days_ago = now_utc - timedelta(days=90)
    workouts_90 = await db.workouts.find(
        {"user_id": user_id, "date": {"$gte": ninety_days_ago.isoformat()}}
    ).to_list(1000)

    # ── Canonical builder — single call, no duplication ──────────────────
    weekly_target, weekly_plan = build_weekly_plan_from_workouts(
        workouts=workouts_90,
        goal_type=goal_type,
        race_date=race_date_v2,
        cycle_start_date=cycle_start_v2,
        reference_date=reference_date,
    )

    # ── Assemble native V2 response — no adapter, no coercion ────────────
    sessions = [
        WeekV2SessionResponse(
            day=s.day,
            workout_type=s.workout_type,
            intensity_class=s.intensity_class,
            distance_km=s.distance_km,
            duration_minutes=s.duration_minutes,
            # TSS doctrine: active sessions → None, rest sessions → 0.
            estimated_tss=0 if s.workout_type == "rest" else None,
            reason_codes=list(s.reason_codes),
        )
        for s in weekly_plan.sessions
    ]

    response = TrainingWeekV2Response(
        reference_date=reference_date.isoformat(),
        goal=WeekV2GoalResponse(
            goal_type=goal_type,
            race_date=race_date_v2.isoformat() if race_date_v2 else None,
            target_time_seconds=target_time_seconds,
        ),
        state=WeekV2StateResponse(
            continuity_state=weekly_target.continuity_state,
            allow_intensity=weekly_target.allow_intensity,
        ),
        weekly_target=WeekV2TargetResponse(
            target_basis=weekly_target.target_basis,
            target_km=weekly_target.target_km,
            target_duration_minutes=weekly_target.target_duration_minutes,
            session_count=weekly_target.target_sessions,
            confidence=weekly_target.confidence,
        ),
        week=WeekV2PlanResponse(
            planned_km=weekly_plan.planned_km,
            planned_duration_minutes=weekly_plan.planned_duration_minutes,
            session_count=weekly_plan.session_count,
            sessions=sessions,
        ),
    )

    return response.model_dump(mode="json")


# PR175 — GET /training/v2/cycle
# Native V2 endpoint: returns cycle calendar structure without any session
# prescription or future volume targets.  Uses PlanGoal V2 + Periodization V2
# as the sole calendar authority.  Resolves goal / anchors from the same
# canonical DB sources as /training/v2/week.
# ---------------------------------------------------------------------------

@api_router.get("/training/v2/cycle")
async def get_training_v2_cycle(user: dict = Depends(auth_user)):
    """Return the training cycle calendar structure (V2 native).

    Calendar only — no session prescription, no future WeeklyTarget.
    Uses the same canonical goal / cycle sources as /training/v2/week.
    """
    from training_v2.plan_goal import GoalType, build_plan_goal
    from training_v2.training_cycle_response import build_cycle_calendar_response

    # Closed mapping: legacy goal strings → GoalType V2
    _GOAL_MAP: dict[str, GoalType] = {
        "10K": GoalType.ten_k,
        "SEMI": GoalType.half_marathon,
        "HALF_MARATHON": GoalType.half_marathon,
        "MARATHON": GoalType.marathon,
        "5K": GoalType.five_k,
        "ULTRA": GoalType.ultra,
        "MAINTENANCE": GoalType.maintenance,
    }

    user_id = user["id"]

    # ── Single clock (same doctrine as /training/v2/week) ─────────────────
    now_utc = datetime.now(timezone.utc)
    reference_date = now_utc.date()

    # ── Goal & cycle — same canonical sources as /training/v2/week ────────
    cycle = await db.training_cycles.find_one({"user_id": user_id}, {"_id": 0})
    if not cycle:
        raise HTTPException(
            status_code=400,
            detail="No training goal defined. Use /api/training/set-goal first.",
        )

    goal_type_raw = cycle.get("goal")
    if not goal_type_raw or goal_type_raw not in GOAL_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or missing goal type: {goal_type_raw}",
        )

    start_date_raw = cycle.get("start_date")
    if not start_date_raw:
        raise HTTPException(status_code=400, detail="No start_date in training cycle.")

    # Resolve cycle_start_date (same logic as /training/v2/week)
    cycle_start_v2: Optional[date] = None
    if isinstance(start_date_raw, datetime):
        cycle_start_v2 = (
            start_date_raw.date()
            if start_date_raw.tzinfo
            else start_date_raw.replace(tzinfo=timezone.utc).date()
        )
    elif isinstance(start_date_raw, str):
        try:
            cycle_start_v2 = datetime.fromisoformat(
                start_date_raw.replace("Z", "+00:00")
            ).date()
        except (ValueError, TypeError):
            pass

    # ── Optional race metadata — same sources as /training/v2/week ────────
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})

    race_date_raw = user_goal.get("event_date") if user_goal else None
    race_date_v2: Optional[date] = None
    if isinstance(race_date_raw, datetime):
        race_date_v2 = (
            race_date_raw.date()
            if race_date_raw.tzinfo
            else race_date_raw.replace(tzinfo=timezone.utc).date()
        )
    elif isinstance(race_date_raw, str):
        try:
            race_date_v2 = datetime.fromisoformat(
                race_date_raw.replace("Z", "+00:00")
            ).date()
        except (ValueError, TypeError):
            pass

    target_time_minutes_raw = user_goal.get("target_time_minutes") if user_goal else None
    target_time_seconds: Optional[int] = None
    if (
        isinstance(target_time_minutes_raw, (int, float))
        and not isinstance(target_time_minutes_raw, bool)
        and target_time_minutes_raw > 0
    ):
        target_time_seconds = int(target_time_minutes_raw * 60)

    # ── Build PlanGoal V2 ─────────────────────────────────────────────────
    mapped_goal_type = _GOAL_MAP.get(goal_type_raw.upper() if goal_type_raw else "")
    if mapped_goal_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot map goal_type '{goal_type_raw}' to V2 GoalType.",
        )

    plan_goal = build_plan_goal(
        goal_type=mapped_goal_type,
        race_date=race_date_v2,
        created_from="user",
    )

    # ── Determine mode and pass appropriate anchor ────────────────────────
    # PlanGoal invariant: maintenance can't have race_date, so
    # plan_goal.race_date is not None ↔ race_calendar mode.
    is_race_calendar = plan_goal.race_date is not None

    if is_race_calendar:
        if cycle_start_v2 is None:
            raise HTTPException(
                status_code=400,
                detail="Could not parse start_date in training cycle (required for race_calendar mode).",
            )
        response = build_cycle_calendar_response(
            plan_goal,
            reference_date,
            race_plan_start_date=cycle_start_v2,
            target_time_seconds=target_time_seconds,
        )
    else:
        if cycle_start_v2 is None:
            raise HTTPException(
                status_code=400,
                detail="Could not parse start_date in training cycle.",
            )
        response = build_cycle_calendar_response(
            plan_goal,
            reference_date,
            cycle_anchor_date=cycle_start_v2,
            target_time_seconds=target_time_seconds,
        )

    return response.model_dump(mode="json")



    """Génère un plan de secours basé sur des templates.

    PR149 BLOCKER 1: When WeeklyTarget V2 prescribes duration-based (target_km_protected=None),
    this fallback MUST NOT invent km. It produces duration-only sessions instead.
    """
    # PR149: duration-based path — no km invention.
    target_duration_minutes = context.get("target_duration_minutes")
    if target_km_protected is None and target_duration_minutes is not None:
        # Duration-based fallback: simple easy sessions, no km.
        sessions_count = 3
        per_session = target_duration_minutes // sessions_count
        remainder = target_duration_minutes - per_session * sessions_count
        sessions = [
            {"day": "monday", "type": "rest", "duration": "0min", "details": "Récupération complète", "intensity": "rest", "estimated_tss": None, "distance_km": None},
            {"day": "tuesday", "type": "endurance", "duration": f"{per_session}min", "details": f"{per_session}min endurance facile", "intensity": "easy", "estimated_tss": None, "distance_km": None},
            {"day": "wednesday", "type": "rest", "duration": "0min", "details": "Récupération", "intensity": "rest", "estimated_tss": None, "distance_km": None},
            {"day": "thursday", "type": "endurance", "duration": f"{per_session}min", "details": f"{per_session}min endurance facile", "intensity": "easy", "estimated_tss": None, "distance_km": None},
            {"day": "friday", "type": "rest", "duration": "0min", "details": "Récupération", "intensity": "rest", "estimated_tss": None, "distance_km": None},
            {"day": "saturday", "type": "endurance", "duration": f"{per_session + remainder}min", "details": f"{per_session + remainder}min endurance facile", "intensity": "easy", "estimated_tss": None, "distance_km": None},
            {"day": "sunday", "type": "rest", "duration": "0min", "details": "Récupération", "intensity": "rest", "estimated_tss": None, "distance_km": None},
        ]
        return {
            "focus": phase,
            "planned_load": None,
            "weekly_km": None,
            "target_duration_minutes": target_duration_minutes,
            "target_basis": "duration",
            "sessions": sessions,
            "total_tss": None,
            "advice": get_phase_description(phase).get("advice", "Keep it up!")
        }

    # Distance-based fallback (legacy path — target_km_protected is set).
    weekly_km = context.get("weekly_km", DEFAULT_WEEKLY_KM)
    
    # Ajuster selon la phase
    phase_multipliers = {
        "build": 1.0,
        "deload": 0.7,
        "intensification": 1.05,
        "taper": 0.6,
        "race": 0.25
    }
    adjusted_km = weekly_km * phase_multipliers.get(phase, 1.0)

    # PR76: honour the pre-computed protected target so the fallback never
    # exceeds the resume-guard cap.
    if target_km_protected is not None:
        adjusted_km = min(adjusted_km, target_km_protected)
    
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
            {"day": "monday", "type": "rest", "duration": "0min", "details": "Récupération complète • Étirements ou yoga", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "tuesday", "type": "endurance", "duration": "30min", "details": f"5 km • {paces['z1']}/km • FC {hr_zones['z1']} bpm", "intensity": "easy", "estimated_tss": None, "distance_km": 5},
            {"day": "wednesday", "type": "rest", "duration": "0min", "details": "Récupération active • Marche ou natation légère", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "thursday", "type": "endurance", "duration": "35min", "details": f"6 km • {paces['z2']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": None, "distance_km": 6},
            {"day": "friday", "type": "rest", "duration": "0min", "details": "Récupération complète • Priorité au sommeil", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "saturday", "type": "endurance", "duration": "40min", "details": f"7 km progressif • {paces['z2']}/km → {paces['z3']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": None, "distance_km": 7},
            {"day": "sunday", "type": "rest", "duration": "0min", "details": "Récupération complète • Préparation semaine suivante", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
        ]
    elif phase == "taper":
        sessions = [
            {"day": "monday", "type": "rest", "duration": "0min", "details": "Récupération complète • Hydratation ++", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "tuesday", "type": "endurance", "duration": "30min", "details": f"5 km + 4×100m rapide • {paces['z2']}/km puis sprint • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": None, "distance_km": 5.5},
            {"day": "wednesday", "type": "rest", "duration": "0min", "details": "Récupération complète • Préparation mentale", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "thursday", "type": "tempo", "duration": "25min", "details": f"4 km dont 2 km allure course • {paces['semi']}/km • FC {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": None, "distance_km": 4},
            {"day": "friday", "type": "rest", "duration": "0min", "details": "Repos total • Préparation matériel final", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "saturday", "type": "activation", "duration": "20min", "details": f"3 km + 3×200m allure course • {paces['z2']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": None, "distance_km": 3.6},
            {"day": "sunday", "type": "rest", "duration": "0min", "details": "VEILLE DE COURSE • Repos total, glucides", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
        ]
    else:  # build, intensification
        sessions = [
            {"day": "monday", "type": "rest", "duration": "0min", "details": "Récupération complète • Étirements recommandés", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "tuesday", "type": "endurance", "duration": "50min", "details": f"8 km • {paces['z2']}/km • FC {hr_zones['z2']} bpm • Zone 2 stricte", "intensity": "easy", "estimated_tss": None, "distance_km": 8},
            {"day": "wednesday", "type": "threshold", "duration": "40min", "details": f"7 km dont 20min à {paces['z4']}/km • FC {hr_zones['z4']} bpm • 2min récup entre blocs", "intensity": "hard", "estimated_tss": None, "distance_km": 7},
            {"day": "thursday", "type": "recovery", "duration": "30min", "details": f"5 km très facile • {paces['z1']}/km • FC <{hr_zones['z1'].split('-')[1]} bpm max", "intensity": "easy", "estimated_tss": None, "distance_km": 5},
            {"day": "friday", "type": "rest", "duration": "0min", "details": "Récupération complète • Cross-training possible (vélo, natation)", "intensity": "rest", "estimated_tss": None, "distance_km": 0},
            {"day": "saturday", "type": "tempo", "duration": "45min", "details": f"8 km dont 25min à {paces['semi']}/km • FC {hr_zones['z3']} bpm • Allure semi-marathon", "intensity": "moderate", "estimated_tss": None, "distance_km": 8},
            {"day": "sunday", "type": "long_run", "duration": "70min", "details": f"12 km progressif • {paces['z2']}/km → {paces['z3']}/km • FC {hr_zones['z2']} → {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": None, "distance_km": 12},
        ]
    
    total_tss = None
    total_km = sum(s.get("distance_km", 0) for s in sessions)

    # PR76: if adjusted_km caps the total, scale all running sessions down
    # proportionally so the plan respects target_km_protected.
    if total_km > adjusted_km > 0:
        scale = adjusted_km / total_km
        for s in sessions:
            if s.get("distance_km", 0) > 0:
                s["distance_km"] = round(s["distance_km"] * scale, 1)
        total_km = sum(s.get("distance_km", 0) for s in sessions)

    return {
        "focus": phase,
        "planned_load": None,
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
async def get_subscription_status(user: dict = Depends(auth_user)):
    """Check user's subscription status"""

    user_id = user["id"]

    # Resolve tier and access via access_control (handles DEMO_MODE, expiry, fail-closed)
    user_access = await get_user_access(db, user_id)

    # Tier display name
    _tier_names = {
        Tier.FREE:    "Gratuit",
        Tier.TRIAL:   "Essai gratuit",
        Tier.PREMIUM: "Premium",
    }
    tier_name = _tier_names.get(user_access.tier, "Gratuit")

    # Expiry date string
    expires_at: Optional[str] = None
    if user_access.premium_expires_at:
        expires_at = user_access.premium_expires_at.isoformat()
    elif user_access.trial_end and user_access.is_trial:
        expires_at = user_access.trial_end.isoformat()

    # Message count for current month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    message_count = await db.chat_messages.count_documents({
        "user_id": user_id,
        "role": "user",
        "timestamp": {"$gte": month_start.isoformat()},
    })

    messages_limit = user_access.chat_monthly_quota if user_access.chat_monthly_quota is not None else 999
    is_unlimited = user_access.is_unlimited_chat

    return SubscriptionStatusResponse(
        tier=user_access.tier.value,
        tier_name=tier_name,
        is_premium=user_access.has_premium_access,
        subscription_id=user_access.paddle_subscription_id,
        expires_at=expires_at,
        messages_used=message_count,
        messages_limit=messages_limit,
        messages_remaining=max(0, messages_limit - message_count) if not is_unlimited else 999,
        is_unlimited=is_unlimited,
    )


# Keep old endpoint for backward compatibility
@api_router.get("/premium/status")
async def get_premium_status(user: dict = Depends(auth_user)):
    """Check if user has active premium subscription (backward compat)"""
    user_id = user["id"]
    status = await get_subscription_status(user)
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


@api_router.get("/user/features")
async def get_user_features(user: dict = Depends(auth_user)):
    """
    Returns the current user's subscription tier and per-feature access flags.

    The frontend uses this response to decide which features to blur/lock and
    whether to show the Paddle upgrade CTA.  Access enforcement always happens
    server-side; this endpoint is display-only.

    Response shape:
        {
            "plan": "free" | "trial" | "premium",
            "trial_active": bool,
            "has_premium_access": bool,
            "trial_days_remaining": int | null,
            "feature_access": { "<feature>": bool, ... }
        }
    """
    user_id = user["id"]
    user_access = await get_user_access(db, user_id)
    api_dict = user_access.to_api_dict()

    return {
        "plan": api_dict["subscription_status"],
        "trial_active": api_dict["is_trial"],
        "has_premium_access": api_dict["has_premium_access"],
        "trial_days_remaining": api_dict["trial_days_remaining"],
        "feature_access": api_dict["feature_access"],
    }



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
async def send_chat_message(request: ChatRequest, user: dict = Depends(auth_user)):
    """Send a message to the chat coach (with tier-based limits)"""
    user_id = user["id"]

    # ── Access control via the single source of truth ────────────────────────
    # access_control.get_user_access() handles all legacy statuses, expiration
    # checks, DEMO_MODE, DB errors (fail-closed), and the canonical tier model.
    user_access = await get_user_access(db, user_id)
    tier = user_access.tier

    is_unlimited = user_access.is_unlimited_chat
    messages_limit = user_access.chat_monthly_quota or CHAT_QUOTA_FREE  # int for FREE tier

    # Get message count for current month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    message_count = await db.chat_messages.count_documents({
        "user_id": user_id,
        "role": "user",
        "timestamp": {"$gte": month_start.isoformat()}
    })

    # Check limit; apply anti-abuse hard cap for unlimited tiers
    if message_count >= messages_limit:
        if is_unlimited and message_count < CHAT_ANTIABUSE_CAP:
            pass  # Unlimited tier — allow but anti-abuse cap still active
        else:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"You've reached your monthly limit of {messages_limit} messages. "
                    "Upgrade to Premium to continue."
                ),
            )

    # Get user's recent workouts for context
    workouts = await db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(50)
    
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
async def get_chat_history(user: dict = Depends(auth_user), limit: int = 50):
    """Get chat history for a user"""
    
    user_id = user["id"]
    messages = await db.chat_messages.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    # Reverse to chronological order
    messages.reverse()
    
    return messages


@api_router.delete("/chat/history")
async def clear_chat_history(user: dict = Depends(auth_user)):
    """Clear chat history for a user"""
    
    user_id = user["id"]
    result = await db.chat_messages.delete_many({"user_id": user_id})
    
    logger.info(f"Chat history cleared for user {user_id}: {result.deleted_count} messages")
    
    return {"success": True, "deleted_count": result.deleted_count}


@api_router.get("/cache/stats")
async def get_coach_cache_stats():
    """Get coach service cache statistics"""
    return get_cache_stats()


@api_router.delete("/cache/clear")
async def clear_coach_cache(_admin: dict = Depends(require_admin)):
    """Clear all coach service caches. Admin only."""
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
async def reset_service_metrics(_admin: dict = Depends(require_admin)):
    """Reset coach service metrics. Admin only."""
    old_metrics = reset_coach_metrics()
    logger.info(f"Metrics reset. Previous: {old_metrics}")
    return {"success": True, "previous": old_metrics}


# ========== SUBSCRIPTION SYSTEM ==========

class SubscriptionInfo(BaseModel):
    """Informations d'abonnement utilisateur"""
    user_id: str
    status: str  # trial, free, premium
    display: Dict
    features: Dict
    trial_days_remaining: Optional[int] = None
    price_locked: Optional[float] = None


@api_router.get("/subscription/info")
async def get_subscription_info(user: dict = Depends(auth_user), language: str = "en"):
    """
    Retrieves complete subscription information for a user.

    Returns:
    - status: trial, free, premium
    - display: Localized UI texts
    - features: Accessible features
    - trial_days_remaining: Remaining days if in trial
    """
    user_id = user["id"]

    # Use access_control as single source of truth for tier resolution
    user_access = await get_user_access(db, user_id)

    # Also fetch raw subscription doc for display fields (price_locked, etc.)
    subscription = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0}) or {}

    status = user_access.tier.value

    return {
        "user_id": user_id,
        "status": status,
        "display": get_subscription_display(subscription, language),
        "features": FEATURES.get(status, FEATURES[SubscriptionStatus.FREE]),
        "trial_days_remaining": user_access.trial_days_remaining,
        "price_locked": subscription.get("price_locked"),
        "created_at": subscription.get("created_at"),
        "activated_at": subscription.get("activated_at"),
    }


@api_router.post("/subscription/cancel")
async def cancel_user_subscription(user: dict = Depends(auth_user)):
    """
    Annule l'abonnement d'un utilisateur.
    Le statut passe à 'free'.
    """
    user_id = user["id"]
    subscription = await cancel_subscription(db, user_id)
    
    return {
        "success": True,
        "status": subscription.get("status"),
        "message": "Abonnement annulé"
    }


def _dev_endpoint_guard() -> None:
    """Raise 404 when accessed in production. DEV/TEST-only endpoints."""
    env = os.getenv("ENVIRONMENT", "development").strip().lower()
    if env == "production":
        raise HTTPException(status_code=404, detail="Not Found")


@api_router.post("/subscription/simulate-trial-end")
async def simulate_trial_end(user: dict = Depends(auth_user)):
    """
    [DEV ONLY] Simulate end of free trial to test paywall.

    Unavailable in production (returns 404 when ENVIRONMENT=production).
    """
    _dev_endpoint_guard()
    user_id = user["id"]
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
async def reset_to_trial(user: dict = Depends(auth_user)):
    """
    [DEV ONLY] Reset user to free trial.

    Unavailable in production (returns 404 when ENVIRONMENT=production).
    """
    _dev_endpoint_guard()
    user_id = user["id"]
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)

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


@api_router.post("/subscription/start-trial")
async def start_free_trial(user: dict = Depends(auth_user)):
    """
    Activate a 30-day free trial for the authenticated Free user.

    No credit card, no Paddle/Stripe checkout. Identity comes strictly from the
    JWT (user["id"]) — never from the request body. A user can only ever start
    one trial: a second attempt (or an already trial/premium user) is refused.
    """
    user_id = user["id"]

    # get_user_subscription creates a FREE subscription if none exists and
    # lazily persists trial/premium expiration.
    subscription = await get_user_subscription(db, user_id)

    if subscription.get("trial_used"):
        raise HTTPException(status_code=409, detail="Trial already used")
    if subscription.get("status") in (SubscriptionStatus.TRIAL, SubscriptionStatus.PREMIUM):
        raise HTTPException(status_code=409, detail="An active plan already exists")

    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)

    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.TRIAL,
                "trial_start": now.isoformat(),
                "trial_end": trial_end.isoformat(),
                "trial_used": True,
                "updated_at": now.isoformat(),
            }
        },
    )

    return {
        "success": True,
        "status": SubscriptionStatus.TRIAL,
        "trial_end": trial_end.isoformat(),
    }



class PaddleCheckoutRequest(BaseModel):
    price_id: Optional[str] = None


class PaddleCheckoutResponse(BaseModel):
    transaction_id: str
    paddle_environment: str
    paddle_client_token: str
    price_id: str


@api_router.post("/subscription/paddle/checkout", response_model=PaddleCheckoutResponse)
async def create_paddle_checkout(
    request: PaddleCheckoutRequest,
    http_request: Request,
    user: dict = Depends(auth_user),
):
    """
    Create a Paddle transaction for the authenticated user.

    Returns a transaction_id that the frontend passes to
    ``Paddle.Checkout.open({ transactionId })`` to display the checkout overlay.

    The price defaults to PADDLE_PRICE_ID (Premium 4.99 EUR/month).

    Security:
    - user_id is ALWAYS taken from the JWT token, never from the request body.
    - Premium is only activated server-side after the Paddle webhook is verified.
    - The frontend MUST NOT interpret the transaction creation as a grant of access.
    """
    if not PADDLE_API_KEY:
        raise HTTPException(status_code=503, detail="Paddle not configured on this server")
    if not PADDLE_PRICE_ID and not request.price_id:
        raise HTTPException(status_code=503, detail="Paddle price ID not configured")

    user_id = user["id"]
    price_id = request.price_id or PADDLE_PRICE_ID

    # Resolve existing Paddle customer_id if available, so Paddle pre-fills the
    # checkout form for returning subscribers.
    subscription = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    paddle_customer_id: Optional[str] = None
    if subscription:
        paddle_customer_id = subscription.get("paddle_customer_id")

    # Build the transaction payload
    transaction_payload: Dict = {
        "items": [{"price_id": price_id, "quantity": 1}],
        "custom_data": {"user_id": user_id},
    }
    if paddle_customer_id:
        transaction_payload["customer_id"] = paddle_customer_id

    headers = {
        "Authorization": f"Bearer {PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{PADDLE_API_BASE}/transactions",
                json=transaction_payload,
                headers=headers,
                timeout=15.0,
            )
        if resp.status_code not in (200, 201):
            logger.error(
                f"[Paddle] Transaction creation failed for user '{user_id}': "
                f"HTTP {resp.status_code} — {resp.text[:500]}"
            )
            raise HTTPException(
                status_code=502,
                detail="Failed to create Paddle transaction. Please try again.",
            )
        data = resp.json()
        transaction_id: str = data["data"]["id"]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[Paddle] Unexpected error creating transaction for '{user_id}': {exc}")
        raise HTTPException(status_code=500, detail="Internal error during checkout setup")

    # Record the pending transaction for idempotence / audit trail
    await db.payment_transactions.insert_one({
        "transaction_id": transaction_id,
        "user_id": user_id,
        "price_id": price_id,
        "provider": "paddle",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    logger.info(f"[Paddle] Created transaction '{transaction_id}' for user '{user_id}'")

    return PaddleCheckoutResponse(
        transaction_id=transaction_id,
        paddle_environment=PADDLE_ENVIRONMENT,
        paddle_client_token=PADDLE_CLIENT_TOKEN,
        price_id=price_id,
    )


@api_router.get("/subscription/paddle/config")
async def get_paddle_config():
    """
    Returns Paddle.js client-side configuration (safe for the browser).

    The frontend calls this once at startup to initialize Paddle.js with the
    correct environment and client token.
    """
    return {
        "paddle_environment": PADDLE_ENVIRONMENT,
        "paddle_client_token": PADDLE_CLIENT_TOKEN,
        "price_id": PADDLE_PRICE_ID,
        "configured": bool(PADDLE_CLIENT_TOKEN and PADDLE_PRICE_ID),
    }


@api_router.post("/webhook/paddle")
async def paddle_webhook(request: Request):
    """
    Handle Paddle Billing webhook notifications.

    Security:
    - Raw body is read before any parsing so the HMAC-SHA256 digest covers
      exactly what Paddle signed.
    - Signature is verified with `verify_and_parse_paddle_event()` before any
      DB mutation.
    - All subscription mutations go through subscription_manager helpers,
      which are then surfaced via access_control.get_user_access() — the
      single source of truth.
    - Idempotence: events are deduplicated on their `event_id`.

    Supported Paddle Billing event types:
        subscription.activated   → activate_premium()
        subscription.updated     → renew_premium() (renewal / plan update)
        subscription.cancelled   → cancel_subscription()
        subscription.past_due    → log warning (access expires naturally)
        transaction.completed    → fallback for one-time or initial payment
        transaction.payment_failed → log warning (access will lapse at expiry)
    """
    body = await request.body()
    paddle_sig = request.headers.get("Paddle-Signature", "")

    if not PADDLE_WEBHOOK_SECRET:
        logger.error("[Paddle] PADDLE_WEBHOOK_SECRET is not set — rejecting webhook")
        raise HTTPException(status_code=500, detail="Paddle webhook secret not configured")

    try:
        event = verify_and_parse_paddle_event(body, paddle_sig, PADDLE_WEBHOOK_SECRET)
    except PaddleWebhookError as exc:
        logger.warning(f"[Paddle] Webhook verification failed: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))

    event_id   = event.get("event_id") or event.get("id", "")
    event_type = event.get("event_type", "")
    data       = event.get("data", {})

    logger.info(f"[Paddle] Webhook received: event_type={event_type!r} event_id={event_id!r}")

    # ── Idempotence guard ────────────────────────────────────────────────────
    if event_id:
        existing = await db.paddle_events.find_one({"event_id": event_id})
        if existing:
            logger.info(f"[Paddle] Duplicate event_id={event_id!r} — skipping")
            return {"received": True, "status": "duplicate"}
        # Record before processing to prevent double-activation in case of
        # retry arriving before DB write completes (best-effort idempotence).
        await db.paddle_events.insert_one({
            "event_id": event_id,
            "event_type": event_type,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        })

    # ── Helper: extract user_id from custom_data ─────────────────────────────
    def _user_id_from_event(evt_data: dict) -> Optional[str]:
        """Extract user_id embedded by the backend when creating the transaction."""
        custom = (
            evt_data.get("custom_data")
            or (evt_data.get("items") or [{}])[0].get("custom_data")
            or {}
        )
        if isinstance(custom, dict):
            return custom.get("user_id")
        return None

    # ── Helper: parse ISO datetime safely ────────────────────────────────────
    def _parse_paddle_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # subscription.activated
    # Fired when a subscription's status becomes "active" (typically after the
    # first payment is processed).
    # ─────────────────────────────────────────────────────────────────────────
    if event_type == "subscription.activated":
        user_id              = _user_id_from_event(data)
        paddle_sub_id        = data.get("id")
        paddle_customer_id   = data.get("customer_id")
        next_billed_at       = _parse_paddle_dt(data.get("next_billed_at"))

        if not user_id:
            logger.warning("[Paddle] subscription.activated — missing user_id in custom_data")
            return {"received": True, "status": "no_user_id"}

        from subscription_manager import activate_premium
        await activate_premium(
            db,
            user_id,
            paddle_subscription_id=paddle_sub_id,
            paddle_customer_id=paddle_customer_id,
            premium_expires_at=next_billed_at,
        )
        logger.info(
            f"[Paddle] PREMIUM activated for user '{user_id}' "
            f"(sub={paddle_sub_id}, next_billed={next_billed_at})"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # subscription.updated
    # Covers renewals, plan changes, and reactivations after past_due recovery.
    # ─────────────────────────────────────────────────────────────────────────
    elif event_type == "subscription.updated":
        user_id            = _user_id_from_event(data)
        paddle_sub_id      = data.get("id")
        new_status         = (data.get("status") or "").lower()
        next_billed_at     = _parse_paddle_dt(data.get("next_billed_at"))
        paddle_customer_id = data.get("customer_id")

        if not user_id:
            logger.warning("[Paddle] subscription.updated — missing user_id in custom_data")
            return {"received": True, "status": "no_user_id"}

        if new_status in ("active", "trialing"):
            from subscription_manager import renew_premium
            if next_billed_at:
                await renew_premium(db, user_id, paddle_sub_id, next_billed_at)
            else:
                # Renewal without a known next billing date — keep premium, reset expiry
                from subscription_manager import activate_premium
                await activate_premium(
                    db, user_id,
                    paddle_subscription_id=paddle_sub_id,
                    paddle_customer_id=paddle_customer_id,
                )
            logger.info(
                f"[Paddle] PREMIUM renewed for user '{user_id}' until {next_billed_at}"
            )
        elif new_status == "cancelled":
            from subscription_manager import cancel_subscription
            await cancel_subscription(db, user_id)
            logger.info(f"[Paddle] Subscription cancelled for user '{user_id}'")
        else:
            logger.info(
                f"[Paddle] subscription.updated status={new_status!r} for user '{user_id}' — no action"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # subscription.cancelled
    # The user or Paddle has cancelled the subscription.
    # ─────────────────────────────────────────────────────────────────────────
    elif event_type == "subscription.cancelled":
        user_id = _user_id_from_event(data)
        if not user_id:
            logger.warning("[Paddle] subscription.cancelled — missing user_id in custom_data")
            return {"received": True, "status": "no_user_id"}

        from subscription_manager import cancel_subscription
        await cancel_subscription(db, user_id)
        logger.info(f"[Paddle] Subscription cancelled for user '{user_id}'")

    # ─────────────────────────────────────────────────────────────────────────
    # subscription.past_due
    # Payment failed; Paddle will retry. We do NOT immediately revoke access —
    # access naturally lapses when premium_expires_at passes.
    # ─────────────────────────────────────────────────────────────────────────
    elif event_type == "subscription.past_due":
        user_id = _user_id_from_event(data)
        logger.warning(
            f"[Paddle] subscription.past_due for user '{user_id}' "
            f"— access will lapse at premium_expires_at"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # transaction.completed
    # Fired for every completed payment (including the initial one for a
    # subscription). Used as a fallback if subscription.activated is delayed.
    # ─────────────────────────────────────────────────────────────────────────
    elif event_type == "transaction.completed":
        user_id            = _user_id_from_event(data)
        paddle_sub_id      = data.get("subscription_id")
        paddle_customer_id = data.get("customer_id")
        transaction_id     = data.get("id")

        if user_id and paddle_sub_id:
            # Only activate if there is an associated subscription
            from subscription_manager import activate_premium
            await activate_premium(
                db,
                user_id,
                paddle_subscription_id=paddle_sub_id,
                paddle_customer_id=paddle_customer_id,
            )
            logger.info(
                f"[Paddle] transaction.completed → PREMIUM for user '{user_id}' "
                f"(txn={transaction_id})"
            )

        # Update transaction status in our DB
        if transaction_id:
            await db.payment_transactions.update_one(
                {"transaction_id": transaction_id},
                {
                    "$set": {
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "paddle_customer_id": paddle_customer_id,
                    }
                },
            )

    # ─────────────────────────────────────────────────────────────────────────
    # transaction.payment_failed
    # ─────────────────────────────────────────────────────────────────────────
    elif event_type == "transaction.payment_failed":
        user_id        = _user_id_from_event(data)
        transaction_id = data.get("id")
        logger.warning(
            f"[Paddle] transaction.payment_failed for user '{user_id}' txn={transaction_id}"
        )
        if transaction_id:
            await db.payment_transactions.update_one(
                {"transaction_id": transaction_id},
                {"$set": {"status": "payment_failed", "updated_at": datetime.now(timezone.utc).isoformat()}},
            )

    else:
        logger.info(f"[Paddle] Unhandled event type: {event_type!r}")

    return {"received": True}
from api.garmin import garmin_router
api_router.include_router(garmin_router)

# Register authentication endpoints under /api/auth/*
api_router.include_router(auth_router)

# Register OAuth authentication endpoints under /api/auth/google and /api/auth/apple
api_router.include_router(oauth_router)

# Register admin endpoints under /api/admin/*
api_router.include_router(admin_router)

# Include the router
app.include_router(api_router)

# Include the physiological engine dashboard router
app.include_router(dashboard_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_compute_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _ensure_subscriptions_unique_index(db_handle) -> None:
    """Thin wrapper — delegates to the testable service module."""
    from services.subscription_index import ensure_subscriptions_unique_index
    await ensure_subscriptions_unique_index(db_handle)


@app.on_event("startup")
async def create_db_indexes():
    """Create MongoDB indexes for common query patterns"""
    validate_environment_configuration()
    validate_demo_mode_safety()
    log_demo_mode_status()
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
        # Subscriptions: enforce 1 document per user.
        # Idempotent: if a non-unique index on user_id already exists (legacy),
        # drop it first so we can (re)create it as UNIQUE without error.
        await _ensure_subscriptions_unique_index(db)
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
        # Garmin Trial Registry — enforces "1 Garmin = 1 Trial" atomically.
        # The unique index on garmin_identity prevents concurrent race conditions:
        # only the first insert (via find_one_and_update $setOnInsert) succeeds.
        # BLOCKER: this collection will remain empty until the Garmin multi-user
        # identity architecture provides a stable per-user garmin_identity.
        await db.garmin_trial_registry.create_index(
            "garmin_identity", unique=True, sparse=False
        )
        # Users collection (auth system)
        await db.users.create_index("email", unique=True)
        await db.users.create_index("id", unique=True)
        await db.users.create_index("reset_password_token_hash", sparse=True)
        await db.auth_identities.create_index(
            [("provider", 1), ("provider_subject", 1)],
            unique=True,
        )
        await db.auth_identities.create_index("user_id")
        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Could not create some MongoDB indexes: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

from services.run_index_history import get_run_index_history_payload, upsert_run_index_snapshot, load_garmin_domain_activities
from fastapi import FastAPI, APIRouter, HTTPException, Query, Request, Depends, Header
from fastapi.responses import RedirectResponse, JSONResponse
from middleware import SSEAwareGZipMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Auth module — JWT-based multi-user identity
from auth.router import auth_router
from auth.oauth_router import oauth_router
from auth.dependencies import get_current_user, require_admin
from auth.jwt_utils import decode_access_token
from auth.mongo_errors import DuplicateKeyError
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
from datetime import date, datetime, timezone, timedelta
from config.secrets import MissingSecretError
import localization
try:
    from pymongo import ReturnDocument
except Exception:  # pragma: no cover - lightweight fallback
    class ReturnDocument:  # type: ignore[no-redef]
        BEFORE = "before"
        AFTER = "after"

# Import the analysis engine (NO LLM dependencies)
from analysis_engine import (
    generate_session_analysis,
    generate_weekly_review,
    generate_dashboard_insight,
)

# Import LLM coach module
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

from training_v2.training_load import build_training_load
from training_v2.training_history import RUNNING_TYPES, build_training_history
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
from training_v2.today_prescription import resolve_today_final_prescription
from training_v2.workout_generator import WorkoutPrescription
from training_v2.training_week_response import TrainingWeekV2Response  # PR167
from training_v2.daily_runtime_helpers import (
    BAND_TO_RECOMMENDATION,
    runtime_session_to_prescription,
    prescription_to_runtime_session,
)
from garmin.readiness_adapter import build_readiness_v2_from_garmin_data
from garmin.domain_adapter import mongo_garmin_activities_to_domain
from garmin.sync_progress import get_sync_progress
from training_v2.performance_model import predict_races, activity_date  # PR185
from training_v2.plan_goal import GoalType

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
from engine.run_index_engine import calculate_run_index, calculate_run_index_from_domain


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

_LEGACY_GOAL_TO_V2: dict[str, GoalType] = {
    "10K": GoalType.ten_k,
    "SEMI": GoalType.half_marathon,
    "HALF_MARATHON": GoalType.half_marathon,
    "MARATHON": GoalType.marathon,
    "5K": GoalType.five_k,
    "ULTRA": GoalType.ultra,
    "MAINTENANCE": GoalType.maintenance,
}

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


def get_rate_limit_key_from_request(request: Request) -> str:
    """Return a technical key used exclusively for rate limiting.

    Resolution order:
    1. JWT sub claim — if a valid JWT is present.
    2. X-Forwarded-For / client IP — anonymous fallback.

    IMPORTANT: the returned value is only suitable as a rate-limit bucket key.
    It MUST NOT be used as a user_id, subscription identity, or passed to
    get_user_access().  An IP address is never a user identity.
    """
    # 1. Try JWT first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        try:
            payload = decode_access_token(token)
            sub = payload.get("sub")
            if sub:
                return sub
        except Exception:
            pass  # Fall through to IP-based key

    # 2. Fallback to IP (acceptable only for rate limiting)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_jwt_user_id_from_request(request: Request) -> Optional[str]:
    """Extract the authenticated user_id exclusively from a valid JWT.

    Returns the JWT ``sub`` claim when a valid, non-expired ****** is
    present.  Returns ``None`` in every other case:
      - no Authorization header
      - malformed / expired / invalid token
      - token present but ``sub`` claim missing

    This function NEVER falls back to an IP address or any other pseudo-identity.
    It is the only safe source of identity for subscription / access-control
    decisions.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):]
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        return sub if sub else None
    except Exception:
        return None


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
    
    user_id = get_rate_limit_key_from_request(request)
    
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

    # Premium route — verify user's subscription tier.
    # Identity MUST come from a valid JWT; an IP address is never a user identity.
    user_id = get_jwt_user_id_from_request(request)

    if not user_id:
        # No valid JWT (absent, expired, or invalid) → 401 before any DB access.
        # get_user_access() is NOT called, so no subscription document is created.
        logger.info(f"[Subscription] Unauthenticated request to premium route '{path}' — 401")
        return JSONResponse(
            status_code=401,
            content={
                "error": "authentication_required",
                "message": "Authentication required",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

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

# Distance types with km values — aligned with plan_goal.py V2 canonical constants.
# PR226: semi aligned to 21.0975 (V2 constant); ultra hardcode removed (must be explicit).
DISTANCE_TYPES = {
    "5k": 5.0,
    "10k": 10.0,
    "semi": 21.0975,   # canonical: plan_goal.DISTANCE_HALF_MARATHON_KM
    "marathon": 42.195,
    # "ultra" intentionally absent — distance must be supplied explicitly (> 42.195)
}

# All valid distance_type values — derived from DISTANCE_TYPES plus "ultra"
# so there is a single source of truth for what types are allowed.
_VALID_DISTANCE_TYPES: frozenset[str] = frozenset(DISTANCE_TYPES.keys()) | {"ultra"}

# Goal→distance_type coherence map (upper-case legacy goal → canonical distance_type key)
_GOAL_TO_DISTANCE_TYPE: dict[str, str] = {
    "5K": "5k",
    "10K": "10k",
    "SEMI": "semi",
    "MARATHON": "marathon",
    "ULTRA": "ultra",
    # MAINTENANCE has no distance_type
}


def calculate_target_pace(distance_km: float, target_time_minutes: int) -> str:
    """Calculate target pace in min/km format"""
    if distance_km <= 0 or target_time_minutes <= 0:
        return None
    pace_minutes = target_time_minutes / distance_km
    pace_min = int(pace_minutes)
    pace_sec = int((pace_minutes - pace_min) * 60)
    return f"{pace_min}:{pace_sec:02d}"


def _validate_target_time_minutes(value: Optional[object]) -> Optional[int]:
    """Validate target_time_minutes input for POST /user/goal."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(
            status_code=400,
            detail="target_time_minutes must be a positive number when provided.",
        )
    if value <= 0:
        raise HTTPException(
            status_code=400,
            detail="target_time_minutes must be strictly greater than 0 when provided.",
        )
    if isinstance(value, float) and not value.is_integer():
        raise HTTPException(
            status_code=400,
            detail="target_time_minutes must be a whole number of minutes when provided.",
        )
    return int(value)


# PR226 — single place for ULTRA distance validation so future threshold or
# error-message changes only need one edit.
_ULTRA_MIN_DISTANCE_KM: float = 42.195


def _validate_ultra_distance_km(distance_km: Optional[float]) -> float:
    """Return validated ultra distance or raise HTTP 400.

    Raises:
        HTTPException(400): when distance_km is absent, non-numeric, or ≤ 42.195.
    """
    if (
        distance_km is None
        or not isinstance(distance_km, (int, float))
        or isinstance(distance_km, bool)
        or distance_km <= _ULTRA_MIN_DISTANCE_KM
    ):
        raise HTTPException(
            status_code=400,
            detail=f"ULTRA goal requires distance_km > {_ULTRA_MIN_DISTANCE_KM} km.",
        )
    return float(distance_km)


# ---------------------------------------------------------------------------
# PR226 — Canonical goal resolver
# Single function that reads training_cycles + user_goals and returns all
# fields needed by /training/v2/week, /training/v2/cycle, /training/week-plan.
# Incoherent legacy data → explicit 400, never silently combined.
# ---------------------------------------------------------------------------

class _ResolvedGoal:
    """Immutable bag of resolved goal fields returned by _resolve_goal_v2."""
    __slots__ = (
        "goal_type",       # str, e.g. "MARATHON"
        "mapped_goal",     # GoalType V2 enum
        "cycle_start",     # date | None
        "race_date",       # date | None  (always None for MAINTENANCE)
        "target_time_sec", # int | None   (always None for MAINTENANCE)
        "target_distance_km",  # float | None (ULTRA only)
        "cycle_doc",       # raw training_cycles document
        "user_goal_doc",   # raw user_goals document | None
    )

    def __init__(self, **kw):
        for k, v in kw.items():
            object.__setattr__(self, k, v)


async def _resolve_goal_v2(user_id: str) -> "_ResolvedGoal":
    """Resolve goal truth from canonical DB sources for V2 endpoints.

    Reads ``training_cycles`` (authoritative goal type) and ``user_goals``
    (optional race metadata).  Validates coherence; raises ``HTTPException``
    on any inconsistency so callers never receive silently combined bad data.

    Rules
    -----
    - No cycle            → HTTP 400
    - Unknown goal type   → HTTP 400
    - MAINTENANCE         → race_date=None, target_time_sec=None always
    - ULTRA + no distance → HTTP 400
    - user_goals present but distance_type mismatches cycle.goal → HTTP 400
    """
    from training_v2.plan_goal import GoalType as _GT, ULTRA_MIN_DISTANCE_KM as _ULTRA_MIN

    cycle = await db.training_cycles.find_one({"user_id": user_id}, {"_id": 0})
    if not cycle:
        raise HTTPException(
            status_code=400,
            detail="No training goal defined. Use /api/training/set-goal first.",
        )

    goal_type = (cycle.get("goal") or "").upper()
    if not goal_type or goal_type not in GOAL_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or missing goal type: '{goal_type}'.",
        )

    mapped_goal = _LEGACY_GOAL_TO_V2.get(goal_type)
    if mapped_goal is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot map goal type '{goal_type}' to V2 GoalType.",
        )

    start_raw = cycle.get("start_date")
    if not start_raw:
        raise HTTPException(
            status_code=400,
            detail="Training cycle has no start_date. Re-set your goal via /api/training/set-goal.",
        )
    cycle_start: Optional[date] = None
    if isinstance(start_raw, datetime):
        cycle_start = start_raw.date() if start_raw.tzinfo else start_raw.replace(tzinfo=timezone.utc).date()
    elif isinstance(start_raw, str):
        try:
            cycle_start = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            pass
    if cycle_start is None:
        raise HTTPException(
            status_code=400,
            detail=f"Training cycle start_date '{start_raw}' is not a valid date. Re-set your goal.",
        )

    user_goal_doc = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})

    # Coherence: if a user_goal exists, its distance_type must match the cycle goal.
    if user_goal_doc:
        dist_type = user_goal_doc.get("distance_type", "")
        expected = _GOAL_TO_DISTANCE_TYPE.get(goal_type)
        if expected and dist_type != expected:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Incoherent goal data: cycle goal is '{goal_type}' but "
                    f"user_goal.distance_type is '{dist_type}' (expected '{expected}'). "
                    "Update your goal via /api/training/set-goal."
                ),
            )

    # MAINTENANCE: race metadata is always None — never expose stale data.
    if mapped_goal == _GT.maintenance:
        return _ResolvedGoal(
            goal_type=goal_type,
            mapped_goal=mapped_goal,
            cycle_start=cycle_start,
            race_date=None,
            target_time_sec=None,
            target_distance_km=None,
            cycle_doc=cycle,
            user_goal_doc=user_goal_doc,
        )

    # Race metadata from user_goals (optional).
    race_date: Optional[date] = None
    if user_goal_doc:
        rd_raw = user_goal_doc.get("event_date")
        if isinstance(rd_raw, str) and rd_raw.strip() == "":
            rd_raw = None
        if rd_raw is not None:
            if isinstance(rd_raw, datetime):
                race_date = rd_raw.date() if rd_raw.tzinfo else rd_raw.replace(tzinfo=timezone.utc).date()
            elif isinstance(rd_raw, str):
                try:
                    race_date = datetime.fromisoformat(rd_raw.replace("Z", "+00:00")).date()
                except (ValueError, TypeError):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"user_goal.event_date '{rd_raw}' is not a valid ISO date. "
                            "Update your goal via /api/user/goal."
                        ),
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"user_goal.event_date has unexpected type '{type(rd_raw).__name__}'. Update your goal.",
                )

    target_time_sec: Optional[int] = None
    if user_goal_doc:
        ttm = user_goal_doc.get("target_time_minutes")
        if isinstance(ttm, (int, float)) and not isinstance(ttm, bool) and ttm > 0:
            target_time_sec = int(ttm * 60)

    # ULTRA: resolve target_distance_km (user_goals.distance_km → cycle fallback).
    target_distance_km: Optional[float] = None
    if mapped_goal == _GT.ultra:
        raw_dist = user_goal_doc.get("distance_km") if user_goal_doc else None
        if not (isinstance(raw_dist, (int, float)) and not isinstance(raw_dist, bool) and raw_dist > _ULTRA_MIN):
            raw_dist = cycle.get("ultra_distance_km")
        if not (isinstance(raw_dist, (int, float)) and not isinstance(raw_dist, bool) and raw_dist > _ULTRA_MIN):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"ULTRA goal requires target_distance_km > {_ULTRA_MIN} km. "
                    "Set your goal distance via /api/user/goal or "
                    "/api/training/set-goal?goal=ULTRA&distance_km=<km>."
                ),
            )
        target_distance_km = float(raw_dist)

    return _ResolvedGoal(
        goal_type=goal_type,
        mapped_goal=mapped_goal,
        cycle_start=cycle_start,
        race_date=race_date,
        target_time_sec=target_time_sec,
        target_distance_km=target_distance_km,
        cycle_doc=cycle,
        user_goal_doc=user_goal_doc,
    )


class UserGoal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    event_name: Optional[str] = None
    event_date: Optional[str] = None  # ISO date string
    distance_type: str  # 5k, 10k, semi, marathon, ultra
    distance_km: float  # Actual distance in km
    target_time_minutes: Optional[int] = None  # Target time in minutes
    target_pace: Optional[str] = None  # Calculated pace min/km
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class UserGoalCreate(BaseModel):
    event_name: Optional[str] = None
    event_date: Optional[str] = None
    distance_type: str  # 5k, 10k, semi, marathon, ultra
    target_time_minutes: Optional[int | float | str | bool] = None  # validated manually in set_user_goal
    distance_km: Optional[float] = None  # PR226: explicit distance for ultra (must be > 42.195)


@api_router.get("/user/goal")
async def get_user_goal(user: dict = Depends(auth_user)):
    """Get user's current goal"""
    user_id = user["id"]
    goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    return goal


@api_router.post("/user/goal")
async def set_user_goal(goal: UserGoalCreate, user: dict = Depends(auth_user)):
    """Set user's goal (event metadata optional, target time optional).

    PR226 rules (all checked BEFORE any DB mutation):
    - MAINTENANCE cycle → rejected (no race metadata on a maintenance cycle)
    - event_date is optional; if provided it must be a parseable future ISO date
    - distance_type must be valid
    - ULTRA requires distance_km > 42.195
    - distance_type must match active training_cycles.goal (coherence check)
    """
    user_id = user["id"]

    # ── 1. Validate inputs BEFORE touching the DB ──────────────────────────

    event_name = goal.event_name.strip() if isinstance(goal.event_name, str) else None
    if event_name == "":
        event_name = None

    raw_event_date = goal.event_date.strip() if isinstance(goal.event_date, str) else None
    if raw_event_date == "":
        raw_event_date = None

    parsed_event_date: Optional[date] = None
    if raw_event_date is not None:
        # event_date: must be exactly YYYY-MM-DD — no suffixes, no trailing garbage.
        import re as _re
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_event_date):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event_date '{raw_event_date}'. Must be exactly YYYY-MM-DD.",
            )
        try:
            parsed_event_date = date.fromisoformat(raw_event_date)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event_date '{raw_event_date}'. Must be ISO format YYYY-MM-DD.",
            )
        if parsed_event_date <= datetime.now(timezone.utc).date():
            raise HTTPException(
                status_code=400,
                detail=f"event_date '{raw_event_date}' must be a future date.",
            )

    if goal.distance_type not in _VALID_DISTANCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid distance_type '{goal.distance_type}'. Must be one of {sorted(_VALID_DISTANCE_TYPES)}.",
        )

    if goal.distance_type == "ultra":
        distance_km = _validate_ultra_distance_km(goal.distance_km)
    else:
        distance_km = DISTANCE_TYPES[goal.distance_type]
    validated_target_time_minutes = _validate_target_time_minutes(goal.target_time_minutes)

    # ── 2. Coherence: distance_type must match active training_cycles.goal ──
    cycle = await db.training_cycles.find_one({"user_id": user_id}, {"_id": 0})
    if cycle:
        active_goal = (cycle.get("goal") or "").upper()
        # MAINTENANCE cycles must never receive race metadata
        if active_goal == "MAINTENANCE":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot set race goal while training cycle is MAINTENANCE. "
                    "Change your training cycle first via /api/training/set-goal."
                ),
            )
        expected_dist_type = _GOAL_TO_DISTANCE_TYPE.get(active_goal)
        if expected_dist_type and goal.distance_type != expected_dist_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Incoherent goal: training cycle is '{active_goal}' "
                    f"but user_goal.distance_type is '{goal.distance_type}' "
                    f"(expected '{expected_dist_type}'). "
                    "Change your training cycle goal first via /api/training/set-goal."
                ),
            )

    # ── 3. Calculate target pace ────────────────────────────────────────────
    target_pace = None
    if validated_target_time_minutes is not None:
        target_pace = calculate_target_pace(distance_km, validated_target_time_minutes)

    # ── 4. Write: delete then insert (all validation passed) ────────────────
    await db.user_goals.delete_many({"user_id": user_id})

    goal_obj = UserGoal(
        user_id=user_id,
        event_name=event_name,
        event_date=parsed_event_date.isoformat() if parsed_event_date else None,  # normalized YYYY-MM-DD when provided
        distance_type=goal.distance_type,
        distance_km=distance_km,
        target_time_minutes=validated_target_time_minutes,
        target_pace=target_pace,
    )
    doc = goal_obj.model_dump()
    await db.user_goals.insert_one(doc)

    doc.pop("_id", None)

    logger.info(
        f"Goal set for user {user_id}: "
        f"name={event_name!r} distance_type={goal.distance_type} "
        f"event_date={parsed_event_date.isoformat() if parsed_event_date else None} "
        f"target_time_minutes={validated_target_time_minutes}"
    )
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


def _domain_activity_date(activity) -> Optional[date]:
    start_time = getattr(activity, "start_time", None)
    if isinstance(start_time, datetime):
        return start_time.date()
    if isinstance(start_time, date):
        return start_time
    if isinstance(start_time, str):
        try:
            return datetime.fromisoformat(start_time.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.fromisoformat(start_time.split("T")[0]).date()
            except ValueError:
                return None
    return None


def _iter_recent_running_domain_activities(activities: list, *, max_days: int) -> list:
    today = datetime.now(timezone.utc).date()
    selected = []
    for activity in activities:
        activity_type = (getattr(activity, "activity_type", None) or "").strip().lower()
        if activity_type not in RUNNING_TYPES:
            continue
        activity_date = _domain_activity_date(activity)
        if activity_date is None:
            continue
        days_ago = (today - activity_date).days
        if 0 <= days_ago < max_days:
            selected.append((activity, activity_date))
    return selected


def calculate_week_stats_from_domain(activities: list) -> dict:
    """Calculate rolling 7-day dashboard stats from DomainActivity only."""
    week_activities = _iter_recent_running_domain_activities(activities, max_days=7)
    total_km = sum(((getattr(a, "distance_m", None) or 0.0) / 1000.0) for a, _ in week_activities)
    total_duration_minutes = sum(((getattr(a, "duration_s", None) or 0.0) / 60.0) for a, _ in week_activities)
    sessions = len(week_activities)

    return {
        "sessions": sessions,
        "volume_km": round(total_km, 1),
        "load_signal": None,
        "actual_duration_minutes": int(round(total_duration_minutes)) if total_duration_minutes > 0 else 0,
    }


def calculate_month_stats_from_domain(activities: list) -> dict:
    """Calculate rolling 30-day dashboard stats from DomainActivity only."""
    today = datetime.now(timezone.utc).date()
    current_month = []
    prev_month = []

    for activity in activities:
        activity_type = (getattr(activity, "activity_type", None) or "").strip().lower()
        if activity_type not in RUNNING_TYPES:
            continue
        activity_date = _domain_activity_date(activity)
        if activity_date is None:
            continue
        days_ago = (today - activity_date).days
        if 0 <= days_ago < 30:
            current_month.append((activity, activity_date))
        elif 30 <= days_ago < 60:
            prev_month.append((activity, activity_date))

    current_km = sum(((getattr(a, "distance_m", None) or 0.0) / 1000.0) for a, _ in current_month)
    prev_km = sum(((getattr(a, "distance_m", None) or 0.0) / 1000.0) for a, _ in prev_month)
    active_weeks = len({(d.isocalendar()[0], d.isocalendar()[1]) for _, d in current_month})

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
        "trend": trend,
    }


# Dashboard insight cache (5 minutes TTL) — uses shared module so Garmin sync
# can invalidate after a RunIndex refresh without circular imports.
import dashboard_insight_cache as _dic
DASHBOARD_CACHE_TTL = _dic.TTL_SECONDS


@api_router.get("/dashboard/insight")
async def get_dashboard_insight(language: str = "en", user: dict = Depends(auth_user)):
    """Get dashboard coach insight with week and month summaries and recovery score - NO LLM"""
    
    user_id = user["id"]
    now = datetime.now(timezone.utc).timestamp()
    
    cached = _dic.get(user_id, language)
    if cached is not None:
        cached_data, cached_time = cached
        if now - cached_time < DASHBOARD_CACHE_TTL:
            logger.info(f"Dashboard insight cache hit for {user_id}_{language}")
            return cached_data
    
    # Canonical dashboard source: garmin_activities → DomainActivity.
    garmin_domain_activities = await load_garmin_domain_activities(db, user_id)
    week_stats = calculate_week_stats_from_domain(garmin_domain_activities)
    month_stats = calculate_month_stats_from_domain(garmin_domain_activities)
    run_index = calculate_run_index_from_domain(garmin_domain_activities)
    await upsert_run_index_snapshot(db, user_id, activities=garmin_domain_activities)
    
    # Generate insight using local engine (NO LLM)
    coach_insight = generate_dashboard_insight(
        week_stats=week_stats,
        month_stats=month_stats,
        recovery_score=None,
        language=language
    )
    
    result = DashboardInsightResponse(
        coach_insight=coach_insight,
        week=week_stats,
        month=month_stats,
        recovery_score=None,
        run_index=run_index,
    )
    
    # Store in shared cache
    _dic.set(user_id, language, result, now)
    logger.info(f"Dashboard insight cached for {user_id}_{language}")
    
    return result


@api_router.get("/stats")
async def get_stats(user: dict = Depends(auth_user)):
    """Get training statistics — running metrics from garmin_activities (DomainActivity).

    PR184: authority changed from db.workouts to garmin_activities → DomainActivity.
    Reuses the same DomainActivity helpers as /dashboard/insight (#182) to avoid
    a third divergent window implementation.  No synthetic fallback data.
    Response contract preserved (same keys).
    """
    from collections import defaultdict
    user_id = user["id"]

    # Canonical source: garmin_activities → DomainActivity (running only)
    garmin_domain_activities = await load_garmin_domain_activities(db, user_id)

    week_stats = calculate_week_stats_from_domain(garmin_domain_activities)
    month_stats = calculate_month_stats_from_domain(garmin_domain_activities)

    sessions_7_days: int = week_stats["sessions"]
    km_7_days: float = week_stats["volume_km"]

    # Derive sessions_30_days from the 30-day window used by calculate_month_stats_from_domain
    month_activities = _iter_recent_running_domain_activities(garmin_domain_activities, max_days=30)
    sessions_30_days: int = len(month_activities)
    km_30_days: float = month_stats["volume_km"]

    # Build weekly_summary from the 7-day window (DomainActivity, running only)
    daily_data: dict = defaultdict(lambda: {"distance": 0.0, "duration": 0, "count": 0})
    for activity, activity_date in _iter_recent_running_domain_activities(garmin_domain_activities, max_days=7):
        date_str = activity_date.isoformat()
        daily_data[date_str]["distance"] += round(
            (getattr(activity, "distance_m", None) or 0.0) / 1000.0, 3
        )
        daily_data[date_str]["duration"] += int(
            round((getattr(activity, "duration_s", None) or 0.0) / 60.0)
        )
        daily_data[date_str]["count"] += 1

    weekly_summary = [{"date": d, **data} for d, data in sorted(daily_data.items())]

    # Compute aggregate totals from the 30-day window for legacy response fields
    all_30d = _iter_recent_running_domain_activities(garmin_domain_activities, max_days=30)
    total_duration_minutes = int(round(
        sum((getattr(a, "duration_s", None) or 0.0) / 60.0 for a, _ in all_30d)
    ))
    hr_values = [
        getattr(a, "avg_heart_rate_bpm", None)
        for a, _ in all_30d
        if isinstance(getattr(a, "avg_heart_rate_bpm", None), (int, float))
    ]
    avg_heart_rate = round(sum(hr_values) / len(hr_values), 1) if hr_values else None

    return {
        "total_workouts": sessions_30_days,
        "total_distance_km": km_30_days,
        "total_duration_minutes": total_duration_minutes,
        "avg_heart_rate": avg_heart_rate,
        "workouts_by_type": {"run": sessions_30_days} if sessions_30_days > 0 else {},
        "weekly_summary": weekly_summary,
        # Fields consumed by Progress page
        "sessions_7_days": sessions_7_days,
        "km_7_days": km_7_days,
        "sessions_30_days": sessions_30_days,
        "km_30_days": km_30_days,
    }


@api_router.post("/coach/analyze", response_model=CoachResponse)
async def analyze_with_coach(request: CoachRequest, user: dict = Depends(auth_user)):
    """Conversational chat coach with server-side LLM enrichment.

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
            current_goal = plan_data.get("goal", "MAINTENANCE")
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
    
    # 6. Récupérer les signaux physiologiques depuis les sources canoniques V2
    vma_info = None
    predictions_summary = ""
    vo2max_value: Optional[float] = None
    paces_summary = ""
    try:
        from training_v2.training_paces import compute_training_paces, training_paces_to_api_dict

        garmin_raw = await db.garmin_activities.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        domain_activities = mongo_garmin_activities_to_domain(garmin_raw)
        if domain_activities:
            acwr = build_training_load(domain_activities, today.date()).acwr
            perf = predict_races(domain_activities, today.date())
            predictions = [
                f"{pred.distance_label}: {pred.predicted_time_str}"
                for pred in perf.predictions
                if pred.predicted_time_str
            ]
            predictions_summary = " | ".join(predictions)

            paces_v2 = training_paces_to_api_dict(
                compute_training_paces(domain_activities, today.date(), user_max_hr=None)
            )
            easy = ((paces_v2.get("paces") or {}).get("easy") or {})
            threshold = ((paces_v2.get("paces") or {}).get("threshold") or {})
            easy_text = f"{easy.get('lower_str')}-{easy.get('upper_str')}" if easy.get("lower_str") and easy.get("upper_str") else None
            threshold_text = threshold.get("pace_str")
            pace_parts = [p for p in [easy_text, threshold_text] if p]
            paces_summary = " | ".join(pace_parts)

        latest_vo2 = await db.garmin_vo2max.find_one(
            {"user_id": user_id, "vo2max_running": {"$ne": None}},
            {"_id": 0, "vo2max_running": 1},
            sort=[("date", -1)],
        )
        if latest_vo2:
            vo2max_value = latest_vo2.get("vo2max_running")
    except Exception as e:
        logger.warning(f"Could not load canonical performance context: {e}")
        vma_info = None
    
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
        "vo2max": vo2max_value,
        "predictions": predictions_summary,
        "paces": paces_summary,
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
    
    # 7. Appeler le modèle LLM serveur configuré pour générer la réponse
    llm_response, success, meta = await enrich_chat_response(
        user_message=user_message,
        context=context,
        conversation_history=[{"role": m.get("role"), "content": m.get("content")} for m in conversation_history],
        user_id=user_id
    )
    
    if not success or not llm_response:
        logger.warning(f"LLM chat failed: {meta}")
        if language == "fr":
            message = "Le service de coaching IA n'est pas disponible actuellement."
        elif language == "es":
            message = "El servicio de coaching con IA no está disponible actualmente."
        else:
            message = "The AI coaching service is currently unavailable."
        raise HTTPException(
            status_code=503,
            detail=message,
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
    """Get RAG-enriched weekly review with server-side LLM enhancement."""
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
    """Get RAG-enriched workout analysis with server-side LLM enhancement."""
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


# ========== CARDIO COACH RUNNING SCREEN ==========

# Returned when no wearable connection is available: explicit "no data"
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
    """Return the RunIndex running-screen payload from Garmin only."""
    user_id = user["id"]

    garmin_conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if garmin_conn and garmin_conn.get("connected"):
        try:
            from garmin.insights import compute_run_index
            garmin_payload = await compute_run_index(db, user_id, language)
            if garmin_payload:
                sync_status = await get_sync_progress(user_id)
                garmin_payload["sync_status"] = sync_status
                metrics = (garmin_payload or {}).get("metrics") or {}
                if metrics.get("run_readiness") is None:
                    cause = "no_data_available_yet"
                    if isinstance(sync_status, dict):
                        phase = sync_status.get("phase")
                        status = sync_status.get("status")
                        error_code = sync_status.get("error_code")
                        dm_status = sync_status.get("daily_metrics_status")
                        if status == "in_progress" or phase in {
                            "activities_fetching",
                            "activities_ready",
                            "run_index_ready",
                            "metrics_7d_fetching",
                            "enriching",
                        }:
                            cause = "sync_in_progress"
                        elif error_code == "session_unavailable":
                            cause = "reconnect_required"
                        elif error_code in {
                            "daily_metrics_fetch_failed",
                            "daily_metrics_7d_failed",
                            "daily_metrics_enrichment_failed",
                        } or dm_status == "failed":
                            cause = "garmin_fetch_error"
                    garmin_payload["readiness_unavailable_cause"] = cause
                return garmin_payload
        except Exception as e:
            logger.warning(f"[run-index] Garmin computation failed, falling back: {e}")

    return _CARDIO_COACH_NO_DATA


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

class TrainingCycleStartDateUpdateRequest(BaseModel):
    start_date: str = Field(..., description="Plan start date (YYYY-MM-DD)")

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("start_date must use YYYY-MM-DD format.") from exc
        return value

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


def _parse_iso_date_field(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date() if value.tzinfo else value.replace(tzinfo=timezone.utc).date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            return None
    if isinstance(value, date):
        return value
    return None


# ========== TRAINING ENDPOINTS ==========

@api_router.post("/training/set-goal")
async def set_training_goal(
    goal: str = Query(..., description="10K | SEMI | MARATHON"),
    distance_km: Optional[float] = Query(None, description="Required for ULTRA: target distance in km (> 42.195)"),
    user: dict = Depends(auth_user)
):
    """
    Définit l'objectif principal du cycle.

    PR226: goal change always clears stale user_goals race data.
    ULTRA requires distance_km > 42.195 stored in training_cycles.ultra_distance_km.
    MAINTENANCE never inherits a race_date or target_time.
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"]:
        raise HTTPException(status_code=400, detail="Invalid goal")

    goal_upper = goal.upper()

    # PR226: ULTRA requires an explicit distance > 42.195 km.
    ultra_distance_km: Optional[float] = None
    if goal_upper == "ULTRA":
        ultra_distance_km = _validate_ultra_distance_km(distance_km)

    cycle_set: dict = {
        "goal": goal_upper,
        "start_date": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    if ultra_distance_km is not None:
        cycle_set["ultra_distance_km"] = ultra_distance_km
    else:
        # Clear any previously stored ultra distance when switching away from ULTRA.
        cycle_set["ultra_distance_km"] = None

    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": cycle_set},
        upsert=True,
    )

    # PR226: any goal change invalidates the previous race metadata so that
    # consumers never see a stale race_date from the old goal.
    await db.user_goals.delete_many({"user_id": user["id"]})

    logger.info(f"[Training] Goal set for user {user['id']}: {goal_upper}")

    return {"status": "updated", "goal": goal_upper}


@api_router.post("/training/v2/cycle/start-date")
async def update_training_v2_cycle_start_date(
    payload: TrainingCycleStartDateUpdateRequest,
    user: dict = Depends(auth_user),
):
    """Update the canonical Training V2 cycle start date for the authenticated user."""
    user_id = user["id"]
    cycle = await db.training_cycles.find_one({"user_id": user_id}, {"_id": 0})
    if not cycle:
        raise HTTPException(
            status_code=400,
            detail="No training cycle defined. Use /api/training/set-goal first.",
        )

    goal_type_raw = cycle.get("goal")
    if not goal_type_raw or goal_type_raw not in GOAL_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or missing goal type: {goal_type_raw}",
        )

    requested_start_date = date.fromisoformat(payload.start_date)
    reference_date = datetime.now(timezone.utc).date()
    if requested_start_date > reference_date:
        raise HTTPException(
            status_code=400,
            detail="plan_start_date cannot be in the future.",
        )

    mapped_goal_type = _LEGACY_GOAL_TO_V2.get(goal_type_raw.upper())
    if mapped_goal_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot map goal_type '{goal_type_raw}' to V2 GoalType.",
        )

    from training_v2.plan_goal import GoalType as _GoalType

    if mapped_goal_type != _GoalType.maintenance:
        user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
        race_date_raw = user_goal.get("event_date") if user_goal else None
        if race_date_raw:
            race_date = _parse_iso_date_field(race_date_raw)
            if race_date is None:
                raise HTTPException(
                    status_code=400,
                    detail="Could not parse race_date in user goal.",
                )
            if requested_start_date > race_date:
                raise HTTPException(
                    status_code=400,
                    detail="plan_start_date must be on or before race_date.",
                )

    updated_at = datetime.now(timezone.utc)
    persisted_start = datetime(
        requested_start_date.year,
        requested_start_date.month,
        requested_start_date.day,
        tzinfo=timezone.utc,
    )
    await db.training_cycles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "start_date": persisted_start,
                "updated_at": updated_at,
            }
        },
        upsert=False,
    )

    return {
        "status": "updated",
        "cycle": {
            "goal": goal_type_raw,
            "start_date": requested_start_date.isoformat(),
            "updated_at": updated_at.isoformat(),
        },
    }


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
async def set_training_plan_goal(
    goal: str,
    distance_km: Optional[float] = Query(None, description="Required for ULTRA: target distance in km (> 42.195)"),
    user: dict = Depends(auth_user),
):
    """
    Set the training goal (10K, SEMI, MARATHON, etc.)

    PR226: mirrors /training/set-goal — clears stale user_goals on any change;
    ULTRA requires distance_km > 42.195.
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"]:
        raise HTTPException(status_code=400, detail="Invalid goal")

    goal_upper = goal.upper()
    config = GOAL_CONFIG[goal_upper]

    # PR226: ULTRA requires an explicit distance > 42.195 km.
    ultra_distance_km: Optional[float] = None
    if goal_upper == "ULTRA":
        ultra_distance_km = _validate_ultra_distance_km(distance_km)

    cycle_set: dict = {
        "goal": goal_upper,
        "updated_at": datetime.now(timezone.utc),
        "ultra_distance_km": ultra_distance_km,
    }

    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": cycle_set},
        upsert=True,
    )

    # PR226: any goal change invalidates the previous race metadata.
    await db.user_goals.delete_many({"user_id": user["id"]})

    logger.info(f"[Training] Goal updated for user {user['id']}: {goal_upper}")

    return {
        "status": "updated",
        "goal": goal_upper,
        "cycle_weeks": config["cycle_weeks"],
        "description": config["description"],
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
    def _goal_entry(goal_type: str, config: dict) -> dict:
        entry: dict = {
            "type": goal_type,
            "description": config["description"],
            "cycle_weeks": config["cycle_weeks"],
        }
        # long_run_ratio and intensity_pct are omitted for goals that have no
        # canonical value (e.g. MAINTENANCE — these fields are not applicable).
        if config.get("long_run_ratio") is not None:
            entry["long_run_ratio"] = config["long_run_ratio"]
        if config.get("intensity_pct") is not None:
            entry["intensity_pct"] = config["intensity_pct"]
        return entry

    return {
        "goals": [_goal_entry(goal_type, config) for goal_type, config in GOAL_CONFIG.items()]
    }


# PR232A — POST /training/feedback (manual "Réalisé / Manqué" feedback) has
# been removed. Execution truth is now exclusively derived from Garmin via
# the PR230 boundary (training_v2.performed_workout) and exposed on
# GET /training/v2/week. See RUNINDEX_PR232A_REPORT.md.


def _resolve_canonical_reference_date(now_utc: datetime, garmin_activities_90: list) -> date:
    """C231 — SINGLE canonical ``reference_date`` resolver, shared by
    ``/training/today`` and ``/training/v2/week``.

    Both endpoints MUST call this (never ``now_utc.date()`` directly) so that
    "today"/the current week are always IDENTICAL between the two endpoints
    for the same user + call instant — the only difference between the two
    call sites is which already-fetched ``garmin_activities_90`` list is
    passed in (both fetch it with the identical 90-day query).
    """
    from training_v2.local_reference_date import resolve_local_reference_date

    return resolve_local_reference_date(
        now_utc=now_utc, garmin_activities=garmin_activities_90
    )


# ──────────────────────────────────────────────────────────────────────────────
# PR137 — Daily Runtime Migration V2
# Helper functions are in training_v2/daily_runtime_helpers.py (pure, testable).
# ──────────────────────────────────────────────────────────────────────────────


@api_router.get("/training/today")
async def get_today_adaptive_session(user: dict = Depends(auth_user)):
    """
    Returns today's adaptive training session.

    Runtime path (PR228 — unified canonical orchestration):
        Garmin actual → TrainingHistory → TrainingLoad → RunnerProfile
          → TrainingState → PlanGoal → Periodization → WeeklyTarget
          → RecentTrainingResponse → WeeklyReconciliation
          → WorkoutGenerator → reconciled WeeklyPlan
          (identical to /training/v2/week — single canonical plan)
          ↓
        séance prévue aujourd'hui (WorkoutPrescription from WeeklyPlan)
          ↓
        ReadinessDecision V2
          ↓
        DailyAdaptation V2  ← Today only, never rebuilds WeeklyPlan
          ↓
        séance du jour adaptée → payload /training/today

    PR228 guarantees:
    - Today's session is derived from the SAME reconciled plan as /training/v2/week.
    - No second WorkoutGenerator. No second WeeklyReconciliation.
    - DailyAdaptation modifies Today only (keep or reduce, never increase).
    - None ≠ 0: absent data is never treated as bad readiness.
    """
    from training_v2.week_plan_bridge import build_canonical_weekly_plan

    # Single clock — all time derivations use this single anchor.
    # No second now() call anywhere in this handler.
    now_utc = datetime.now(timezone.utc)
    ninety_days_ago = now_utc - timedelta(days=90)

    # ── 1. Goal resolver — single source of truth (PR226) ────────────────
    resolved = await _resolve_goal_v2(user["id"])

    # ── 2. Garmin activities — 90-day window, ALWAYS loaded (PR228 fail-closed) ─
    # Garmin history is loaded unconditionally so that Week and Today always
    # share the same canonical activity source.
    # Rule: the garmin connection flag only gates live data that requires an
    # active connection (daily_metrics, readiness).  Historical activities
    # already stored in the DB are available regardless of connection status.
    #
    # FAIL-CLOSED: a technical error during activity load or domain-conversion
    # must propagate as an explicit HTTP error.  We must NEVER build
    # TrainingHistory / WeeklyPlan with workouts=[] when the true cause is
    # a storage failure — that would silently produce a deep_reprise plan.
    # Absence of history (user has never run) is handled cleanly upstream
    # (empty list from the DB with no exception).
    try:
        garmin_activities_90 = await db.garmin_activities.find(
            {"user_id": user["id"], "start_time": {"$gte": ninety_days_ago.isoformat()}},
            {"_id": 0},
        ).to_list(1000)
    except Exception as exc:
        logger.error(f"[TrainingToday] Garmin activities DB read failed: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Training plan temporarily unavailable: Garmin activity data could not be read.",
        ) from exc
    try:
        domain_activities_90: list = mongo_garmin_activities_to_domain(garmin_activities_90)
    except Exception as exc:
        logger.error(f"[TrainingToday] Garmin activities domain conversion failed: {exc}")
        raise HTTPException(
            status_code=503,
            detail="Training plan temporarily unavailable: Garmin activity data could not be processed.",
        ) from exc

    # C231 — "today" resolved via the SAME canonical helper used by
    # /training/v2/week (_resolve_canonical_reference_date), never a raw
    # ``now_utc.date()``, so both endpoints always target the identical
    # calendar day/week for this user.
    today = _resolve_canonical_reference_date(now_utc, garmin_activities_90)
    today_iso = today.isoformat()
    day_name = today.strftime("%A")

    # ── 3. Readiness (live data) — only when Garmin connection is active ──
    readiness_data_source = "unavailable"
    garmin_connected = False
    garmin_daily_metrics_docs: list = []

    garmin_conn = await db.garmin_connections.find_one({"user_id": user["id"]}, {"_id": 0})
    if garmin_conn and garmin_conn.get("connected"):
        try:
            garmin_daily_metrics_docs = await (
                db.garmin_daily_metrics.find({"user_id": user["id"]}, {"_id": 0})
                .sort("date", -1)
                .limit(30)
                .to_list(length=30)
            )
            garmin_connected = True
        except Exception as exc:
            logger.warning(f"[TrainingToday] Garmin daily metrics fetch failed: {exc}")

    # ── 4. Canonical plan — SAME pipeline as /training/v2/week (PR228) ───
    # build_canonical_weekly_plan includes WeeklyReconciliation internally.
    # Today's session comes from this reconciled plan — no second WorkoutGenerator,
    # no second WeeklyReconciliation.
    canonical = build_canonical_weekly_plan(
        workouts=domain_activities_90,
        goal_type=resolved.goal_type,
        race_date=resolved.race_date,
        cycle_start_date=resolved.cycle_start,
        reference_date=today,
        target_distance_km=resolved.target_distance_km,
        target_time_seconds=resolved.target_time_sec,
    )
    weekly_plan = canonical.weekly_plan

    # ── 5. Find today's planned session from the reconciled WeeklyPlan ───
    planned_prescription: Optional[WorkoutPrescription] = None
    for session in weekly_plan.sessions:
        if session.day.lower() == day_name.lower():
            planned_prescription = session
            break

    if planned_prescription is None:
        return {
            "status": "no_session",
            "message": "No session planned for today",
            "date": today_iso,
            "day": day_name,
        }

    # ── 6/7. ReadinessDecision V2 + DailyAdaptation V2 — Today only ──────
    # C231 — delegated to training_v2.today_prescription, the SAME shared
    # helper /training/v2/week uses to compute today's FINAL prescription
    # before freezing a snapshot. Guarantees identical output regardless of
    # which endpoint is hit first for a given day.
    today_final = resolve_today_final_prescription(
        planned_prescription=planned_prescription,
        reference_date=today,
        domain_activities_90=domain_activities_90,
        garmin_daily_metrics_docs=garmin_daily_metrics_docs,
        garmin_connected=garmin_connected,
    )
    readiness_decision: ReadinessDecision = today_final.readiness_decision
    adaptation_result: DailyAdaptationResult = today_final.adaptation_result
    readiness_data_source = today_final.readiness_data_source

    # C231 — item 2 BLOCKER FIX: go through the SAME atomic get-or-create
    # snapshot service /training/v2/week uses, so both endpoints always
    # converge on ONE canonical served prescription for today, regardless
    # of which one is called first or concurrently.
    from training_v2.served_prescription import get_or_create_served_prescription
    from training_v2.week_execution import prescription_id_for

    served_result = await get_or_create_served_prescription(
        db,
        user_id=user["id"],
        prescription_id=prescription_id_for(user["id"], today, day_name.lower()),
        planned_date=today,
        served_candidate=adaptation_result.adapted_workout,
        planned_prescription=planned_prescription,
    )
    served_prescription = served_result.prescription

    # ── 8. Map prescription to legacy runtime dict format ─────────────────
    planned_session_runtime = prescription_to_runtime_session(planned_prescription)
    # C231 — the canonical SERVED prescription (post get-or-create snapshot
    # resolution), never the raw local adaptation_result, is what gets
    # displayed — guarantees identical distance/duration as /training/v2/week.
    served_prescription_runtime = prescription_to_runtime_session(served_prescription)
    # Backward-compat alias — kept byte-for-byte identical to
    # served_prescription_runtime (see "served_prescription" key below).
    adapted_runtime = served_prescription_runtime
    # C231 (round 2, item 1 BLOCKER FIX) — adaptation_applied is now PURELY
    # informative: it reflects TODAY's live readiness recompute action and
    # MUST NEVER be used (here or by any consumer) to choose which session is
    # displayed. The canonical served_prescription (frozen once per day) is
    # ALWAYS the one displayed, regardless of what a later recompute would
    # decide. session_modified_from_planned (C231 micro-correction: read
    # directly from the winning snapshot's own immutable
    # `modified_from_planned` field, computed ONCE at snapshot-creation time
    # — NEVER recomputed here against the current live planned_prescription,
    # which can keep changing after the snapshot was frozen and would make
    # the boolean flip retroactively for a served session that never
    # actually changed).
    adaptation_applied = adaptation_result.action != DailyAdaptationAction.KEEP
    session_modified_from_planned = served_result.modified_from_planned
    adaptation_reason = ", ".join(adaptation_result.reason_codes)

    # ── 9. Legacy compat: recommendation / recommendation_color derived from V2 ─
    recommendation, recommendation_color = BAND_TO_RECOMMENDATION[readiness_decision.band]

    return {
        "status": "success",
        "date": today_iso,
        "day": day_name,
        # planned_session: runtime dict of today's session from the reconciled canonical plan.
        # PR228: this is now the output of prescription_to_runtime_session(planned_prescription)
        # rather than a raw dict from generate_dynamic_training_plan.
        "planned_session": planned_session_runtime,
        # original_prescription: identical to planned_session — both represent the planned
        # session before DailyAdaptation. Preserved for backward compat with existing consumers.
        "original_prescription": planned_session_runtime,
        # served_prescription: C231 (round 2) — THE canonical session to display
        # today. Always the frozen, get-or-create'd served prescription — never
        # recomputed on the fly, never superseded by a later readiness change.
        # Consumers (frontend included) MUST read this key first and MUST NOT
        # fall back to planned_session while a served_prescription exists.
        "served_prescription": served_prescription_runtime,
        # adapted_prescription: kept for backward compat — always byte-for-byte
        # identical to served_prescription (never a separate, potentially
        # divergent, live recompute).
        "adapted_prescription": adapted_runtime,
        # Legacy compat: adaptive_session present when the served prescription
        # actually differed from the plan AT SNAPSHOT-CREATION TIME (immutable
        # fact from session_modified_from_planned), not a live recompute. None
        # (unknown, e.g. pre-migration snapshot) is treated the same as False
        # here — falsy in Python — so no adaptive_session is fabricated.
        "adaptive_session": adapted_runtime if session_modified_from_planned else None,
        # adaptation_applied: INFORMATIVE ONLY (C231 round 2) — describes what
        # today's live readiness recompute would decide right now. NEVER an
        # authority for choosing which session to display; see
        # served_prescription for that.
        "adaptation_applied": adaptation_applied,
        "adaptation_reason": adaptation_reason,
        "adaptation_action": adaptation_result.action.value,
        # session_modified_from_planned: C231 (micro-correction) — the ONLY
        # ground-truth signal for whether the "Adapté" banner should be
        # shown. This is the WINNING SNAPSHOT's own immutable
        # `modified_from_planned` field (computed exactly once, at
        # snapshot-creation time) — never recomputed here against the
        # current live planned_session, which could keep changing after the
        # snapshot was frozen and would otherwise make this flip
        # retroactively for a served session that never actually changed.
        # True/False/None (unknown — old snapshot predating this field; the
        # frontend must show no banner for None, exactly like False).
        "session_modified_from_planned": session_modified_from_planned,
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
        # Legacy compat: fatigue block derived from V2
        "fatigue": {
            "run_readiness": readiness_decision.score,
            "recommendation": recommendation,
            "recommendation_color": recommendation_color,
            "data_source": readiness_data_source,
        },
        # PR228: reconciliation audit (same reconciliation applied to /training/v2/week)
        "weekly_reconciliation": {
            "action": canonical.reconciliation_result.action.value,
            "reason_codes": list(canonical.reconciliation_result.reason_codes),
        },
        # vma / vma_confidence: PR228 — no longer computed in /training/today.
        # These fields were supplied by generate_dynamic_training_plan (coach_service path)
        # which has been removed. Verified: frontend does not consume vma from this endpoint.
        # VMA is available at /run-index (canonical source) and /training/v2/week context.
        "vma": None,
        "vma_confidence": None,
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
    PR185 — VMA V2 + Race Predictions V2.
    Source: garmin_activities → DomainActivity (running only).
    No db.workouts. No avg_speed/0.70 fallback. Riegel extrapolation.
    Frontend contract preserved (has_data, predictions[], athlete_profile).
    """
    from training_v2.performance_model import (
        CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO,
        RUNNING_TYPES,
        seconds_to_str,
        validate_activity,
    )
    user_id = user["id"]
    reference_date = datetime.now(timezone.utc).date()

    # Canonical source: garmin_activities → DomainActivity (PR185)
    raw_activities = await db.garmin_activities.find(
        {"user_id": user_id}, {"_id": 0}
    ).to_list(2000)
    domain_activities = mongo_garmin_activities_to_domain(raw_activities)

    result = predict_races(domain_activities, reference_date)

    if not result.has_data:
        return {
            "has_data": False,
            "message": "Not enough data to predict. Keep training!",
            "predictions": [],
            "model_version": "v2",
        }

    # Map RacePrediction dataclasses to the dict contract expected by the frontend.
    predictions_out = []
    for pred in result.predictions:
        # Build a ±5% range string for display (frontend legacy field)
        if pred.predicted_time_s is not None:
            lo = seconds_to_str(pred.predicted_time_s * 0.97)
            hi = seconds_to_str(pred.predicted_time_s * 1.03)
            predicted_range = f"{lo} - {hi}"
        else:
            predicted_range = None

        entry = {
            "distance": pred.distance_label,
            "distance_km": pred.distance_km,
            "description": {
                "5K": "5 kilomètres",
                "10K": "10 kilomètres",
                "Semi": "Semi-marathon",
                "Marathon": "Marathon",
            }.get(pred.distance_label, pred.distance_label),
            "predicted_time": pred.predicted_time_str,
            "predicted_range": predicted_range,
            "predicted_pace": pred.predicted_pace_str,
            "readiness": pred.readiness,
            "readiness_label": pred.readiness_label,
            "readiness_color": pred.readiness_color,
            "readiness_score": pred.readiness_score,
            "volume_factor": pred.volume_factor,
            "endurance_factor": pred.endurance_factor,
            "confidence": pred.confidence,
            "source_quality_score": pred.source_quality_score,
            "source_quality_confidence": pred.source_quality_confidence,
            "source_speed_percentile": pred.source_speed_percentile,
            "source_relative_hr": pred.source_relative_hr,
            "predicted_time_s": pred.predicted_time_s,
            "extrapolation_ratio": pred.extrapolation_ratio,
            "is_strong_extrapolation": (
                pred.extrapolation_ratio is not None
                and pred.extrapolation_ratio > CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO
            ),
            "curve_method": pred.curve_method,
            "curve_k": pred.curve_k,
            "contributors_count": pred.contributors_count,
            "model_version": "v2",
        }
        predictions_out.append(entry)

    ap = result.athlete_profile
    curve_diag = result.race_curve_diagnostics or {}
    return {
        "has_data": True,
        "athlete_profile": {
            "weekly_km": ap.get("weekly_km"),
            "avg_pace": None,
            "best_pace": None,
            "max_long_run": ap.get("max_long_run_km"),
            "estimated_vma": ap.get("estimated_vma"),
            "estimated_vo2max": ap.get("estimated_vo2max"),
            "vo2max_note": ap.get("vo2max_note"),
            "vma_method": ap.get("vma_method"),
            "vma_confidence": ap.get("vma_confidence"),
            "source_date": ap.get("source_date"),
            "source_distance_km": ap.get("source_distance_km"),
            "vma_efforts_count": 0,
            "total_sessions_6w": len([
                a for a in domain_activities
                if validate_activity(a, reference_date)
                and (activity_date(a) or date.min) >= (reference_date - timedelta(days=41))
            ]),
            "calculation_window": "garmin_activities",
            "model_version": "v2",
        },
        "predictions": predictions_out,
        "race_curve_diagnostics": {
            "curve_method": curve_diag.get("curve_method"),
            "curve_a": curve_diag.get("curve_a"),
            "curve_k": curve_diag.get("curve_k"),
            "curve_k_raw": curve_diag.get("curve_k_raw"),
            "curve_k_prior": curve_diag.get("curve_k_prior"),
            "curve_k_min": curve_diag.get("curve_k_min"),
            "curve_k_max": curve_diag.get("curve_k_max"),
            "contributors_count": curve_diag.get("contributors_count"),
            "qualified_performance_count": curve_diag.get("qualified_performance_count"),
            "observed_distance_min": curve_diag.get("observed_distance_min"),
            "observed_distance_max": curve_diag.get("observed_distance_max"),
            "observed_distance_min_km": curve_diag.get("observed_distance_min_km"),
            "observed_distance_max_km": curve_diag.get("observed_distance_max_km"),
            "fit_quality": curve_diag.get("fit_quality"),
            "k_conflict": curve_diag.get("k_conflict"),
            "k_fallback_applied": curve_diag.get("k_fallback_applied"),
            "weighted_recency": curve_diag.get("weighted_recency"),
            "weighted_quality_confidence": curve_diag.get("weighted_quality_confidence"),
            "weighted_quality_score": curve_diag.get("weighted_quality_score"),
            "effective_contributors": curve_diag.get("effective_contributors"),
            "two_point_evidence_strength": curve_diag.get("two_point_evidence_strength"),
            "contributors": curve_diag.get("contributors", []),
            "slope_evidence_count": curve_diag.get("slope_evidence_count"),
            "slope_evidence_distance_min": curve_diag.get("slope_evidence_distance_min"),
            "slope_evidence_distance_max": curve_diag.get("slope_evidence_distance_max"),
            "slope_evidence_distance_min_km": curve_diag.get("slope_evidence_distance_min_km"),
            "slope_evidence_distance_max_km": curve_diag.get("slope_evidence_distance_max_km"),
        },
        "methodology": {
            "vma_calculation": "Individual HR-speed model (speed = a * HR + b). Built from >= 4 clean running activities with sufficient HR range (>= 20 bpm, >= 3 distinct HR levels). R\u00b2 >= 0.30 required. FCmax from highest credible observed Garmin max HR only (150\u2013230 bpm; no user profile, no population fallback, no formula). Extrapolation to 95% FCmax. No avg_speed/0.70 fallback.",
            "prediction_model": "Race predictions use Performance Curve V2 from #188-qualified observed performances only (no synthetic source): log(T)=log(A)+k·log(D), with single-performance fallback to Riegel k=1.06. Exactly two observations use deterministic shrinkage toward k=1.06 based on evidence strength. For >=3 observations, robust Huber reweighting is followed by a final refit on final weights. If k is outside RunIndex guardrails [1.0, 1.25], fallback k=1.06 is applied and A is re-estimated with fixed slope and weighted intercept. Extrapolation uses symmetric ratio max(target/obs, obs/target) with RunIndex policy thresholds 4.5 (very uncertain) and 6.0 (null prediction). VMA output and estimated VO2max are not used to compute race times; #188 qualification may depend on FCmax through relative HR.",
            "vo2max_formula": "VO2MAX (ml/kg/min) approx VMA (km/h) x 3.5 — derived estimate only, not a lab measurement.",
            "model_version": "v2",
        },
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

    # ── Single clock ──────────────────────────────────────────────────────
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    ninety_days_ago = today - timedelta(days=90)

    # ── PR226: canonical resolver — single source of truth ────────────────
    from training_v2.periodization import build_periodization
    from training_v2.plan_goal import build_plan_goal
    from training_v2.week_plan_bridge import (
        build_weekly_plan_from_workouts,
        workouts_to_domain_activities,
    )

    resolved = await _resolve_goal_v2(user_id)
    goal_type = resolved.goal_type

    # event_name for display context (not used by V2 builder)
    event_name = resolved.user_goal_doc.get("event_name") if resolved.user_goal_doc else None

    # ── Workouts — 90-day window ──────────────────────────────────────────
    garmin_activities_90 = await db.garmin_activities.find({
        "user_id": user_id,
        "start_time": {"$gte": ninety_days_ago.isoformat()}
    }, {"_id": 0}).to_list(1000)
    domain_activities_90 = mongo_garmin_activities_to_domain(garmin_activities_90)

    cycle_start_v2 = resolved.cycle_start
    race_date_v2 = resolved.race_date

    plan_goal_v2 = build_plan_goal(
        goal_type=resolved.mapped_goal,
        race_date=race_date_v2,  # already None for MAINTENANCE
        target_distance_km=resolved.target_distance_km,
        target_time_seconds=resolved.target_time_sec,
        created_from="user",
    )

    if plan_goal_v2.race_date is not None:
        periodization = build_periodization(
            plan_goal=plan_goal_v2,
            reference_date=today.date(),
            race_plan_start_date=cycle_start_v2,
        )
    else:
        periodization = build_periodization(
            plan_goal=plan_goal_v2,
            reference_date=today.date(),
            cycle_anchor_date=cycle_start_v2,
        )

    weekly_target, weekly_plan_v2 = build_weekly_plan_from_workouts(
        workouts=domain_activities_90,
        goal_type=goal_type,
        race_date=race_date_v2,
        cycle_start_date=cycle_start_v2,
        reference_date=today.date(),
        target_distance_km=resolved.target_distance_km,
        target_time_seconds=resolved.target_time_sec,
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

    running_activities_7 = [
        a for a in domain_activities_90
        if (a.activity_type or "").lower() in RUNNING_TYPES
        and activity_date(a) is not None
        and activity_date(a) >= seven_days_ago.date()
    ]
    running_activities_28 = [
        a for a in domain_activities_90
        if (a.activity_type or "").lower() in RUNNING_TYPES
        and activity_date(a) is not None
        and activity_date(a) >= twenty_eight_days_ago.date()
    ]
    km_7_running = sum((a.distance_m or 0.0) / 1000.0 for a in running_activities_7)
    km_28_running = sum((a.distance_m or 0.0) / 1000.0 for a in running_activities_28)
    load_7 = km_7_running
    load_28 = km_28_running

    cycle_weeks = GOAL_CONFIG[goal_type]["cycle_weeks"]
    # resolved.cycle_start is already validated — never None after _resolve_goal_v2.
    cycle_start_dt = datetime(
        resolved.cycle_start.year,
        resolved.cycle_start.month,
        resolved.cycle_start.day,
        tzinfo=timezone.utc,
    )
    if today < cycle_start_dt:
        current_week = 0
    else:
        delta_days = (today - cycle_start_dt).days
        current_week = min(delta_days // 7 + 1, cycle_weeks + 1)
    phase = periodization.phase.value

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
            "type": goal_type,
            "name": event_name,
            "event_date": resolved.race_date.isoformat() if resolved.race_date else None,
        },
        "current_week": current_week,
        "total_weeks": cycle_weeks,
        "phase": phase,
        "context": context,
        "debug_volume": {
            "km_7": round(km_7_running, 1),
            "km_28": round(km_28_running, 1),
            "current_weekly_km": round(km_28_running / 4.0, 1),
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

    Pipeline (PR228 — canonical reconciled path):
      TrainingHistory → TrainingState → PlanGoal → Periodization
      → WeeklyTarget → RecentTrainingResponse → WeeklyReconciliation
      → WorkoutGenerator → WeeklyPlan

    No legacy adapter applied. None stays None (None != 0 doctrine).
    WeeklyReconciliation: preserve/reduce only, never increase.
    """
    from training_v2.week_plan_bridge import build_canonical_weekly_plan
    from training_v2.training_week_response import (
        WeekV2GoalResponse,
        WeekV2PlanResponse,
        WeekV2SessionResponse,
        WeekV2StateResponse,
        WeekV2TargetResponse,
    )

    user_id = user["id"]

    # ── Single clock to avoid midnight-boundary skew ──────────────────────
    now_utc = datetime.now(timezone.utc)

    # ── Workouts — 90-day window ──────────────────────────────────────────
    ninety_days_ago = now_utc - timedelta(days=90)
    garmin_activities_90 = await db.garmin_activities.find(
        {"user_id": user_id, "start_time": {"$gte": ninety_days_ago.isoformat()}},
        {"_id": 0},
    ).to_list(1000)
    domain_activities_90 = mongo_garmin_activities_to_domain(garmin_activities_90)

    # ── C231 — "today" resolved via the SAME canonical helper used by
    # /training/today (_resolve_canonical_reference_date), never a raw UTC
    # date that can drift by up to a day around midnight ──────────────────
    reference_date = _resolve_canonical_reference_date(now_utc, garmin_activities_90)

    # ── PR226: canonical resolver — single source of truth ────────────────
    resolved = await _resolve_goal_v2(user_id)

    # ── PR228: canonical builder — single call with reconciliation ────────
    canonical = build_canonical_weekly_plan(
        workouts=domain_activities_90,
        goal_type=resolved.goal_type,
        race_date=resolved.race_date,
        cycle_start_date=resolved.cycle_start,
        reference_date=reference_date,
        target_distance_km=resolved.target_distance_km,
        target_time_seconds=resolved.target_time_sec,
    )
    weekly_target = canonical.reconciled_target
    weekly_plan = canonical.weekly_plan
    reconciliation_result = canonical.reconciliation_result

    # ── Assemble native V2 response — no adapter, no coercion ────────────
    _WEEK_GOAL_NORM: dict[str, str] = {
        "5K": "5k", "10K": "10k", "SEMI": "half_marathon",
        "HALF_MARATHON": "half_marathon", "MARATHON": "marathon",
        "ULTRA": "ultra", "MAINTENANCE": "maintenance",
    }
    _goal_type_v2_str: str = _WEEK_GOAL_NORM.get(
        resolved.goal_type.upper() if resolved.goal_type else "", resolved.goal_type
    )

    # ── PR232A/C231: factual execution — PR230 Garmin boundary, no fallback,
    # matched against the FROZEN prescription snapshot once a session is
    # today or in the past (see training_v2/prescription_snapshot.py) ─────
    from training_v2.week_execution import (
        EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE,
        build_week_execution,
        prescription_id_for,
    )
    from training_v2.training_week_response import (
        WeekV2ActualResponse,
        WeekV2PaceRangeResponse,
    )
    from training_v2.session_structure import resolve_session_pace_zone
    from training_v2.canonical_training_paces import load_canonical_training_paces
    from training_v2.prescription_snapshot import PrescriptionSnapshot, snapshot_from_prescription
    from training_v2.served_prescription import get_or_create_served_prescription

    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)

    existing_snapshot_docs = await db.training_prescription_snapshots.find(
        {"user_id": user_id}, {"_id": 0}
    ).to_list(1000)
    frozen_snapshots: dict[str, PrescriptionSnapshot] = {}
    for doc in existing_snapshot_docs:
        prescription_id = doc.get("prescription_id")
        planned_date_raw = doc.get("planned_date")
        if not isinstance(prescription_id, str) or not isinstance(planned_date_raw, str):
            continue
        try:
            snapshot_planned_date = date.fromisoformat(planned_date_raw)
        except ValueError:
            continue
        if not (week_start <= snapshot_planned_date <= week_end):
            continue
        frozen_snapshots[prescription_id] = PrescriptionSnapshot(**doc)

    # C231 — item 3 BLOCKER FIX: the session whose planned_date == today MUST
    # be frozen from its FINAL post-DailyAdaptation prescription (the same one
    # /training/today serves), never the raw WeeklyPlan session. Only compute
    # this (extra Garmin-connection/readiness fetch) when today's session has
    # NOT already been frozen by a prior call (from either endpoint) — once a
    # snapshot exists it is authoritative and this branch is skipped entirely.
    sessions_for_execution = list(weekly_plan.sessions)
    today_day_name = reference_date.strftime("%A").lower()
    today_index = next(
        (i for i, s in enumerate(sessions_for_execution) if s.day.lower() == today_day_name),
        None,
    )
    if today_index is not None:
        today_prescription_id = prescription_id_for(
            user_id, reference_date, today_day_name
        )
        if today_prescription_id not in frozen_snapshots:
            garmin_conn = await db.garmin_connections.find_one(
                {"user_id": user_id}, {"_id": 0}
            )
            garmin_connected = bool(garmin_conn and garmin_conn.get("connected"))
            garmin_daily_metrics_docs: list = []
            if garmin_connected:
                try:
                    garmin_daily_metrics_docs = await (
                        db.garmin_daily_metrics.find({"user_id": user_id}, {"_id": 0})
                        .sort("date", -1)
                        .limit(30)
                        .to_list(length=30)
                    )
                except Exception as exc:
                    logger.warning(
                        f"[TrainingV2Week] Garmin daily metrics fetch failed: {exc}"
                    )
                    garmin_connected = False
            today_final = resolve_today_final_prescription(
                planned_prescription=sessions_for_execution[today_index],
                reference_date=reference_date,
                domain_activities_90=domain_activities_90,
                garmin_daily_metrics_docs=garmin_daily_metrics_docs,
                garmin_connected=garmin_connected,
            )
            # C231 — item 2 BLOCKER FIX: go through the SAME atomic
            # get-or-create used by /training/today, so a concurrent call to
            # either endpoint always converges on one canonical Mongo
            # snapshot instead of each endpoint writing/using its own
            # locally computed (possibly divergent) candidate.
            served_result = await get_or_create_served_prescription(
                db,
                user_id=user_id,
                prescription_id=today_prescription_id,
                planned_date=reference_date,
                served_candidate=today_final.adaptation_result.adapted_workout,
                planned_prescription=sessions_for_execution[today_index],
            )
            served = served_result.prescription
            sessions_for_execution[today_index] = served
            frozen_snapshots[today_prescription_id] = snapshot_from_prescription(
                user_id=user_id,
                prescription_id=today_prescription_id,
                planned_date=reference_date,
                session=served,
                # C231 (micro-correction): propagate the WINNING snapshot's
                # own modified_from_planned — never recomputed here — so
                # this in-memory cache entry stays consistent with what
                # /training/today would read for the exact same snapshot.
                modified_from_planned=served_result.modified_from_planned,
            )

    try:
        execution = build_week_execution(
            user_id=user_id,
            reference_date=reference_date,
            week_start=week_start,
            sessions=sessions_for_execution,
            garmin_docs=garmin_activities_90,
            frozen_snapshots=frozen_snapshots,
        )
    except ValueError as exc:
        logger.error(f"[TrainingV2Week] Execution invariant violated: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Training week execution is inconsistent (invariant violated); "
            "refusing to return a truncated week.",
        ) from exc

    # C231 — fail-fast: the response MUST cover every WeeklyPlan session.
    # A silently truncated week (fewer executed sessions than prescribed)
    # is never acceptable; surface it as an explicit server error instead.
    if len(execution.sessions) != len(weekly_plan.sessions):
        logger.error(
            "[TrainingV2Week] Session count mismatch: "
            f"{len(execution.sessions)} executed vs {len(weekly_plan.sessions)} planned "
            f"for user_id={user_id}."
        )
        raise HTTPException(
            status_code=500,
            detail="Training week execution is incomplete (session count mismatch); "
            "refusing to return a truncated week.",
        )

    # Freeze rule is insert-only: never overwrite an already-frozen snapshot.
    for snapshot in execution.snapshots_to_persist:
        await db.training_prescription_snapshots.update_one(
            {"user_id": snapshot.user_id, "prescription_id": snapshot.prescription_id},
            {"$setOnInsert": snapshot.model_dump(mode="json")},
            upsert=True,
        )

    # C232 (correction) — canonical Training Paces loader (BLOCKER FIX): same
    # query/window/policy and same reference_date as /training/v2/paces, so
    # the two endpoints can never disagree for the same user/day. No 90-day
    # truncation: compute_training_paces' own HIGH-never-expires policy
    # needs the fuller history loaded by the canonical loader.
    training_paces_v2 = await load_canonical_training_paces(
        db, user_id=user_id, reference_date=reference_date
    )

    def _pace_range_response(pace_range) -> Optional[WeekV2PaceRangeResponse]:
        if pace_range is None:
            return None
        return WeekV2PaceRangeResponse(
            lower_min_per_km=pace_range.lower.min_per_km,
            upper_min_per_km=pace_range.upper.min_per_km,
        )

    def _actual_response(row) -> Optional[WeekV2ActualResponse]:
        if row.activity_id is None:
            return None
        return WeekV2ActualResponse(
            activity_id=row.activity_id,
            distance_km=row.actual_distance_km,
            duration_minutes=row.actual_duration_min,
            pace_min_per_km=row.actual_pace_min_per_km,
            activity_type=row.actual_activity_type,
            start_time=row.actual_start_time.isoformat() if row.actual_start_time else None,
        )

    def _session_response(se) -> WeekV2SessionResponse:
        planned_date_iso = se.planned_date.isoformat() if se.planned_date else None
        if se.execution_status == EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE:
            # C231 (round 2, item 3) — this day's real historical prescription
            # was never frozen/served while it was current: the live
            # (recomputed today) session is NOT trusted as historical fact.
            # None != 0: distance/duration/workout_type/matching/adherence
            # are all left unfabricated. The real Garmin activity (if any)
            # still surfaces separately via unmatched_actuals, never here.
            return WeekV2SessionResponse(
                day=se.session.day,
                planned_date=planned_date_iso,
                workout_type=None,
                intensity_class=None,
                distance_km=None,
                duration_minutes=None,
                estimated_tss=None,
                reason_codes=[],
                matching_status=None,
                adherence_status=None,
                actual=None,
                execution_status=EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE,
                primary_pace=None,
            )
        # C232 (correction round 2, item 4) — historical immutability: once
        # planned_date <= reference_date, ``se.session`` is the EFFECTIVE
        # prescription — the FROZEN snapshot when one exists (see
        # prescription_snapshot.py), which does NOT persist a pace zone.
        # Resolving a pace zone from TODAY's live TrainingPaces for an
        # already-frozen (today-or-past) session would let it silently
        # acquire retroactively a pace that was never fixed with it (a
        # Monday session could show a different pace on Wednesday than it
        # did on Monday). A pace zone is therefore only ever resolved for a
        # STILL STRICTLY FUTURE session (never frozen yet, live prescription
        # may still legitimately evolve until then). ``None`` stays ``None``
        # — never reconstructed from live paces for a frozen session.
        is_frozen_or_past = (
            se.planned_date is not None and se.planned_date <= reference_date
        )
        if is_frozen_or_past:
            primary_pace = None
        else:
            # C232 (correction) — honest pace ZONE only (no fabricated
            # splits): see training_v2/session_structure.py docstring for
            # exactly which workout_types get a pace zone and why.
            primary_pace = _pace_range_response(
                resolve_session_pace_zone(
                    workout_type=se.session.workout_type,
                    paces=training_paces_v2,
                )
            )
        return WeekV2SessionResponse(
            day=se.session.day,
            planned_date=planned_date_iso,
            workout_type=se.session.workout_type,
            intensity_class=se.session.intensity_class,
            distance_km=se.session.distance_km,
            duration_minutes=se.session.duration_minutes,
            estimated_tss=0 if se.session.workout_type == "rest" else None,
            reason_codes=list(se.session.reason_codes),
            matching_status=se.row.matching_status.value,
            adherence_status=se.row.adherence_status.value,
            actual=_actual_response(se.row),
            execution_status=None,
            primary_pace=primary_pace,
        )

    sessions = [_session_response(se) for se in execution.sessions]
    unmatched_actuals = [
        actual
        for row in execution.extra_rows
        if (actual := _actual_response(row)) is not None
    ]

    response = TrainingWeekV2Response(
        reference_date=reference_date.isoformat(),
        goal=WeekV2GoalResponse(
            goal_type=_goal_type_v2_str,
            race_date=resolved.race_date.isoformat() if resolved.race_date else None,
            target_time_seconds=resolved.target_time_sec,
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
            unmatched_actuals=unmatched_actuals,
        ),
        reconciliation_action=reconciliation_result.action.value,
        reconciliation_reason_codes=list(reconciliation_result.reason_codes),
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
    from training_v2.plan_goal import build_plan_goal
    from training_v2.training_cycle_response import build_cycle_calendar_response

    user_id = user["id"]

    # ── Single clock ─────────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    reference_date = now_utc.date()

    # ── PR226: canonical resolver — single source of truth ────────────────
    resolved = await _resolve_goal_v2(user_id)

    # ── Build PlanGoal V2 ─────────────────────────────────────────────────
    plan_goal = build_plan_goal(
        goal_type=resolved.mapped_goal,
        race_date=resolved.race_date,  # already None for MAINTENANCE
        target_distance_km=resolved.target_distance_km,
        target_time_seconds=resolved.target_time_sec,
        created_from="user",
    )

    # PlanGoal invariant: maintenance can't have race_date →
    # plan_goal.race_date is not None ↔ race_calendar mode.
    if plan_goal.race_date is not None:
        response = build_cycle_calendar_response(
            plan_goal,
            reference_date,
            race_plan_start_date=resolved.cycle_start,
            target_time_seconds=resolved.target_time_sec,
        )
    else:
        response = build_cycle_calendar_response(
            plan_goal,
            reference_date,
            cycle_anchor_date=resolved.cycle_start,
            target_time_seconds=resolved.target_time_sec,
        )

    return response.model_dump(mode="json")


# PR194 — GET /training/v2/paces
# VDOT-based Daniels training paces derived exclusively from qualified performances.
# FORBIDDEN sources: Garmin VO2max, VMA, Race Predictions outputs.
# ---------------------------------------------------------------------------

@api_router.get("/training/v2/paces")
async def get_training_v2_paces(user: dict = Depends(auth_user)):
    """Return V2 training paces (Daniels E/M/T/I/R) derived from VDOT.

    VDOT is computed exclusively from qualified running performances (#188).
    Garmin VO2max and VMA never influence the paces returned here.

    C232 (correction) — BLOCKER FIX: this endpoint now goes through the
    SAME canonical loader (`training_v2.canonical_training_paces`) and the
    SAME canonical `reference_date` resolver as GET /training/v2/week, so
    the two endpoints can never disagree (one showing a pace, the other
    None) for the same user/day. No locally re-derived activity window,
    no Garmin-connection gate that the other endpoint doesn't apply.

    Response:
        confidence         "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT"
        vdot_reference     float (internal, not surfaced to runner)
        paces.easy         {lower, upper} pace range in min/km
        paces.marathon     single pace in min/km
        paces.threshold    single pace in min/km
        paces.interval     {lower, upper} pace range in min/km
        paces.repetition   single pace in min/km

    When confidence == "INSUFFICIENT", paces fields are all null.
    """
    from training_v2.canonical_training_paces import load_canonical_training_paces
    from training_v2.training_paces import training_paces_to_api_dict

    user_id = user["id"]
    now_utc = datetime.now(timezone.utc)

    # ── C231/C232 — SAME canonical reference_date resolver as Today/Week ──
    ninety_days_ago = now_utc - timedelta(days=90)
    garmin_activities_90 = await db.garmin_activities.find(
        {"user_id": user_id, "start_time": {"$gte": ninety_days_ago.isoformat()}},
        {"_id": 0},
    ).to_list(1000)
    reference_date = _resolve_canonical_reference_date(now_utc, garmin_activities_90)

    # ── C232 — canonical loader: same query/window/policy as /training/v2/week ─
    paces = await load_canonical_training_paces(
        db, user_id=user_id, reference_date=reference_date
    )
    return training_paces_to_api_dict(paces)


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
async def store_chat_response(
    message_id: str,
    response: str,
    user: dict = Depends(auth_user),
):
    """Store a response generated by client-side WebLLM.

    The owning user_id is resolved exclusively from the authenticated JWT;
    any client-supplied user_id is not accepted (A35 — P0 security fix).
    """
    user_id = user["id"]
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
    Direct trial activation is disabled.

    Trial activation must go through the Garmin server authority
    (`garmin.service.connect` -> `activate_garmin_trial`) so that every grant is
    tied to a verified Garmin identity in `garmin_trial_registry`.
    """
    raise HTTPException(
        status_code=403,
        detail="Trial activation is only available during Garmin connection",
    )



class PaddleCheckoutRequest(BaseModel):
    price_id: Optional[str] = None


class PaddleCheckoutResponse(BaseModel):
    transaction_id: str
    paddle_environment: str
    paddle_client_token: str
    price_id: str


def _normalize_paddle_event_type(event_type: Optional[str]) -> str:
    normalized = (event_type or "").strip()
    if normalized == "subscription.cancelled":
        return "subscription.canceled"
    return normalized


def _normalize_paddle_status(status: Optional[str]) -> str:
    normalized = (status or "").strip().lower()
    if normalized == "cancelled":
        return "canceled"
    return normalized


def _parse_paddle_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_current_period_end(evt_data: dict) -> Optional[datetime]:
    current_period = evt_data.get("current_billing_period") or {}
    if not isinstance(current_period, dict):
        return None
    return _parse_paddle_dt(current_period.get("ends_at"))


def _require_current_period_end(event_type: str, evt_data: dict) -> datetime:
    period_end = _extract_current_period_end(evt_data)
    if period_end is None:
        raise RuntimeError(
            f"Paddle event {event_type!r} missing valid current_billing_period.ends_at; refusing Premium mutation"
        )
    return period_end


def _require_occurred_at(event_type: str, event: dict) -> datetime:
    occurred_at = _parse_paddle_dt(event.get("occurred_at"))
    if occurred_at is None:
        raise RuntimeError(
            f"Paddle event {event_type!r} missing valid occurred_at; refusing state mutation"
        )
    return occurred_at


def _resolve_paddle_event_processing_lease_seconds(raw_value: Optional[str]) -> int:
    default_value = 900
    if raw_value is None:
        return default_value
    cleaned = str(raw_value).strip()
    if cleaned == "":
        logger.warning(
            "Invalid PADDLE_EVENT_PROCESSING_LEASE_SECONDS=%r; falling back to %s",
            raw_value,
            default_value,
        )
        return default_value
    try:
        parsed = int(cleaned)
    except (ValueError, TypeError):
        logger.warning(
            "Invalid PADDLE_EVENT_PROCESSING_LEASE_SECONDS=%r; falling back to %s",
            raw_value,
            default_value,
        )
        return default_value
    return max(60, parsed)


PADDLE_EVENT_PROCESSING_LEASE_SECONDS = _resolve_paddle_event_processing_lease_seconds(
    os.getenv("PADDLE_EVENT_PROCESSING_LEASE_SECONDS")
)


async def _try_claim_existing_paddle_event(
    db_handle,
    event_id: str,
    event_type: str,
    now_iso: str,
    match_status,
) -> bool:
    reclaimed = await db_handle.paddle_events.find_one_and_update(
        {"event_id": event_id, "status": match_status},
        {
            "$set": {
                "event_type": event_type,
                "status": "processing",
                "claimed_at": now_iso,
            },
            "$unset": {
                "processed_at": "",
                "failed_at": "",
                "last_error": "",
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    return reclaimed is not None


async def _claim_paddle_event(db_handle, event_id: str, event_type: str) -> str:
    now = datetime.now(timezone.utc)
    claimed_at = now.isoformat()

    try:
        existing = await db_handle.paddle_events.find_one_and_update(
            {"event_id": event_id},
            {
                "$setOnInsert": {
                    "event_id": event_id,
                    "event_type": event_type,
                    "status": "processing",
                    "claimed_at": claimed_at,
                }
            },
            upsert=True,
            return_document=ReturnDocument.BEFORE,
        )
    except DuplicateKeyError:
        existing = await db_handle.paddle_events.find_one({"event_id": event_id})

    if existing is None:
        return "claimed"

    existing_status = str(existing.get("status") or "").strip().lower()
    if existing_status == "processed":
        return "processed"
    if existing_status in {"failed", ""}:
        if await _try_claim_existing_paddle_event(
            db_handle,
            event_id,
            event_type,
            claimed_at,
            existing.get("status"),
        ):
            return "claimed"

    elif existing_status == "processing":
        claimed_at_dt = _parse_paddle_dt(existing.get("claimed_at"))
        is_stale = claimed_at_dt is None or (now - claimed_at_dt) >= timedelta(
            seconds=PADDLE_EVENT_PROCESSING_LEASE_SECONDS
        )
        if not is_stale:
            return "processing"

        reclaimed = await db_handle.paddle_events.find_one_and_update(
            {
                "event_id": event_id,
                "status": "processing",
                "claimed_at": existing.get("claimed_at"),
            },
            {
                "$set": {
                    "event_type": event_type,
                    "status": "processing",
                    "claimed_at": claimed_at,
                },
                "$unset": {
                    "processed_at": "",
                    "failed_at": "",
                    "last_error": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if reclaimed is not None:
            logger.warning(
                "[Paddle] Reclaimed stale processing event_id=%r (lease=%ss)",
                event_id,
                PADDLE_EVENT_PROCESSING_LEASE_SECONDS,
            )
            return "claimed"
    else:
        if await _try_claim_existing_paddle_event(
            db_handle,
            event_id,
            event_type,
            claimed_at,
            existing.get("status"),
        ):
            logger.warning(
                "[Paddle] Recovered legacy/unknown event status for event_id=%r status=%r",
                event_id,
                existing.get("status"),
            )
            return "claimed"

    current = await db_handle.paddle_events.find_one({"event_id": event_id})
    current_status = str((current or {}).get("status") or "").strip().lower()
    if current_status == "processed":
        return "processed"
    if current_status == "processing":
        return "processing"
    if await _try_claim_existing_paddle_event(
        db_handle,
        event_id,
        event_type,
        claimed_at,
        (current or {}).get("status"),
    ):
        return "claimed"
    raise RuntimeError(
        f"Paddle event {event_id!r} could not be claimed from status {current_status!r}"
    )


async def _mark_paddle_event_failed(db_handle, event_id: str, event_type: str, error: str) -> None:
    await db_handle.paddle_events.update_one(
        {"event_id": event_id},
        {
            "$set": {
                "event_id": event_id,
                "event_type": event_type,
                "status": "failed",
                "last_error": error,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
            "$unset": {
                "processed_at": "",
            },
        },
        upsert=True,
    )


async def _mark_paddle_event_processed(db_handle, event_id: str, event_type: str) -> None:
    await db_handle.paddle_events.update_one(
        {"event_id": event_id},
        {
            "$set": {
                "event_id": event_id,
                "event_type": event_type,
                "status": "processed",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            },
            "$unset": {
                "last_error": "",
                "failed_at": "",
            },
        },
        upsert=True,
    )


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

    The price is ALWAYS taken from PADDLE_PRICE_ID (Premium 4.99 EUR/month).

    Security:
    - user_id is ALWAYS taken from the JWT token, never from the request body.
    - Premium is only activated server-side after the Paddle webhook is verified.
    - The frontend MUST NOT interpret the transaction creation as a grant of access.
    """
    if not PADDLE_API_KEY:
        raise HTTPException(status_code=503, detail="Paddle not configured on this server")
    if not PADDLE_PRICE_ID:
        raise HTTPException(status_code=503, detail="Paddle price ID not configured")
    if request.price_id and request.price_id != PADDLE_PRICE_ID:
        raise HTTPException(status_code=400, detail="Client price_id does not match configured Paddle price")

    user_id = user["id"]
    price_id = PADDLE_PRICE_ID

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
    - Idempotence: only events already completed successfully are treated as duplicates.

    Supported Paddle Billing event types:
        subscription.activated   → activate_premium()
        subscription.updated     → renew_premium() (renewal / plan update)
        subscription.canceled    → cancel_subscription()
        subscription.past_due    → log warning (access expires naturally)
        transaction.completed    → audit/update local transaction state only
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
    event_type = _normalize_paddle_event_type(event.get("event_type", ""))
    data       = event.get("data", {})

    if not event_id:
        logger.error("[Paddle] Webhook missing stable event_id — rejecting event")
        raise HTTPException(status_code=400, detail="Paddle webhook event_id is required")

    logger.info(f"[Paddle] Webhook received: event_type={event_type!r} event_id={event_id!r}")

    # ── Idempotence guard ────────────────────────────────────────────────────
    claim_status = await _claim_paddle_event(db, event_id, event_type)
    if claim_status == "processed":
        logger.info(f"[Paddle] Duplicate processed event_id={event_id!r} — skipping")
        return {"received": True, "status": "duplicate"}
    if claim_status == "processing":
        logger.info(f"[Paddle] Event event_id={event_id!r} is already processing")
        return {"received": True, "status": "processing"}

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

    try:
        # ─────────────────────────────────────────────────────────────────────
        # subscription.activated
        # Fired when a subscription's status becomes "active" (typically after the
        # first payment is processed).
        # ─────────────────────────────────────────────────────────────────────
        if event_type == "subscription.activated":
            user_id              = _user_id_from_event(data)
            paddle_sub_id        = data.get("id")
            paddle_customer_id   = data.get("customer_id")

            if not user_id:
                logger.warning("[Paddle] subscription.activated — missing user_id in custom_data")
                result = {"received": True, "status": "no_user_id"}
            else:
                occurred_at = _require_occurred_at(event_type, event)
                period_end = _require_current_period_end(event_type, data)
                from subscription_manager import activate_premium
                activation = await activate_premium(
                    db,
                    user_id,
                    paddle_subscription_id=paddle_sub_id,
                    paddle_customer_id=paddle_customer_id,
                    premium_expires_at=period_end,
                    paddle_last_event_at=occurred_at,
                    paddle_event_id=event_id,
                )
                if activation.get("_stale_event"):
                    logger.info(f"[Paddle] Ignoring stale subscription.activated for user '{user_id}'")
                    result = {"received": True, "status": "stale"}
                else:
                    logger.info(
                        f"[Paddle] PREMIUM activated for user '{user_id}' "
                        f"(sub={paddle_sub_id}, period_end={period_end})"
                    )
                    result = {"received": True}

        # ─────────────────────────────────────────────────────────────────────
        # subscription.updated
        # Covers renewals, plan changes, and reactivations after past_due recovery.
        # ─────────────────────────────────────────────────────────────────────
        elif event_type == "subscription.updated":
            user_id            = _user_id_from_event(data)
            paddle_sub_id      = data.get("id")
            new_status         = _normalize_paddle_status(data.get("status"))

            if not user_id:
                logger.warning("[Paddle] subscription.updated — missing user_id in custom_data")
                result = {"received": True, "status": "no_user_id"}
            elif new_status in ("active", "trialing"):
                occurred_at = _require_occurred_at(event_type, event)
                period_end = _require_current_period_end(event_type, data)
                from subscription_manager import renew_premium
                renewal = await renew_premium(
                    db,
                    user_id,
                    paddle_sub_id,
                    period_end,
                    paddle_last_event_at=occurred_at,
                    paddle_event_id=event_id,
                )
                if renewal.get("_stale_event"):
                    logger.info(f"[Paddle] Ignoring stale subscription.updated for user '{user_id}'")
                    result = {"received": True, "status": "stale"}
                else:
                    logger.info(
                        f"[Paddle] PREMIUM renewed for user '{user_id}' until {period_end}"
                    )
                    result = {"received": True}
            elif new_status == "canceled":
                occurred_at = _require_occurred_at(event_type, event)
                period_end = _extract_current_period_end(data)
                from subscription_manager import cancel_subscription
                cancellation = await cancel_subscription(
                    db,
                    user_id,
                    premium_expires_at=period_end,
                    paddle_last_event_at=occurred_at,
                    paddle_event_id=event_id,
                )
                if cancellation.get("_stale_event"):
                    logger.info(f"[Paddle] Ignoring stale canceled subscription.updated for user '{user_id}'")
                    result = {"received": True, "status": "stale"}
                else:
                    logger.info(f"[Paddle] Subscription canceled for user '{user_id}'")
                    result = {"received": True}
            else:
                logger.info(
                    f"[Paddle] subscription.updated status={new_status!r} for user '{user_id}' — no action"
                )
                result = {"received": True}

        elif event_type == "subscription.canceled":
            user_id = _user_id_from_event(data)
            if not user_id:
                logger.warning("[Paddle] subscription.canceled — missing user_id in custom_data")
                result = {"received": True, "status": "no_user_id"}
            else:
                occurred_at = _require_occurred_at(event_type, event)
                period_end = _extract_current_period_end(data)
                from subscription_manager import cancel_subscription
                cancellation = await cancel_subscription(
                    db,
                    user_id,
                    premium_expires_at=period_end,
                    paddle_last_event_at=occurred_at,
                    paddle_event_id=event_id,
                )
                if cancellation.get("_stale_event"):
                    logger.info(f"[Paddle] Ignoring stale subscription.canceled for user '{user_id}'")
                    result = {"received": True, "status": "stale"}
                else:
                    logger.info(f"[Paddle] Subscription canceled for user '{user_id}'")
                    result = {"received": True}

        # ─────────────────────────────────────────────────────────────────────
        # subscription.past_due
        # Payment failed; Paddle will retry. We do NOT immediately revoke access —
        # access naturally lapses when premium_expires_at passes.
        # ─────────────────────────────────────────────────────────────────────
        elif event_type == "subscription.past_due":
            user_id = _user_id_from_event(data)
            logger.warning(
                f"[Paddle] subscription.past_due for user '{user_id}' "
                f"— access will lapse at premium_expires_at"
            )
            result = {"received": True}

        # ─────────────────────────────────────────────────────────────────────
        # transaction.completed
        # Fired for every completed payment. Premium activation waits for the
        # subscription webhook because that flow carries the canonical expiry.
        # ─────────────────────────────────────────────────────────────────────
        elif event_type == "transaction.completed":
            user_id            = _user_id_from_event(data)
            paddle_customer_id = data.get("customer_id")
            transaction_id     = data.get("id")

            logger.info(
                f"[Paddle] transaction.completed for user '{user_id}' "
                f"(txn={transaction_id}) — awaiting subscription webhook for Premium activation"
            )

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
            result = {"received": True}

        # ─────────────────────────────────────────────────────────────────────
        # transaction.payment_failed
        # ─────────────────────────────────────────────────────────────────────
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
            result = {"received": True}

        else:
            logger.info(f"[Paddle] Unhandled event type: {event_type!r}")
            result = {"received": True}
    except Exception as exc:
        await _mark_paddle_event_failed(db, event_id, event_type, str(exc))
        raise

    await _mark_paddle_event_processed(db, event_id, event_type)

    return result


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


async def _ensure_paddle_events_unique_index(db_handle) -> None:
    """Thin wrapper — delegates to the testable service module."""
    from services.paddle_event_index import ensure_paddle_events_unique_index
    await ensure_paddle_events_unique_index(db_handle)


async def _ensure_prescription_snapshot_unique_index(db_handle) -> None:
    """Thin wrapper — delegates to the testable service module."""
    from services.prescription_snapshot_index import ensure_prescription_snapshot_unique_index
    await ensure_prescription_snapshot_unique_index(db_handle)


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
    # Critical Paddle idempotence index must be guaranteed before startup continues.
    await _ensure_paddle_events_unique_index(db)
    # C231 — item 4 BLOCKER FIX: the prescription-snapshot unique index is
    # exactly as critical as Paddle's — it is the ONLY mechanism guaranteeing
    # a served prescription can never be silently duplicated/overwritten
    # under concurrency (see training_v2/served_prescription.py). It must be
    # created BEFORE the fail-open try block below: if index creation ever
    # fails, startup must propagate the error and stop, never continue while
    # falsely claiming immutability is guaranteed.
    await _ensure_prescription_snapshot_unique_index(db)
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
        # Historical readiness/run-index collections (kept for non-destructive compatibility)
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

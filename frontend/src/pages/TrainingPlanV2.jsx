import { useState, useEffect, useCallback } from "react";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  RefreshCw,
  Target,
  Calendar,
  Clock,
  Zap,
  Heart,
  Activity,
  AlertCircle,
  Footprints,
  Mountain,
  TrendingUp,
  Timer,
} from "lucide-react";
import axios from "axios";
import Paywall from "@/components/Paywall";
import { API_BASE_URL } from "@/config";
import { formatDistance } from "@/utils/units";

const API = API_BASE_URL;

// ── Workout type → icon mapping ─────────────────────────────────────────────
function workoutIcon(type) {
  switch (type) {
    case "rest":
    case "recovery":
      return <Heart className="w-4 h-4" />;
    case "easy":
    case "long_easy":
      return <Footprints className="w-4 h-4" />;
    case "steady":
      return <Activity className="w-4 h-4" />;
    case "quality":
    case "intervals":
    case "fartlek":
      return <Zap className="w-4 h-4" />;
    case "threshold":
    case "tempo":
      return <TrendingUp className="w-4 h-4" />;
    case "race":
      return <Mountain className="w-4 h-4" />;
    default:
      return <Footprints className="w-4 h-4" />;
  }
}

// ── Workout type → colour class ──────────────────────────────────────────────
function workoutColorClass(type) {
  switch (type) {
    case "rest":
      return "text-muted-foreground";
    case "recovery":
      return "text-blue-400";
    case "easy":
    case "long_easy":
      return "text-green-400";
    case "steady":
      return "text-yellow-400";
    case "quality":
    case "intervals":
    case "fartlek":
      return "text-orange-400";
    case "threshold":
    case "tempo":
      return "text-red-400";
    case "race":
      return "text-purple-400";
    default:
      return "text-foreground";
  }
}

// ── Intensity class → colour class ───────────────────────────────────────────
function intensityColorClass(intensityClass) {
  switch (intensityClass) {
    case "low":
      return "bg-green-500/20 text-green-400";
    case "moderate":
      return "bg-yellow-500/20 text-yellow-400";
    case "high":
      return "bg-orange-500/20 text-orange-400";
    case "very_high":
      return "bg-red-500/20 text-red-400";
    case "none":
    default:
      return "bg-muted/50 text-muted-foreground";
  }
}

// ── Format seconds to h:mm display ──────────────────────────────────────────
function formatTargetTime(seconds) {
  if (seconds == null) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const pad = (n) => String(n).padStart(2, "0");
  return `${h}h${pad(m)}`;
}

// ── Day key → i18n key ───────────────────────────────────────────────────────
function dayKey(day) {
  const map = {
    monday: "day_monday",
    tuesday: "day_tuesday",
    wednesday: "day_wednesday",
    thursday: "day_thursday",
    friday: "day_friday",
    saturday: "day_saturday",
    sunday: "day_sunday",
  };
  return map[day?.toLowerCase()] ?? day;
}

// ── Workout type → i18n key ──────────────────────────────────────────────────
function workoutTypeKey(type) {
  if (!type) return null;
  return `trainingV2.workout_${type}`;
}

// ── Intensity class → i18n key ───────────────────────────────────────────────
function intensityKey(cls) {
  if (!cls) return null;
  return `trainingV2.intensity_${cls}`;
}

// ── Continuity state → i18n key ──────────────────────────────────────────────
function continuityStateKey(state) {
  if (!state) return null;
  return `trainingV2.state_${state}`;
}

// ── Confidence → i18n key ────────────────────────────────────────────────────
function confidenceKey(conf) {
  if (!conf) return null;
  return `trainingV2.confidence_${conf}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────
export default function TrainingPlanV2() {
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading } = useSubscription();
  const { unitSystem } = useUnitSystem();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState(null);

  const fetchWeek = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    try {
      const res = await axios.get(`${API}/training/v2/week`);
      setData(res.data);
    } catch (err) {
      if (err.response?.status === 403 && err.response?.data?.error === "subscription_required") {
        setApiError("subscription_required");
      } else {
        setApiError("generic");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!subLoading && !isFree) {
      fetchWeek();
    } else if (!subLoading) {
      setLoading(false);
    }
  }, [subLoading, isFree, fetchWeek]);

  // Paywall for free users
  if (isFree || apiError === "subscription_required") {
    return <Paywall language={lang} returnPath="/training-v2" />;
  }

  // Loading skeleton
  if (loading || subLoading) {
    return (
      <div className="p-4 md:p-6 space-y-4 max-w-2xl mx-auto">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <div className="space-y-3">
          {[...Array(7)].map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  // Error state
  if (apiError === "generic") {
    return (
      <div className="p-4 md:p-6 max-w-2xl mx-auto flex flex-col items-center gap-4 pt-16">
        <AlertCircle className="w-12 h-12 text-destructive" />
        <p className="text-muted-foreground text-center">{t("trainingV2.error")}</p>
        <Button onClick={fetchWeek} variant="outline" size="sm">
          <RefreshCw className="w-4 h-4 mr-2" />
          {t("trainingV2.retry")}
        </Button>
      </div>
    );
  }

  // No data
  if (!data) {
    return (
      <div className="p-4 md:p-6 max-w-2xl mx-auto flex flex-col items-center gap-4 pt-16">
        <p className="text-muted-foreground">{t("trainingV2.noData")}</p>
        <Button onClick={fetchWeek} variant="outline" size="sm">
          <RefreshCw className="w-4 h-4 mr-2" />
          {t("trainingV2.refresh")}
        </Button>
      </div>
    );
  }

  const { goal, week_state, sessions } = data;

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-2xl mx-auto pb-20">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-foreground">{t("trainingV2.currentWeek")}</h1>
        <Button onClick={fetchWeek} variant="ghost" size="icon" aria-label={t("trainingV2.refresh")}>
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {/* 1 — GOAL */}
      {goal && (
        <GoalCard goal={goal} t={t} />
      )}

      {/* 2 — WEEK STATE */}
      {week_state && (
        <WeekStateCard weekState={week_state} t={t} unitSystem={unitSystem} />
      )}

      {/* 3 — SESSIONS */}
      {Array.isArray(sessions) && sessions.length > 0 && (
        <SessionsSection sessions={sessions} t={t} unitSystem={unitSystem} />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// GoalCard
// ─────────────────────────────────────────────────────────────────────────────
function GoalCard({ goal, t }) {
  const { goal_type, race_date, target_time_seconds } = goal;
  const formattedTime = formatTargetTime(target_time_seconds);

  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Target className="w-4 h-4 text-primary" />
        <span className="text-sm font-medium text-foreground">{t("trainingV2.goal")}</span>
      </div>
      <div className="space-y-1.5">
        {goal_type != null && (
          <p className="text-base font-semibold text-foreground">{goal_type}</p>
        )}
        {race_date != null && (
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Calendar className="w-3.5 h-3.5" />
            <span>{t("trainingV2.raceDate")}: {race_date}</span>
          </div>
        )}
        {formattedTime != null && (
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Timer className="w-3.5 h-3.5" />
            <span>{t("trainingV2.targetTime")}: {formattedTime}</span>
          </div>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// WeekStateCard
// ─────────────────────────────────────────────────────────────────────────────
function WeekStateCard({ weekState, t, unitSystem }) {
  const {
    continuity_state,
    allow_intensity,
    target_basis,
    target_km,
    target_duration_minutes,
    session_count,
    confidence,
  } = weekState;

  const stateLabel = continuity_state
    ? t(continuityStateKey(continuity_state))
    : null;

  const confLabel = confidence ? t(confidenceKey(confidence)) : null;

  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Activity className="w-4 h-4 text-primary" />
        <span className="text-sm font-medium text-foreground">{t("trainingV2.weekTarget")}</span>
      </div>

      <div className="space-y-2">
        {stateLabel != null && (
          <p className="text-sm text-foreground font-medium">{stateLabel}</p>
        )}

        {allow_intensity === false && (
          <p className="text-xs text-yellow-400">{t("trainingV2.intensityLimited")}</p>
        )}

        <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
          {/* Target distance — only when distance-based and value is known */}
          {target_basis === "distance" && target_km != null && (
            <span className="flex items-center gap-1">
              <Footprints className="w-3.5 h-3.5" />
              {formatDistance(target_km, { unitSystem })}
            </span>
          )}

          {/* Target duration — only when duration-based and value is known */}
          {target_basis === "duration" && target_duration_minutes != null && (
            <span className="flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {target_duration_minutes} {t("trainingV2.min")}
            </span>
          )}

          {/* Session count */}
          {session_count != null && (
            <span className="flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5" />
              {session_count} {t("trainingV2.sessions")}
            </span>
          )}
        </div>

        {confLabel != null && (
          <p className="text-xs text-muted-foreground">
            {t("trainingV2.confidence")}: {confLabel}
          </p>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SessionsSection
// ─────────────────────────────────────────────────────────────────────────────
function SessionsSection({ sessions, t, unitSystem }) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
        {t("trainingV2.planned")}
      </h2>
      <div className="space-y-2">
        {sessions.map((session, idx) => (
          <SessionCard key={idx} session={session} t={t} unitSystem={unitSystem} />
        ))}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SessionCard
// ─────────────────────────────────────────────────────────────────────────────
function SessionCard({ session, t, unitSystem }) {
  const { day, workout_type, intensity_class, distance_km, duration_minutes, estimated_tss } = session;

  const dayLabel = day ? t(`trainingV2.${dayKey(day)}`) : day;
  const typeKey = workoutTypeKey(workout_type);
  const typeLabel = typeKey ? t(typeKey) : workout_type;
  const colorClass = workoutColorClass(workout_type);
  const intensityLabel = intensity_class ? t(intensityKey(intensity_class)) : null;
  const intensityClasses = intensity_class ? intensityColorClass(intensity_class) : "";

  const showTss = estimated_tss != null;

  return (
    <div className="rounded-xl border border-border bg-card p-3 flex items-center gap-3">
      {/* Day label */}
      <div className="w-20 shrink-0">
        <p className="text-xs text-muted-foreground">{dayLabel}</p>
      </div>

      {/* Icon + type */}
      <div className={`flex items-center gap-1.5 flex-1 min-w-0 ${colorClass}`}>
        {workoutIcon(workout_type)}
        <p className="text-sm font-medium truncate">{typeLabel}</p>
      </div>

      {/* Metrics */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground shrink-0">
        {/* Distance — only when known */}
        {distance_km != null && (
          <span>{formatDistance(distance_km, { unitSystem })}</span>
        )}

        {/* Duration — only when known */}
        {duration_minutes != null && (
          <span className="flex items-center gap-0.5">
            <Clock className="w-3 h-3" />
            {duration_minutes} {t("trainingV2.min")}
          </span>
        )}

        {/* TSS — only when known (null = unknown, 0 = real zero) */}
        {showTss && (
          <span className="text-muted-foreground">{estimated_tss} {t("trainingV2.tss")}</span>
        )}
      </div>

      {/* Intensity badge */}
      {intensityLabel && intensity_class !== "none" && (
        <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${intensityClasses}`}>
          {intensityLabel}
        </span>
      )}
    </div>
  );
}

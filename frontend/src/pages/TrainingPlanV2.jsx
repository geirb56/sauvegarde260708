import { useState, useEffect, useCallback } from "react";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import Paywall from "@/components/Paywall";
import {
  RefreshCw,
  Trophy,
  Calendar,
  Target,
  Activity,
  Zap,
  Heart,
  Moon,
  Footprints,
  Dumbbell,
} from "lucide-react";
import axios from "axios";
import { toast } from "sonner";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

// ---------------------------------------------------------------------------
// Workout type → icon + colors (V2 types only, never mutates workout_type)
// ---------------------------------------------------------------------------
const WORKOUT_STYLES = {
  rest: {
    icon: Moon,
    bg: "#12142a",
    border: "#4f46e5",
    text: "#a5b4fc",
    badge: "#4f46e5",
    badgeText: "#ffffff",
  },
  recovery: {
    icon: Heart,
    bg: "#0b1a1a",
    border: "#22d3ee",
    text: "#a5f3fc",
    badge: "#0891b2",
    badgeText: "#ffffff",
  },
  easy: {
    icon: Footprints,
    bg: "#0b1a12",
    border: "#10b981",
    text: "#6ee7b7",
    badge: "#10b981",
    badgeText: "#0b1a12",
  },
  steady: {
    icon: Activity,
    bg: "#1c1400",
    border: "#eab308",
    text: "#fde68a",
    badge: "#ca8a04",
    badgeText: "#ffffff",
  },
  quality: {
    icon: Zap,
    bg: "#1c1207",
    border: "#f97316",
    text: "#fed7aa",
    badge: "#f97316",
    badgeText: "#1c1207",
  },
  long_easy: {
    icon: Dumbbell,
    bg: "#0d1321",
    border: "#3b82f6",
    text: "#93c5fd",
    badge: "#2563eb",
    badgeText: "#ffffff",
  },
};

const DEFAULT_STYLE = {
  icon: Activity,
  bg: "#111827",
  border: "#6b7280",
  text: "#d1d5db",
  badge: "#374151",
  badgeText: "#ffffff",
};

function getWorkoutStyle(workoutType) {
  return WORKOUT_STYLES[workoutType] || DEFAULT_STYLE;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatSeconds(totalSeconds) {
  if (totalSeconds == null) return null;
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) {
    return `${h}h${String(m).padStart(2, "0")}m${String(s).padStart(2, "0")}s`;
  }
  return `${m}m${String(s).padStart(2, "0")}s`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionCard({ title, icon: Icon, children }) {
  return (
    <div
      style={{
        background: "#0d1321",
        border: "1px solid #1e2940",
        borderRadius: "12px",
        padding: "20px",
        marginBottom: "16px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          marginBottom: "16px",
        }}
      >
        {Icon && (
          <Icon
            style={{ width: "18px", height: "18px", color: "#60a5fa" }}
          />
        )}
        <h2
          style={{
            fontSize: "14px",
            fontWeight: 600,
            color: "#93c5fd",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            margin: 0,
          }}
        >
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

function InfoRow({ label, value }) {
  if (value == null) return null;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        paddingBottom: "8px",
        borderBottom: "1px solid #1e2940",
        marginBottom: "8px",
      }}
    >
      <span style={{ fontSize: "13px", color: "#94a3b8" }}>{label}</span>
      <span style={{ fontSize: "13px", color: "#e2e8f0", fontWeight: 500 }}>
        {value}
      </span>
    </div>
  );
}

function GoalBlock({ goal, t }) {
  const goalTypeKey = `goalType_${goal.goal_type?.toLowerCase()}`;
  const goalTypeLabel = t(`trainingV2.${goalTypeKey}`) !== `trainingV2.${goalTypeKey}`
    ? t(`trainingV2.${goalTypeKey}`)
    : goal.goal_type;

  return (
    <SectionCard title={t("trainingV2.goalSection")} icon={Trophy}>
      <InfoRow label={t("trainingV2.goalType")} value={goalTypeLabel} />
      {goal.race_date != null && (
        <InfoRow label={t("trainingV2.raceDate")} value={goal.race_date} />
      )}
      {goal.target_time_seconds != null && (
        <InfoRow
          label={t("trainingV2.targetTime")}
          value={formatSeconds(goal.target_time_seconds)}
        />
      )}
    </SectionCard>
  );
}

function StateSectionBlock({ state, weeklyTarget, t, unitSystem }) {
  const continuityMap = {
    no_history: t("trainingV2.continuityNoHistory"),
    deep_reprise: t("trainingV2.continuityDeepReprise"),
    partial_reprise: t("trainingV2.continuityPartialReprise"),
    reprise_exit: t("trainingV2.continuityRepriseExit"),
    normal: t("trainingV2.continuityNormal"),
  };

  const confidenceMap = {
    none: t("trainingV2.confidenceNone"),
    low: t("trainingV2.confidenceLow"),
    medium: t("trainingV2.confidenceMedium"),
    high: t("trainingV2.confidenceHigh"),
  };

  const basisLabel =
    weeklyTarget.target_basis === "distance"
      ? t("trainingV2.basisDistance")
      : t("trainingV2.basisDuration");

  return (
    <SectionCard title={t("trainingV2.stateSection")} icon={Target}>
      <InfoRow
        label={t("trainingV2.continuityState")}
        value={continuityMap[state.continuity_state] || state.continuity_state}
      />
      <InfoRow
        label={t("trainingV2.allowIntensity")}
        value={state.allow_intensity ? t("trainingV2.intensityYes") : t("trainingV2.intensityNo")}
      />
      <InfoRow label={t("trainingV2.targetBasis")} value={basisLabel} />
      {weeklyTarget.target_km != null && (
        <InfoRow
          label={t("trainingV2.targetKm")}
          value={formatDistance(weeklyTarget.target_km, { unitSystem })}
        />
      )}
      {weeklyTarget.target_duration_minutes != null && (
        <InfoRow
          label={t("trainingV2.targetDuration")}
          value={`${weeklyTarget.target_duration_minutes} ${t("trainingV2.minutes")}`}
        />
      )}
      <InfoRow
        label={t("trainingV2.sessionCount")}
        value={weeklyTarget.session_count}
      />
      <InfoRow
        label={t("trainingV2.confidence")}
        value={confidenceMap[weeklyTarget.confidence] || weeklyTarget.confidence}
      />
    </SectionCard>
  );
}

function SessionCard({ session, t, unitSystem }) {
  const style = getWorkoutStyle(session.workout_type);
  const Icon = style.icon;

  const workoutLabelKey = `workout${session.workout_type.charAt(0).toUpperCase()}${session.workout_type.slice(1).replace(/_([a-z])/g, (_, c) => c.toUpperCase())}`;
  const workoutLabel =
    t(`trainingV2.${workoutLabelKey}`) !== `trainingV2.${workoutLabelKey}`
      ? t(`trainingV2.${workoutLabelKey}`)
      : session.workout_type;

  const intensityLabelKey = `intensity${session.intensity_class.charAt(0).toUpperCase()}${session.intensity_class.slice(1)}`;
  const intensityLabel =
    t(`trainingV2.${intensityLabelKey}`) !== `trainingV2.${intensityLabelKey}`
      ? t(`trainingV2.${intensityLabelKey}`)
      : session.intensity_class;

  const dayLabelKey = `trainingPlanDays.${session.day}`;
  const dayLabel =
    t(dayLabelKey) !== dayLabelKey ? t(dayLabelKey) : session.day;

  return (
    <div
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
        borderRadius: "10px",
        padding: "14px 16px",
        marginBottom: "10px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Icon style={{ width: "16px", height: "16px", color: style.text }} />
          <span
            style={{ fontSize: "13px", fontWeight: 600, color: style.text }}
          >
            {dayLabel}
          </span>
        </div>
        <span
          style={{
            background: style.badge,
            color: style.badgeText,
            fontSize: "11px",
            fontWeight: 600,
            padding: "2px 8px",
            borderRadius: "4px",
            textTransform: "uppercase",
          }}
        >
          {workoutLabel}
        </span>
      </div>

      <div
        style={{
          display: "flex",
          gap: "12px",
          flexWrap: "wrap",
          fontSize: "12px",
          color: "#94a3b8",
        }}
      >
        <span>{intensityLabel}</span>
        {session.distance_km != null && (
          <span>{formatDistance(session.distance_km, { unitSystem })}</span>
        )}
        {session.duration_minutes != null && (
          <span>
            {session.duration_minutes} {t("trainingV2.minutes")}
          </span>
        )}
        {session.estimated_tss != null && (
          <span>{session.estimated_tss} {t("trainingV2.tss")}</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function TrainingPlanV2() {
  const { t } = useLanguage();
  const { isFree, isTrial, isPremium, loading: subLoading } = useSubscription();
  const { unitSystem } = useUnitSystem();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchWeek = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/training/v2/week`);
      setData(res.data);
    } catch (err) {
      setError(err?.response?.data?.detail || t("trainingV2.loadingError"));
      toast.error(t("trainingV2.loadingError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchWeek();
  }, [fetchWeek]);

  // Subscription guard — mirrors TrainingPlan pattern
  if (subLoading) {
    return (
      <div style={{ maxWidth: "640px", margin: "0 auto", padding: "20px 16px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          <Skeleton style={{ height: "120px", borderRadius: "12px" }} />
          <Skeleton style={{ height: "160px", borderRadius: "12px" }} />
          <Skeleton style={{ height: "200px", borderRadius: "12px" }} />
        </div>
      </div>
    );
  }

  if (isFree) {
    return <Paywall />;
  }

  return (
    <div
      style={{
        maxWidth: "640px",
        margin: "0 auto",
        padding: "20px 16px",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "20px",
        }}
      >
        <h1
          style={{
            fontSize: "20px",
            fontWeight: 700,
            color: "#e2e8f0",
            margin: 0,
          }}
        >
          {t("trainingV2.title")}
        </h1>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchWeek}
          disabled={loading}
          style={{ gap: "6px" }}
        >
          <RefreshCw
            style={{
              width: "14px",
              height: "14px",
              ...(loading ? { animation: "spin 1s linear infinite" } : {}),
            }}
          />
          {t("trainingV2.refresh")}
        </Button>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          <Skeleton style={{ height: "120px", borderRadius: "12px" }} />
          <Skeleton style={{ height: "160px", borderRadius: "12px" }} />
          <Skeleton style={{ height: "200px", borderRadius: "12px" }} />
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div
          style={{
            background: "#1c0a0a",
            border: "1px solid #ef4444",
            borderRadius: "10px",
            padding: "20px",
            textAlign: "center",
          }}
        >
          <p style={{ color: "#fca5a5", marginBottom: "12px" }}>{error}</p>
          <Button variant="outline" onClick={fetchWeek}>
            {t("trainingV2.retry")}
          </Button>
        </div>
      )}

      {/* Content */}
      {!loading && !error && data && (
        <>
          {/* Block 1: Goal */}
          <GoalBlock goal={data.goal} t={t} />

          {/* Block 2: State + Weekly Target */}
          <StateSectionBlock
            state={data.state}
            weeklyTarget={data.weekly_target}
            t={t}
            unitSystem={unitSystem}
          />

          {/* Block 3: Sessions */}
          <SectionCard title={t("trainingV2.sessionsSection")} icon={Calendar}>
            {data.week.sessions.length === 0 ? (
              <p style={{ color: "#64748b", fontSize: "13px" }}>
                {t("trainingV2.noSessions")}
              </p>
            ) : (
              data.week.sessions.map((session, idx) => (
                <SessionCard
                  key={idx}
                  session={session}
                  t={t}
                  unitSystem={unitSystem}
                />
              ))
            )}
          </SectionCard>
        </>
      )}
    </div>
  );
}

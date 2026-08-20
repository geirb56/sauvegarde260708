import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import Paywall from "@/components/Paywall";
import { toast } from "sonner";
import { Calendar, RefreshCw, ShieldCheck, Target, TrendingUp } from "lucide-react";
import { API_BASE_URL } from "@/config";
import { formatDistance } from "@/utils/units";

const API = API_BASE_URL;

const SESSION_STYLES = {
  rest: { bg: "#12142a", border: "#4f46e5", text: "#a5b4fc", badge: "#4f46e5", badgeText: "#ffffff" },
  recovery: { bg: "#0b1a1a", border: "#22d3ee", text: "#a5f3fc", badge: "#0891b2", badgeText: "#ffffff" },
  easy: { bg: "#0b1a12", border: "#10b981", text: "#6ee7b7", badge: "#10b981", badgeText: "#0b1a12" },
  steady: { bg: "#1c1207", border: "#f59e0b", text: "#fcd34d", badge: "#d97706", badgeText: "#ffffff" },
  quality: { bg: "#1c1207", border: "#f97316", text: "#fed7aa", badge: "#ea580c", badgeText: "#ffffff" },
  long_easy: { bg: "#0d1321", border: "#3b82f6", text: "#93c5fd", badge: "#2563eb", badgeText: "#ffffff" }
};

const fallbackLabel = (value) =>
  (value || "")
    .split("_")
    .filter(Boolean)
    .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
    .join(" ");

const typeTranslationKey = (workoutType) => {
  switch (workoutType) {
    case "long_easy":
      return "long_run";
    case "quality":
      return "intervals";
    case "steady":
      return "tempo";
    default:
      return workoutType;
  }
};

const isMissingTranslation = (value, key) =>
  !value || value === key || value === `[[${key}]]`;

export default function TrainingPlanV2() {
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const { isFree, loading: subLoading } = useSubscription();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [apiError, setApiError] = useState(null);
  const [weekPayload, setWeekPayload] = useState(null);
  const isMountedRef = useRef(true);

  const fetchWeek = useCallback(async () => {
    if (isMountedRef.current) {
      setApiError(null);
    }
    try {
      const res = await axios.get(`${API}/training/v2/week`);
      if (!isMountedRef.current) return;
      setWeekPayload(res.data);
      setApiError(null);
    } catch (err) {
      if (!isMountedRef.current) return;
      if (err.response?.status === 403 && err.response?.data?.error === "subscription_required") {
        setApiError("subscription_required");
        return;
      }
      setApiError(err.response?.data?.detail || t("trainingPlanExtended.loadingError"));
      toast.error(t("trainingPlanExtended.loadingError"));
    } finally {
      if (!isMountedRef.current) return;
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    isMountedRef.current = true;
    fetchWeek();
    return () => {
      isMountedRef.current = false;
    };
  }, [fetchWeek]);

  const sessions = weekPayload?.week?.sessions || [];
  const weeklyTarget = weekPayload?.weekly_target || {};
  const week = weekPayload?.week || {};
  const state = weekPayload?.state || {};

  const targetSummary = useMemo(() => {
    if (weeklyTarget.target_basis === "distance") {
      return weeklyTarget.target_km == null
        ? "—"
        : formatDistance(weeklyTarget.target_km, { unitSystem });
    }
    if (weeklyTarget.target_basis === "duration") {
      return weeklyTarget.target_duration_minutes == null ? "—" : `${weeklyTarget.target_duration_minutes} min`;
    }
    return "—";
  }, [unitSystem, weeklyTarget.target_basis, weeklyTarget.target_duration_minutes, weeklyTarget.target_km]);

  const plannedSummary = useMemo(() => {
    if (weeklyTarget.target_basis === "distance") {
      return week.planned_km == null ? "—" : formatDistance(week.planned_km, { unitSystem });
    }
    if (weeklyTarget.target_basis === "duration") {
      return week.planned_duration_minutes == null ? "—" : `${week.planned_duration_minutes} min`;
    }
    return "—";
  }, [unitSystem, week.planned_duration_minutes, week.planned_km, weeklyTarget.target_basis]);

  if (loading || subLoading) {
    return (
      <div className="p-4 space-y-4" style={{ background: "var(--bg-primary)", minHeight: "100vh" }}>
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-2 gap-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (isFree || apiError === "subscription_required") {
    return <Paywall language={lang} returnPath="/training-v2" />;
  }

  return (
    <div className="p-4 pb-24 space-y-4" style={{ background: "var(--bg-primary)" }} data-testid="training-plan-v2-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold uppercase tracking-tight text-white">{t("trainingPlanV2.title")}</h1>
          <p className="text-sm font-mono" style={{ color: "var(--text-tertiary)" }}>
            {t("trainingPlanV2.currentWeekOnly")}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setRefreshing(true);
            fetchWeek();
          }}
          disabled={refreshing}
          className="border-slate-600 text-slate-300 hover:bg-slate-700"
          data-testid="refresh-training-v2-btn"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
          {t("trainingPlanExtended.refresh")}
        </Button>
      </div>

      {apiError && apiError !== "subscription_required" && (
        <div className="card-modern p-4" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.35)", borderRadius: "16px" }}>
          <p className="text-sm text-red-300">{String(apiError)}</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="p-4 rounded-2xl" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}>
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-4 h-4" style={{ color: "var(--accent-green)" }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{t("trainingPlanV2.target")}</span>
          </div>
          <div className="text-2xl font-bold text-white">{targetSummary}</div>
          <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>{weeklyTarget.target_basis || "—"}</p>
        </div>
        <div className="p-4 rounded-2xl" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}>
          <div className="flex items-center gap-2 mb-2">
            <Calendar className="w-4 h-4" style={{ color: "#60a5fa" }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{t("trainingPlanV2.planned")}</span>
          </div>
          <div className="text-2xl font-bold text-white">{plannedSummary}</div>
          <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
            {(week.session_count ?? 0)} {t("trainingPlanV2.sessions")}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="p-4 rounded-2xl" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}>
          <div className="flex items-center gap-2 mb-2">
            <ShieldCheck className="w-4 h-4" style={{ color: "#34d399" }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{t("trainingPlanV2.state")}</span>
          </div>
          <div className="text-sm font-semibold text-white">{state.continuity_state || "—"}</div>
          <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
            {t("trainingPlanV2.intensity")}: {state.allow_intensity ? t("trainingPlanV2.on") : t("trainingPlanV2.off")}
          </p>
        </div>
        <div className="p-4 rounded-2xl" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}>
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4" style={{ color: "#fbbf24" }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{t("trainingPlanV2.confidence")}</span>
          </div>
          <div className="text-sm font-semibold text-white">{weeklyTarget.confidence || "—"}</div>
          <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
            {(weeklyTarget.session_count ?? 0)} {t("trainingPlanV2.recommended")}
          </p>
        </div>
      </div>

      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center gap-2 mb-3">
          <Calendar className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
          <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>{t("trainingPlanExtended.weekDetails")}</span>
        </div>

        <div className="space-y-2">
          {sessions.map((session) => {
            const style = SESSION_STYLES[session.workout_type] || SESSION_STYLES.easy;
            const workoutTranslationKey = `trainingPlanSessionType.${typeTranslationKey(session.workout_type)}`;
            const dayTranslationKey = `trainingPlanDays.${session.day}`;
            const translatedType = t(workoutTranslationKey);
            const dayLabel = t(dayTranslationKey);
            const workoutLabel = isMissingTranslation(translatedType, workoutTranslationKey)
              ? fallbackLabel(session.workout_type)
              : translatedType;
            const safeDayLabel = isMissingTranslation(dayLabel, dayTranslationKey)
              ? fallbackLabel(session.day)
              : dayLabel;
            const sessionKey = `${session.day}-${session.workout_type}-${session.intensity_class}-${session.distance_km ?? "na"}-${session.duration_minutes ?? "na"}-${(session.reason_codes || []).join("-")}`;

            return (
              <div key={sessionKey} className="flex items-center gap-2 p-3 rounded-lg" style={{ background: style.bg, border: `1px solid ${style.border}` }}>
                <div className="w-1 h-10 rounded-full shrink-0" style={{ background: style.border }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold" style={{ color: style.text }}>{safeDayLabel}</span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: style.badge, color: style.badgeText }}>{workoutLabel}</span>
                  </div>
                  <div className="text-[11px] mt-1" style={{ color: style.text, opacity: 0.8 }}>
                    {session.distance_km != null
                      ? formatDistance(session.distance_km, { unitSystem })
                      : session.duration_minutes != null
                        ? `${session.duration_minutes} min`
                        : "—"}
                    {session.intensity_class ? ` • ${session.intensity_class}` : ""}
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold shrink-0" style={{ background: style.badge, color: style.badgeText }}>
                  {session.estimated_tss == null ? "—" : `${session.estimated_tss} TSS`}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

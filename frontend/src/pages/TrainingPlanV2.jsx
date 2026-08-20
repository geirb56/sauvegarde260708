import { useState, useEffect } from "react";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  RefreshCw,
  Calendar,
  Clock,
  Zap,
  Activity,
  Heart,
  Trophy,
  Sprout,
  Target,
  ChevronRight,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import axios from "axios";
import Paywall from "@/components/Paywall";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

// ── Helpers ─────────────────────────────────────────────────────────────────

const formatDateDMY = (dateStr) => {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
};

const formatTargetTime = (seconds) => {
  if (!seconds) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
};

// Map V2 workout_type → visual style key
const V2_TYPE_STYLE = {
  rest: "repos",
  recovery: "recuperation",
  easy: "endurance",
  steady: "seuil",
  quality: "fractionne",
  long_easy: "sortie_longue",
};

// Dark-theme palette consistent with RunIndex
const SESSION_STYLES = {
  repos: {
    bg: "#12142a",
    border: "#4f46e5",
    text: "#a5b4fc",
    badge: "#4f46e5",
    badgeText: "#ffffff",
    label: "Repos",
  },
  recuperation: {
    bg: "#0b1a1a",
    border: "#22d3ee",
    text: "#a5f3fc",
    badge: "#0891b2",
    badgeText: "#ffffff",
    label: "Récupération",
  },
  endurance: {
    bg: "#0b1a12",
    border: "#10b981",
    text: "#6ee7b7",
    badge: "#10b981",
    badgeText: "#0b1a12",
    label: "Endurance",
  },
  seuil: {
    bg: "#1c1207",
    border: "#f97316",
    text: "#fed7aa",
    badge: "#f97316",
    badgeText: "#1c1207",
    label: "Seuil",
  },
  fractionne: {
    bg: "#1c1207",
    border: "#f97316",
    text: "#fed7aa",
    badge: "#ea580c",
    badgeText: "#ffffff",
    label: "Fractionné",
  },
  sortie_longue: {
    bg: "#0d1321",
    border: "#3b82f6",
    text: "#93c5fd",
    badge: "#2563eb",
    badgeText: "#ffffff",
    label: "Sortie longue",
  },
};

const getStyleKey = (workoutType) =>
  V2_TYPE_STYLE[workoutType] || "endurance";

// Intensity badge colours
const INTENSITY_COLORS = {
  rest: { bg: "#4f46e520", text: "#a5b4fc" },
  low: { bg: "#10b98120", text: "#6ee7b7" },
  moderate: { bg: "#f9731620", text: "#fed7aa" },
  high: { bg: "#ef444420", text: "#fca5a5" },
};

// Continuity state display
const STATE_META = {
  no_history: { color: "#6b7280", label: "Nouveau" },
  deep_reprise: { color: "#34d399", label: "Reprise profonde" },
  partial_reprise: { color: "#fbbf24", label: "Reprise partielle" },
  reprise_exit: { color: "#60a5fa", label: "Sortie de reprise" },
  normal: { color: "#22c55e", label: "Normal" },
};

const CONFIDENCE_META = {
  none: { color: "#6b7280", label: "Insuffisant" },
  low: { color: "#f59e0b", label: "Faible" },
  medium: { color: "#60a5fa", label: "Moyen" },
  high: { color: "#22c55e", label: "Élevé" },
};

// ── Day label (short) ────────────────────────────────────────────────────────

const DAY_SHORT = {
  monday: "Lun",
  tuesday: "Mar",
  wednesday: "Mer",
  thursday: "Jeu",
  friday: "Ven",
  saturday: "Sam",
  sunday: "Dim",
};

// ── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, sub, accentColor, delay = 0 }) {
  return (
    <div
      className="p-4 rounded-2xl animate-in"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border-color)",
        animationDelay: `${delay}ms`,
      }}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4" style={{ color: accentColor || "var(--text-tertiary)" }} />
        <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
          {label}
        </span>
      </div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {sub && (
        <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
          {sub}
        </p>
      )}
    </div>
  );
}

function SessionRow({ session, idx }) {
  const styleKey = getStyleKey(session.workout_type);
  const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
  const intensityMeta = INTENSITY_COLORS[session.intensity_class] || INTENSITY_COLORS.low;
  const isRest = session.workout_type === "rest";
  const dayLabel = DAY_SHORT[session.day] || session.day;

  return (
    <div
      className="flex items-center gap-3 p-3 rounded-xl transition-all"
      style={{
        background: style.bg,
        border: `1.5px solid ${style.border}`,
        animationDelay: `${idx * 30}ms`,
      }}
    >
      {/* Day pill */}
      <div
        className="w-10 h-10 rounded-xl flex flex-col items-center justify-center shrink-0 text-[10px] font-bold uppercase"
        style={{ background: `${style.border}20`, color: style.text }}
      >
        {dayLabel}
      </div>

      {/* Colour bar */}
      <div
        className="w-1 self-stretch rounded-full shrink-0"
        style={{ background: style.border, minHeight: "32px" }}
      />

      {/* Main info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold" style={{ color: style.text }}>
            {style.label}
          </span>
          {!isRest && session.intensity_class !== "rest" && (
            <span
              className="px-2 py-0.5 rounded-full text-[10px] font-medium"
              style={{ background: intensityMeta.bg, color: intensityMeta.text }}
            >
              {session.intensity_class}
            </span>
          )}
        </div>
        {!isRest && (
          <div className="flex items-center gap-2 mt-0.5 text-xs" style={{ color: style.text, opacity: 0.75 }}>
            {session.distance_km != null && (
              <span>{session.distance_km.toFixed(1)} km</span>
            )}
            {session.distance_km != null && session.duration_minutes != null && (
              <span>·</span>
            )}
            {session.duration_minutes != null && (
              <span>{session.duration_minutes} min</span>
            )}
          </div>
        )}
      </div>

      {/* TSS badge — rest = 0, active = null (not yet computed) */}
      <div className="shrink-0 text-right">
        {session.estimated_tss !== null && session.estimated_tss !== undefined ? (
          <span
            className="px-2 py-1 rounded-full text-xs font-bold"
            style={{ background: style.badge, color: style.badgeText }}
          >
            {session.estimated_tss} TSS
          </span>
        ) : (
          <span
            className="px-2 py-1 rounded-full text-xs font-medium"
            style={{ background: "var(--bg-secondary)", color: "var(--text-tertiary)" }}
          >
            — TSS
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function TrainingPlanV2() {
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const { isFree, loading: subLoading, trialDaysRemaining, isTrial } = useSubscription();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [apiError, setApiError] = useState(null);

  const fetchData = async () => {
    try {
      const res = await axios.get(`${API}/training/v2/week`);
      setData(res.data);
      setApiError(null);
    } catch (err) {
      if (err.response?.status === 403 && err.response?.data?.error === "subscription_required") {
        setApiError("subscription_required");
      } else {
        toast.error("Impossible de charger le plan d'entraînement");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetchData();
      toast.success("Plan mis à jour");
    } finally {
      setRefreshing(false);
    }
  };

  // ── Loading ──────────────────────────────────────────────────────────────

  if (loading || subLoading) {
    return (
      <div className="p-4 space-y-4" style={{ background: "var(--bg-primary)", minHeight: "100vh" }}>
        <Skeleton className="h-10 w-48" />
        <div className="grid grid-cols-2 gap-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-6 w-32" />
        <div className="space-y-2">
          {[1, 2, 3, 4, 5, 6, 7].map((i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      </div>
    );
  }

  // ── Paywall ──────────────────────────────────────────────────────────────

  if (isFree || apiError === "subscription_required") {
    return <Paywall language={lang} returnPath="/training-v2" />;
  }

  // ── Data aliases ─────────────────────────────────────────────────────────

  const goal = data?.goal || {};
  const state = data?.state || {};
  const target = data?.weekly_target || {};
  const week = data?.week || {};
  const sessions = week.sessions || [];

  const stateMeta = STATE_META[state.continuity_state] || STATE_META.normal;
  const confidenceMeta = CONFIDENCE_META[target.confidence] || CONFIDENCE_META.medium;

  const isReprise =
    state.continuity_state === "deep_reprise" ||
    state.continuity_state === "partial_reprise";

  const targetDisplay =
    target.target_basis === "duration"
      ? target.target_duration_minutes != null
        ? `${target.target_duration_minutes} min`
        : "—"
      : target.target_km != null
      ? formatDistance(target.target_km * 1000, { unitSystem })
      : "—";

  const plannedDisplay =
    target.target_basis === "duration"
      ? week.planned_duration_minutes != null
        ? `${week.planned_duration_minutes} min`
        : "—"
      : week.planned_km != null
      ? formatDistance(week.planned_km * 1000, { unitSystem })
      : "—";

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div
      className="p-4 pb-24 space-y-4"
      style={{ background: "var(--bg-primary)" }}
      data-testid="training-plan-v2-page"
    >
      {/* Trial banner */}
      {isTrial && trialDaysRemaining != null && (
        <div
          className="p-3 rounded-xl flex items-center justify-between"
          style={{
            background: "rgba(59,130,246,0.1)",
            border: "1px solid rgba(59,130,246,0.3)",
          }}
        >
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-blue-400" />
            <span className="text-sm text-blue-300">
              {trialDaysRemaining === 1
                ? t("trainingPlanExtended.trialBannerOne")
                : t("trainingPlanExtended.trialBanner").replace("{days}", trialDaysRemaining)}
            </span>
          </div>
          <a
            href="/settings"
            className="text-xs font-medium px-3 py-1 rounded-full"
            style={{ background: "rgba(59,130,246,0.3)", color: "#93c5fd" }}
          >
            {t("trainingPlanExtended.subscribe")}
          </a>
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold uppercase tracking-tight text-white">
              {t("trainingPlanExtended.planTitle")}
            </h1>
            <span
              className="px-2 py-0.5 rounded-full text-[10px] font-bold"
              style={{ background: "rgba(110,235,90,0.15)", color: "#6EEB5A", border: "1px solid rgba(110,235,90,0.3)" }}
            >
              V2
            </span>
          </div>
          <p className="text-sm font-mono mt-0.5 flex items-center gap-2" style={{ color: "var(--text-tertiary)" }}>
            <span className="capitalize">{goal.goal_type || "—"}</span>
            {goal.race_date && (
              <>
                <span>·</span>
                <span>{formatDateDMY(goal.race_date)}</span>
              </>
            )}
            {goal.target_time_seconds && (
              <>
                <span>·</span>
                <span>Obj. {formatTargetTime(goal.target_time_seconds)}</span>
              </>
            )}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="border-slate-600 text-slate-300 hover:bg-slate-700"
          data-testid="refresh-plan-v2-btn"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
          {t("trainingPlanExtended.refresh")}
        </Button>
      </div>

      {/* Reprise banner */}
      {isReprise && (
        <div
          className="p-4 rounded-2xl"
          style={{
            background: "rgba(16,185,129,0.08)",
            border: "1px solid rgba(16,185,129,0.35)",
          }}
          data-testid="v2-reprise-banner"
        >
          <div className="flex items-start gap-3">
            <Sprout className="w-5 h-5 mt-0.5 shrink-0" style={{ color: "#34d399" }} />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-white">
                  {t("trainingPlanExtended.repriseTitle")}
                </span>
                <span
                  className="px-2 py-0.5 rounded-full text-[10px] font-bold"
                  style={{ background: "#10b98120", color: "#6ee7b7", border: "1px solid #10b981" }}
                >
                  {state.continuity_state === "deep_reprise"
                    ? t("trainingPlanExtended.repriseBadgeDeep")
                    : t("trainingPlanExtended.repriseBadgePartial")}
                </span>
              </div>
              <p className="text-sm mt-1" style={{ color: "var(--text-tertiary)" }}>
                {state.continuity_state === "deep_reprise"
                  ? t("trainingPlanExtended.repriseDescDeep")
                  : t("trainingPlanExtended.repriseDescPartial")}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Intensity lock banner */}
      {!state.allow_intensity && !isReprise && (
        <div
          className="p-3 rounded-xl flex items-center gap-3"
          style={{ background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)" }}
        >
          <AlertCircle className="w-4 h-4 shrink-0" style={{ color: "#fbbf24" }} />
          <span className="text-sm" style={{ color: "#fde68a" }}>
            Séances faciles uniquement cette semaine — récupération prioritaire
          </span>
        </div>
      )}

      {/* Stats row: planned vs target */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          icon={Target}
          label="Objectif semaine"
          value={targetDisplay}
          sub={`${target.session_count || "—"} séances prévues`}
          accentColor="var(--accent-green)"
          delay={50}
        />
        <StatCard
          icon={Activity}
          label="Planifié"
          value={plannedDisplay}
          sub={`${week.session_count || 0} séances`}
          accentColor="var(--accent-pink)"
          delay={100}
        />
      </div>

      {/* Confidence + state row */}
      <div className="grid grid-cols-2 gap-3">
        <div
          className="p-4 rounded-2xl"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}
        >
          <div className="flex items-center gap-2 mb-1">
            <Zap className="w-4 h-4" style={{ color: confidenceMeta.color }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
              Confiance
            </span>
          </div>
          <span className="text-sm font-bold" style={{ color: confidenceMeta.color }}>
            {confidenceMeta.label}
          </span>
        </div>
        <div
          className="p-4 rounded-2xl"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}
        >
          <div className="flex items-center gap-2 mb-1">
            <Heart className="w-4 h-4" style={{ color: stateMeta.color }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
              État
            </span>
          </div>
          <span className="text-sm font-bold" style={{ color: stateMeta.color }}>
            {stateMeta.label}
          </span>
        </div>
      </div>

      {/* Sessions list */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}
      >
        {/* Section header */}
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: "1px solid var(--border-color)" }}
        >
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
              Semaine courante
            </span>
          </div>
          {data?.reference_date && (
            <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
              Ref. {formatDateDMY(data.reference_date)}
            </span>
          )}
        </div>

        {/* Session rows */}
        <div className="p-3 space-y-2">
          {sessions.length === 0 ? (
            <div className="text-center py-8" style={{ color: "var(--text-tertiary)" }}>
              <Trophy className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p className="text-sm">Aucune séance planifiée</p>
            </div>
          ) : (
            sessions.map((session, idx) => (
              <SessionRow key={`${session.day}-${idx}`} session={session} idx={idx} />
            ))
          )}
        </div>
      </div>

      {/* V2 footnote */}
      <div className="flex items-center gap-2 px-1">
        <CheckCircle2 className="w-3 h-3" style={{ color: "var(--text-tertiary)" }} />
        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
          Moteur V2 — UNKNOWN ≠ ZERO — TSS actif null, repos 0
        </span>
      </div>
    </div>
  );
}

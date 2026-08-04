import { useState, useEffect, useRef, useCallback } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import {
  Zap,
  RefreshCw,
  Loader2,
  Heart,
  Timer,
  Activity,
  Moon,
  BarChart2,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Check,
  X,
  TrendingUp,
  Target,
  Info,
} from "lucide-react";
import {
  BarChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useUnitSystem } from "@/context/UnitContext";
import { Button } from "@/components/ui/button";
import { BrandSplash } from "@/components/LoadingSpinner";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

// ─── Run Recommendation thresholds ──────────────────────────────────────────
const FATIGUE_REST_THRESHOLD = 1.5;
const FATIGUE_EASY_THRESHOLD = 1.2;
const LOAD_OPTIMAL_MIN = 0.8;
const LOAD_OPTIMAL_MAX = 1.3;

const STATUS_COLORS = {
  green: { bg: "#22c55e20", text: "#22c55e", border: "#22c55e40" },
  yellow: { bg: "#f59e0b20", text: "#f59e0b", border: "#f59e0b40" },
  red: { bg: "#ef444420", text: "#ef4444", border: "#ef444440" },
};

const REC_STYLES = {
  green: {
    bg: "linear-gradient(135deg, #052e16 0%, #14532d 100%)",
    accent: "#22c55e",
    button: "#22c55e",
    buttonHover: "#16a34a",
  },
  yellow: {
    bg: "linear-gradient(135deg, #1c1003 0%, #451a03 100%)",
    accent: "#f59e0b",
    button: "#d97706",
    buttonHover: "#b45309",
  },
  red: {
    bg: "linear-gradient(135deg, #1c0202 0%, #450a0a 100%)",
    accent: "#ef4444",
    button: "#ef4444",
    buttonHover: "#dc2626",
  },
};

// Couleurs pour les séances — dark theme (même style que TrainingPlan)
const SESSION_STYLES = {
  repos: {
    bg: "#12142a",
    border: "#4f46e5",
    text: "#a5b4fc",
    badge: "#4f46e5",
    badgeText: "#ffffff"
  },
  endurance: {
    bg: "#0b1a12",
    border: "#10b981",
    text: "#6ee7b7",
    badge: "#10b981",
    badgeText: "#0b1a12"
  },
  seuil: {
    bg: "#1c1207",
    border: "#f97316",
    text: "#fed7aa",
    badge: "#f97316",
    badgeText: "#1c1207"
  },
  recuperation: {
    bg: "#0b1a1a",
    border: "#22d3ee",
    text: "#a5f3fc",
    badge: "#0891b2",
    badgeText: "#ffffff"
  },
  sortie_longue: {
    bg: "#0d1321",
    border: "#3b82f6",
    text: "#93c5fd",
    badge: "#2563eb",
    badgeText: "#ffffff"
  },
  fractionne: {
    bg: "#1c1207",
    border: "#f97316",
    text: "#fed7aa",
    badge: "#ea580c",
    badgeText: "#ffffff"
  },
};

const getSessionStyleKey = (type, intensity) => {
  const typeLower = (type && typeof type === "string" ? type : "").toLowerCase();
  
  if (typeLower.includes("repos") || typeLower === "rest") return "repos";
  if (typeLower.includes("endurance") || typeLower === "easy" || typeLower === "short_easy" || typeLower === "easy_run") return "endurance";
  if (typeLower.includes("seuil") || typeLower.includes("threshold") || typeLower === "tempo") return "seuil";
  if (typeLower.includes("récup") || typeLower.includes("recup") || typeLower === "recovery" || typeLower === "activation") return "recuperation";
  if (typeLower.includes("sortie longue") || typeLower === "long_run" || typeLower.includes("long")) return "sortie_longue";
  if (typeLower.includes("fractionn") || typeLower.includes("interval") || typeLower === "fartlek" || typeLower === "speed_reminder" || typeLower === "race") return "fractionne";
  
  return intensity || "endurance";
};

// SessionCard component for displaying a session with colors
function SessionCard({ session, isGrayed = false, fatigueColor = null }) {
  const { t } = useLanguage();
  if (!session) return null;

  const styleKey = getSessionStyleKey(session.type, session.intensity);
  const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
  const isRest = styleKey === "repos";

  const borderColor = fatigueColor
    ? (fatigueColor === "green" ? "#10b981" : fatigueColor === "yellow" ? "#f59e0b" : "#ef4444")
    : style.border;

  return (
    <div
      className={`flex items-center gap-2 p-3 rounded-lg ${isGrayed ? "opacity-50" : ""}`}
      style={{
        background: style.bg,
        border: `2px solid ${borderColor}`
      }}
    >
      <div
        className="w-1 h-10 rounded-full shrink-0"
        style={{ background: borderColor }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-bold" style={{ color: style.text }}>
            {t(`trainingPlanSessionType.${session.type}`) || session.type}
          </span>
          <span className="text-xs" style={{ color: style.text, opacity: 0.8 }}>
            {session.duration}
          </span>
        </div>
        {!isRest && session.details && (
          <span className="text-xs block" style={{ color: style.text, opacity: 0.7 }}>
            {session.details}
          </span>
        )}
      </div>
      <span
        className="px-2 py-1 rounded-full text-xs font-bold shrink-0"
        style={{ background: style.badge, color: style.badgeText }}
      >
        {session.estimated_tss || 0} TSS
      </span>
    </div>
  );
}

function StatusIcon({ status, size = 16 }) {
  if (status === "green") return <CheckCircle size={size} color="#22c55e" />;
  if (status === "yellow") return <AlertTriangle size={size} color="#f59e0b" />;
  return <XCircle size={size} color="#ef4444" />;
}

function MetricWidget({ icon: Icon, label, value, unit, status, detail }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.green;
  return (
    <div
      className="flex-shrink-0 rounded-2xl p-4 flex flex-col gap-1 w-[140px] snap-start"
      style={{ background: colors.bg, border: `1px solid ${colors.border}` }}
    >
      <div className="flex items-center justify-between">
        <Icon size={18} color={colors.text} />
        <StatusIcon status={status} size={14} />
      </div>
      <p className="text-xs font-medium mt-1" style={{ color: "var(--text-tertiary)" }}>
        {label}
      </p>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-bold" style={{ color: colors.text }}>
          {value}
        </span>
        {unit && (
          <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            {unit}
          </span>
        )}
      </div>
      {detail && (
        <p className="text-[10px] leading-tight" style={{ color: "var(--text-tertiary)" }}>
          {detail}
        </p>
      )}
    </div>
  );
}

function TrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="rounded-xl p-3 text-xs shadow-lg"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border-color)",
        color: "var(--text-primary)",
      }}
    >
      <p className="font-bold mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value}
        </p>
      ))}
    </div>
  );
}

// Workout type configuration (labels from t("workoutTypes.*"))
// Circular Gauge Component
function CircularGauge({ value, max = 100, size = 64 }) {
  const strokeWidth = 5;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = (value / max) * circumference;

  return (
    <div className="circular-gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="gauge-bg"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          className="gauge-progress"
        />
      </svg>
      <div className="gauge-text">{value}%</div>
    </div>
  );
}

function RunIndexPillar({ icon: Icon, label, value, color }) {
  const safeValue = Number.isFinite(value) ? value : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
          {Icon && <Icon className="w-4 h-4 shrink-0" style={{ color }} />}
          <span>{label}</span>
        </div>
        <span className="text-sm font-bold" style={{ color }}>
          {safeValue}%
        </span>
      </div>
      <div
        className="h-2 rounded-full overflow-hidden"
        style={{ background: "rgba(255,255,255,0.08)" }}
      >
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.max(0, Math.min(100, safeValue))}%`, background: color }}
        />
      </div>
    </div>
  );
}

// Readiness tile — compact stat card: icon + status dot + label + value (status-colored), tappable for info
function ReadinessTile({ icon: Icon, label, value, status, testId, onClick }) {
  const color = status === "yellow" ? "#f59e0b" : status === "red" ? "#ef4444" : "#22c55e";
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left rounded-2xl p-3 flex flex-col gap-2 transition-transform duration-200 hover:-translate-y-0.5 active:scale-[0.98]"
      style={{ background: `${color}12`, border: `1px solid ${color}33` }}
      data-testid={`readiness-tile-${testId}`}
    >
      <div className="flex items-center justify-between">
        {Icon && <Icon className="w-4 h-4 shrink-0" style={{ color }} />}
        <div className="flex items-center gap-1.5">
          <Info className="w-3 h-3 opacity-40" style={{ color: "var(--text-tertiary)" }} />
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
        </div>
      </div>
      <span className="text-[11px] font-medium leading-tight" style={{ color: "var(--text-tertiary)" }}>
        {label}
      </span>
      <span className="text-lg font-black leading-none" style={{ color }} data-testid={`readiness-value-${testId}`}>
        {value}
      </span>
    </button>
  );
}

// Mini Line Chart Component
function MiniLineChart({ data = [], height = 60 }) {
  if (!data.length) return null;
  
  const width = 280;
  const padding = 10;
  
  const maxVal = Math.max(...data);
  const minVal = Math.min(...data);
  const range = maxVal - minVal || 1;
  
  const points = data.map((val, i) => {
    const x = padding + (i / (data.length - 1)) * (width - 2 * padding);
    const y = height - padding - ((val - minVal) / range) * (height - 2 * padding);
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      width="100%"
      height={height}
      className="mt-2 block"
    >
      <defs>
        <linearGradient id="lineGradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="var(--accent-green)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="var(--accent-green)" />
        </linearGradient>
      </defs>
      <polyline
        points={points}
        fill="none"
        stroke="url(#lineGradient)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Dashboard() {
  const [insight, setInsight] = useState(null);
  const [todaySession, setTodaySession] = useState(null);
  const [trainingMetrics, setTrainingMetrics] = useState(null);
  const [cardioData, setCardioData] = useState(null);
  const [cardioLoading, setCardioLoading] = useState(true);
  const [cardioError, setCardioError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [sessionFeedback, setSessionFeedback] = useState({});
  const [infoMetric, setInfoMetric] = useState(null);
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const fetchedRef = useRef(false);
  const lastLangRef = useRef(lang);

  useEffect(() => {
    if (fetchedRef.current && lastLangRef.current === lang) {
      return;
    }
    fetchedRef.current = true;
    lastLangRef.current = lang;
    fetchData();
  }, [lang]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchData = async () => {
    setLoading(true);
    try {
      const [insightRes, ragRes, todayRes, metricsRes] = await Promise.all([
        axios.get(`${API}/dashboard/insight?language=${lang}`),
        axios.get(`${API}/rag/dashboard`).catch(() => ({ data: null })),
        axios.get(`${API}/training/today`).catch(() => ({ data: null })),
        axios.get(`${API}/training/metrics`).catch(() => ({ data: null }))
      ]);
      setInsight(insightRes.data);
      if (ragRes.data) {
        setInsight(prev => ({ ...prev, rag: ragRes.data }));
      }
      if (metricsRes.data) {
        setTrainingMetrics(metricsRes.data);
      }
      
      // Utiliser la réponse de /api/training/today (avec adaptation)
      if (todayRes.data?.status === "success") {
        setTodaySession(todayRes.data);
      }
    } catch (error) {
      console.error("Failed to fetch data:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (day, status) => {
    setFeedbackSubmitting(true);
    try {
      const today = new Date().toISOString().split('T')[0];
      await axios.post(
        `${API}/training/feedback`,
        null,
        { params: { date: today, workout_id: day, status } }
      );

      setSessionFeedback(prev => ({ ...prev, [day]: status }));
      toast.success(t("trainingPlanExtended.feedbackSaved") || "Feedback enregistré");
      
      // Refresh today's session
      const todayRes = await axios.get(`${API}/training/today`);
      if (todayRes.data?.status === "success") {
        setTodaySession(todayRes.data);
      }
    } catch (err) {
      console.error("Error submitting feedback:", err);
      toast.error(t("common.error") || "Erreur");
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  const fetchCardioData = useCallback(async () => {
    setCardioLoading(true);
    setCardioError(null);
    try {
      const res = await axios.get(`${API}/run-index?language=${lang}`);
      setCardioData(res.data);
    } catch (err) {
      console.error("RunIndex fetch failed:", err);
      setCardioError("Unable to load data.");
    } finally {
      setCardioLoading(false);
    }
  }, [lang]);

  useEffect(() => {
    fetchCardioData();
  }, [fetchCardioData]);

  // ACWR color helper
  const getAcwrColor = (status) => {
    switch(status) {
      case "optimal": return "#22c55e";
      case "low": return "#3b82f6";
      case "warning": return "#f59e0b";
      case "danger": return "#ef4444";
      default: return "#22c55e";
    }
  };

  // TSB color helper
  const getTsbColor = (status) => {
    switch(status) {
      case "fresh": return "#22c55e";
      case "ready": return "#3b82f6";
      case "training": return "#f59e0b";
      case "fatigued": return "#ef4444";
      default: return "#3b82f6";
    }
  };

  if (loading) {
    return <BrandSplash text={t("common.loading")} />;
  }

  const weekStats = insight?.week || { sessions: 0, volume_km: 0 };
  const monthStats = insight?.month || { volume_km: 0 };
  
  // Mock data for the chart (would come from real data)
  const chartData = [45, 48, 42, 50, 55, 58, 62, 68];
  
  // Calculate weekly progress
  const weeklyKmTarget = trainingMetrics?.load_28 ? Math.round(trainingMetrics.load_28 / 4 * 1.1) : 80;
  const weeklyProgress = Math.min(100, Math.round((weekStats.volume_km / weeklyKmTarget) * 100));
  const runIndexData = insight?.run_index;
  const runIndexScore = runIndexData?.run_index ?? 0;
  const runIndexConfidence = runIndexData?.confidence_score ?? 0;

  return (
    <div className="p-4 pb-24 space-y-4" style={{ background: "var(--bg-primary)" }}>

      {runIndexData && (
        <div
          className="rounded-3xl p-5 space-y-4 animate-in"
          style={{
            background: "linear-gradient(135deg, #0d1a10 0%, #111827 60%, #0d1a10 100%)",
            border: "1px solid rgba(110, 235, 90, 0.22)",
            boxShadow: "0 16px 40px rgba(15, 23, 42, 0.22)",
          }}
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em]" style={{ color: "#6EEB5A" }}>
                {t("dashboard.runIndex")}
              </p>
              <h2 className="text-lg font-black mt-1" style={{ color: "#ffffff" }}>
                {t("dashboard.runIndexOverall")}
              </h2>
              <p className="text-xs mt-2 max-w-md" style={{ color: "rgba(255,255,255,0.72)" }}>
                {t("dashboard.runIndexDescription")}
              </p>
            </div>
            <div className="px-3 py-1 rounded-full text-[11px] font-bold uppercase tracking-wider" style={{ background: "rgba(110, 235, 90, 0.12)", color: "#6EEB5A" }}>
              {t("progress.confidence")}: {runIndexConfidence}%
            </div>
          </div>

          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="flex items-end gap-2">
                <span className="text-6xl font-black leading-none" style={{ color: "#ffffff" }}>
                  {runIndexScore}
                </span>
                <span className="text-xl font-semibold pb-1" style={{ color: "#6EEB5A" }}>
                  / 1000
                </span>
              </div>
              <p className="text-sm mt-2" style={{ color: "rgba(255,255,255,0.72)" }}>
                {t("dashboard.runIndexLevel")}
              </p>
            </div>
          </div>

          <div className="grid gap-3">
            <RunIndexPillar icon={Zap} label={t("dashboard.runIndexPillars.speed")} value={runIndexData?.speed_score} color="#f59e0b" />
            <RunIndexPillar icon={Heart} label={t("dashboard.runIndexPillars.endurance")} value={runIndexData?.endurance_score} color="#ef4444" />
            <RunIndexPillar icon={TrendingUp} label={t("dashboard.runIndexPillars.consistency")} value={runIndexData?.consistency_score} color="#6EEB5A" />
            <RunIndexPillar icon={Target} label={t("dashboard.runIndexPillars.efficiency")} value={runIndexData?.efficiency_score} color="#3b82f6" />
          </div>
        </div>
      )}

      {/* ── RUN READINESS SECTION ────────────────────────────────────── */}
      {cardioLoading ? (
        <div
          className="flex flex-col items-center justify-center py-8 gap-3"
          data-testid="run-index-loading"
        >
          <Loader2
            className="animate-spin"
            size={28}
            style={{ color: "var(--accent-green)" }}
          />
          <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            {t("dashboard.computingReadiness")}
          </p>
        </div>
      ) : (
        <>
          {cardioError && (
            <div
              className="flex items-center gap-2 px-4 py-3 rounded-xl text-xs"
              style={{ background: "#f59e0b15", border: "1px solid #f59e0b30", color: "#f59e0b" }}
            >
              <AlertTriangle size={14} />
              <span>{cardioError}</span>
            </div>
          )}

          {/* Decision card */}
          {(() => {
            if (cardioData?.no_data || cardioData?.connected === false) {
              return (
                <div
                  className="rounded-2xl p-6 flex flex-col items-center text-center gap-3"
                  style={{ background: "var(--bg-elevated, #1a1a1f)", border: "1px solid var(--border, #2a2a30)" }}
                  data-testid="cardio-no-data"
                >
                  <Activity size={28} style={{ color: "var(--text-tertiary)" }} />
                  <p className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
                    {t("dashboard.noData", "No data yet")}
                  </p>
                  <p className="text-xs max-w-xs" style={{ color: "var(--text-tertiary)" }}>
                    {cardioData?.message || t("dashboard.connectGarminPrompt", "Connect your Garmin to see your readiness and daily metrics.")}
                  </p>
                  <Link
                    to="/onboarding"
                    className="mt-1 px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider"
                    style={{ background: "var(--accent-green)", color: "#0a0e1a" }}
                    data-testid="cardio-connect-cta"
                  >
                    {t("dashboard.connectGarmin", "Connect Garmin")}
                  </Link>
                </div>
              );
            }
            const m = cardioData?.metrics || {};
            const recStyle = REC_STYLES[cardioData?.recommendation_color] || REC_STYLES.green;
            const history = cardioData?.history || [];
            
            // Run Readiness Score — single source of truth from backend (Garmin insights)
            const runReadinessScore = m.run_readiness ?? 100;
            
            return (
              <>
                <div
                  className="rounded-3xl p-5 space-y-4 animate-in"
                  style={{
                    background: "linear-gradient(135deg, #0d1a10 0%, #111827 60%, #0d1a10 100%)",
                    border: "1px solid rgba(110, 235, 90, 0.22)",
                    boxShadow: "0 16px 40px rgba(15, 23, 42, 0.22)",
                  }}
                  data-testid="run-readiness-card"
                >
                  {/* Header — same structure as RunIndex */}
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p
                        className="text-xs font-semibold uppercase tracking-[0.22em]"
                        style={{ color: "#6EEB5A" }}
                        data-testid="run-readiness-title"
                      >
                        {t("dashboard.runReadiness")}
                      </p>
                      <h2 className="text-lg font-black mt-1" style={{ color: "#ffffff" }}>
                        {t("dashboard.runReadinessDescription")}
                      </h2>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span
                        className="px-3 py-1 rounded-full text-[11px] font-bold uppercase tracking-wider"
                        style={{ background: `${recStyle.accent}1f`, color: recStyle.accent }}
                        data-testid="run-readiness-recommendation"
                      >
                        {cardioData?.recommendation || "—"}
                      </span>
                      <button
                        onClick={fetchCardioData}
                        className="p-1 rounded-lg opacity-60 hover:opacity-100 transition-opacity"
                        aria-label="Refresh"
                        data-testid="run-readiness-refresh"
                      >
                        <RefreshCw size={14} style={{ color: recStyle.accent }} />
                      </button>
                    </div>
                  </div>

                  {/* Big score — same font as RunIndex, out of 100, white number */}
                  <div className="flex items-end gap-2">
                    <span
                      className="text-6xl font-black leading-none"
                      style={{ color: "#ffffff" }}
                      data-testid="run-readiness-score"
                    >
                      {runReadinessScore}
                    </span>
                    <span className="text-xl font-semibold pb-1" style={{ color: "#6EEB5A" }}>
                      / 100
                    </span>
                  </div>

                  {/* Component tiles — compact grid, tappable for info */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="run-readiness-pillars">
                    <ReadinessTile
                      icon={Heart}
                      label={t("dashboard.readinessPillars.hrv")}
                      value={(m.hrv_delta === undefined || m.hrv_delta === null) ? "—" : `${m.hrv_delta >= 0 ? "+" : ""}${m.hrv_delta} ms`}
                      status={m.hrv_status || "green"}
                      testId="hrv"
                      onClick={() => setInfoMetric("hrv")}
                    />
                    <ReadinessTile
                      icon={Activity}
                      label={t("dashboard.readinessPillars.rhr")}
                      value={(m.rhr_today === undefined || m.rhr_today === null) ? "—" : `${m.rhr_today} bpm`}
                      status={m.rhr_status || "green"}
                      testId="rhr"
                      onClick={() => setInfoMetric("rhr")}
                    />
                    <ReadinessTile
                      icon={Moon}
                      label={t("dashboard.readinessPillars.sleep")}
                      value={(m.sleep_hours === undefined || m.sleep_hours === null) ? "—" : `${m.sleep_hours} h`}
                      status={m.sleep_status || "green"}
                      testId="sleep"
                      onClick={() => setInfoMetric("sleep")}
                    />
                    <ReadinessTile
                      icon={BarChart2}
                      label={t("dashboard.readinessPillars.load")}
                      value={(m.training_load === undefined || m.training_load === null) ? "—" : `${m.training_load}`}
                      status={m.training_load_status || "green"}
                      testId="load"
                      onClick={() => setInfoMetric("load")}
                    />
                  </div>

                  {/* 30-day Run Readiness trend */}
                  {history.filter((h) => h.run_readiness !== undefined && h.run_readiness !== null).length >= 2 && (
                    <div className="pt-1" data-testid="readiness-trend">
                      <p className="text-[11px] uppercase tracking-wider font-semibold mb-1" style={{ color: "var(--text-tertiary)" }}>
                        {t("dashboard.monthlyReadiness")}
                      </p>
                      <MiniLineChart data={history.map((h) => h.run_readiness ?? 0)} height={110} />
                      <div className="flex justify-between mt-1">
                        <span className="text-[9px]" style={{ color: "var(--text-tertiary)" }}>
                          {history[0]?.date ? history[0].date.slice(5) : ""}
                        </span>
                        <span className="text-[9px]" style={{ color: "var(--text-tertiary)" }}>
                          {history[history.length - 1]?.date ? history[history.length - 1].date.slice(5) : ""}
                        </span>
                      </div>
                    </div>
                  )}

                  {cardioData?.mock && (
                    <p className="text-center text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                      {t("dashboard.demoDataNotice")}
                    </p>
                  )}
                </div>
              </>
            );
          })()}
        </>
      )}

      {/* TODAY'S SESSION - Interactive with Adaptation */}
      <div 
        className="today-workout-card animate-in" 
        style={{ 
          animationDelay: "200ms",
          border: todaySession?.fatigue ? `2px solid ${
            todaySession.fatigue.fatigue_status === "green" ? "#10b981" :
            todaySession.fatigue.fatigue_status === "yellow" ? "#f59e0b" : "#ef4444"
          }` : undefined
        }} 
        data-testid="today-workout-card"
      >
        <div className="flex items-center justify-between mb-3">
          <p className="today-label">{t("dashboard.todayLabel")}</p>
          {todaySession?.fatigue && (
            <span
              className="px-3 py-1 rounded-full text-xs font-bold"
              style={{
                background: todaySession.fatigue.fatigue_status === "green" ? "#10b98120" :
                           todaySession.fatigue.fatigue_status === "yellow" ? "#f59e0b20" : "#ef444420",
                color: todaySession.fatigue.fatigue_status === "green" ? "#10b981" :
                       todaySession.fatigue.fatigue_status === "yellow" ? "#f59e0b" : "#ef4444"
              }}
            >
              {todaySession.fatigue.recommendation || "RUN HARD"}
            </span>
          )}
        </div>

        {todaySession?.status === "success" ? (
          <>
            {/* Adaptation notice */}
            {todaySession.adaptation_applied && (
              <div
                className="p-2 rounded-lg text-xs mb-3"
                style={{
                  background: "rgba(249, 115, 22, 0.1)",
                  border: "1px solid rgba(249, 115, 22, 0.3)",
                  color: "#fb923c"
                }}
              >
                <strong>{t("trainingPlanExtended.adaptedBecause") || "Adapté :"}</strong> {todaySession.adaptation_reason}
              </div>
            )}

            {/* Display with SessionCard */}
            {todaySession.adaptation_applied ? (
              <div className="space-y-3">
                {/* Original Session (grayed out) */}
                <div>
                  <div className="text-[10px] font-mono uppercase mb-1" style={{ color: "var(--text-tertiary)" }}>
                    {t("trainingPlanExtended.originalSession") || "Séance originale"}
                  </div>
                  <SessionCard session={todaySession.planned_session} isGrayed={true} />
                </div>

                {/* Adaptive Session (highlighted) */}
                <div>
                  <div className="text-[10px] font-mono uppercase mb-1" style={{ color: "var(--text-secondary)" }}>
                    {t("trainingPlanExtended.adaptiveSession") || "Séance adaptative"}
                  </div>
                  <SessionCard
                    session={todaySession.adaptive_session}
                    fatigueColor={todaySession.fatigue?.recommendation_color}
                  />
                </div>
              </div>
            ) : (
              <SessionCard session={todaySession.planned_session} />
            )}

            {/* Feedback Buttons */}
            <div className="flex gap-2 mt-3">
              <Button
                size="sm"
                onClick={() => handleFeedback(todaySession.day, "done")}
                disabled={feedbackSubmitting || sessionFeedback[todaySession.day] === "done"}
                className={`flex-1 ${
                  sessionFeedback[todaySession.day] === "done"
                    ? "bg-green-600 text-white"
                    : "bg-slate-700 text-slate-200 hover:bg-green-600"
                }`}
              >
                <Check className="w-4 h-4 mr-1" />
                {t("trainingPlanExtended.feedbackDone") || "Réalisé"}
              </Button>
              <Button
                size="sm"
                onClick={() => handleFeedback(todaySession.day, "missed")}
                disabled={feedbackSubmitting || sessionFeedback[todaySession.day] === "missed"}
                className={`flex-1 ${
                  sessionFeedback[todaySession.day] === "missed"
                    ? "bg-red-600 text-white"
                    : "bg-slate-700 text-slate-200 hover:bg-red-600"
                }`}
              >
                <X className="w-4 h-4 mr-1" />
                {t("trainingPlanExtended.feedbackMissed") || "Manqué"}
              </Button>
            </div>
          </>
        ) : (
          <>
            <h3 className="today-title" style={{ color: "var(--text-secondary)" }}>
              {t("dashboard.todayNoSessionTitle")}
            </h3>
            <p className="today-meta" style={{ opacity: 0.7 }}>
              {t("dashboard.todayNoSessionSubtitle")}
            </p>
          </>
        )}
      </div>

      {/* Metric explanation dialog */}
      <Dialog open={!!infoMetric} onOpenChange={(o) => !o && setInfoMetric(null)}>
        <DialogContent
          className="max-w-sm"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", color: "var(--text-primary)" }}
          data-testid="readiness-info-dialog"
        >
          <DialogHeader>
            <DialogTitle style={{ color: "var(--text-primary)" }}>
              {infoMetric ? t(`dashboard.readinessPillars.${infoMetric}`) : ""}
            </DialogTitle>
            <DialogDescription style={{ color: "var(--text-secondary)" }}>
              {infoMetric ? t(`dashboard.readinessInfo.${infoMetric}`) : ""}
            </DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>

    </div>
  );
}

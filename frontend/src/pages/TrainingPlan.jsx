import { useState, useEffect } from "react";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  TrendingUp, RefreshCw, CheckCircle2,
  Zap, Clock, Activity, ChevronDown, ChevronUp,
  Trophy, Mountain, Calendar, Heart
} from "lucide-react";
import { toast } from "sonner";
import axios from "axios";
import Paywall from "@/components/Paywall";

import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default";

// Helper functions for ACWR/TSB colors
const getAcwrColor = (status) => {
  switch(status) {
    case "low": return "#3b82f6";
    case "optimal": return "#22c55e";
    case "warning": return "#f59e0b";
    case "danger": return "#ef4444";
    default: return "#6b7280";
  }
};

const getTsbColor = (status) => {
  switch(status) {
    case "fresh": return "#22c55e";
    case "ready": return "#3b82f6";
    case "training": return "#f59e0b";
    case "fatigued": return "#ef4444";
    default: return "#6b7280";
  }
};

// Couleurs par phase
const PHASE_COLORS = {
  build: { bg: "#3b82f620", border: "#3b82f6", text: "#3b82f6", name: "Construction" },
  deload: { bg: "#22c55e20", border: "#22c55e", text: "#22c55e", name: "Récupération" },
  intensification: { bg: "#f9731620", border: "#f97316", text: "#f97316", name: "Intensification" },
  taper: { bg: "#8b5cf620", border: "#8b5cf6", text: "#8b5cf6", name: "Affûtage" },
  race: { bg: "#ef444420", border: "#ef4444", text: "#ef4444", name: "Course" },
};

// Couleurs correspondant au design de l'app pour les séances
const SESSION_STYLES = {
  repos: {
    bg: "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
    border: "#6366f1",
    text: "#c7d2fe",
    badge: "#4f46e5",
    badgeText: "#ffffff"
  },
  endurance: {
    bg: "linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%)",
    border: "#34d399",
    text: "#065f46",
    badge: "#10b981",
    badgeText: "#ffffff"
  },
  seuil: {
    bg: "linear-gradient(135deg, #fed7aa 0%, #fdba74 100%)",
    border: "#f97316",
    text: "#9a3412",
    badge: "#f97316",
    badgeText: "#ffffff"
  },
  recuperation: {
    bg: "linear-gradient(135deg, #fef9c3 0%, #fef08a 100%)",
    border: "#facc15",
    text: "#854d0e",
    badge: "#eab308",
    badgeText: "#ffffff"
  },
  sortie_longue: {
    bg: "linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%)",
    border: "#ec4899",
    text: "#9d174d",
    badge: "#ec4899",
    badgeText: "#ffffff"
  },
  fractionne: {
    bg: "linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%)",
    border: "#8b5cf6",
    text: "#5b21b6",
    badge: "#8b5cf6",
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

// SessionCard component for displaying a single session
function SessionCard({ session, isGrayed = false, fatigueColor = null }) {
  if (!session) return null;

  const styleKey = getSessionStyleKey(session.type, session.intensity);
  const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
  const isRest = styleKey === "repos";

  // Override border color based on fatigue if provided
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
            {session.type}
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

export default function TrainingPlan() {
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const { isFree, loading: subLoading, trialDaysRemaining, isTrial } = useSubscription();
  const [plan, setPlan] = useState(null);
  const [fullCycle, setFullCycle] = useState(null);
  const [trainingMetrics, setTrainingMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sessionsPerWeek, setSessionsPerWeek] = useState(null);
  const [expandedWeek, setExpandedWeek] = useState(null);
  const [showAllWeeks, setShowAllWeeks] = useState(true);
  const [apiError, setApiError] = useState(null);

  const fetchData = async () => {
    try {
      const [planRes, cycleRes, metricsRes] = await Promise.all([
        axios.get(`${API}/training/plan`, { headers: { "X-User-Id": USER_ID } }),
        axios.get(`${API}/training/full-cycle`, { params: { lang }, headers: { "X-User-Id": USER_ID } }),
        axios.get(`${API}/training/metrics`, { headers: { "X-User-Id": USER_ID } }).catch(() => ({ data: null }))
      ]);
      setPlan(planRes.data);
      setFullCycle(cycleRes.data);
      if (metricsRes.data) {
        setTrainingMetrics(metricsRes.data);
      }
      setApiError(null);
      if (planRes.data?.sessions_per_week) {
        setSessionsPerWeek(planRes.data.sessions_per_week);
      }
      // Expand current week by default
      if (cycleRes.data?.current_week) {
        setExpandedWeek(cycleRes.data.current_week);
      }
    } catch (err) {
      console.error("Error fetching plan:", err);
      // Check if it's a subscription error
      if (err.response?.status === 403 && err.response?.data?.error === "subscription_required") {
        setApiError("subscription_required");
      } else {
        toast.error(t("trainingPlanExtended.loadingError"));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefresh = async (newSessionCount = sessionsPerWeek) => {
    setRefreshing(true);
    try {
      const params = newSessionCount ? `?sessions=${newSessionCount}` : "";
      const res = await axios.post(`${API}/training/refresh${params}`, {}, {
        headers: { "X-User-Id": USER_ID }
      });
      setPlan(res.data);
      // Refresh full cycle too
      const cycleRes = await axios.get(`${API}/training/full-cycle`, { params: { lang }, headers: { "X-User-Id": USER_ID } });
      setFullCycle(cycleRes.data);
      toast.success(t("trainingPlanExtended.planUpdated"));
    } catch (err) {
      toast.error(t("common.error"));
    } finally {
      setRefreshing(false);
    }
  };

  if (loading || subLoading) {
    return (
      <div className="p-4 space-y-4" style={{ background: "var(--bg-primary)", minHeight: "100vh" }}>
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-3 grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  // Show paywall for free users
  if (isFree || apiError === "subscription_required") {
    return <Paywall language={lang} returnPath="/training" />;
  }

  const context = plan?.context || {};
  const sessions = plan?.plan?.sessions || [];
  const weeks = fullCycle?.weeks || [];
  const currentWeek = fullCycle?.current_week || 1;
  const totalWeeks = fullCycle?.total_weeks || 12;

  return (
    <div className="p-4 pb-24 space-y-4" style={{ background: "var(--bg-primary)" }} data-testid="training-plan-page">
      
      {/* Trial Banner */}
      {isTrial && trialDaysRemaining !== null && (
        <div 
          className="p-3 rounded-xl flex items-center justify-between"
          style={{ 
            background: "linear-gradient(135deg, rgba(59,130,246,0.2) 0%, rgba(139,92,246,0.2) 100%)",
            border: "1px solid rgba(59,130,246,0.3)"
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold uppercase tracking-tight text-white">
            {t("trainingPlanExtended.planTitle")}
          </h1>
          <p className="text-sm font-mono" style={{ color: "var(--text-tertiary)" }}>
            {t("trainingPlanExtended.weekLabel")} {currentWeek} / {totalWeeks}
            {" • "}
            <span className="capitalize">{fullCycle?.goal ? t(`settings.distances.${fullCycle.goal.toLowerCase()}`) : t("settings.distances.semi")}</span>
          </p>
        </div>
        <Button 
          variant="outline" 
          size="sm" 
          onClick={() => handleRefresh()}
          disabled={refreshing}
          className="border-slate-600 text-slate-300 hover:bg-slate-700"
          data-testid="refresh-plan-btn"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
          {t("trainingPlanExtended.refresh")}
        </Button>
      </div>

      {/* Progress Bar */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Trophy className="w-4 h-4" style={{ color: "#f59e0b" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
              {t("trainingPlanExtended.cycleProgress")}
            </span>
          </div>
          <span className="text-sm font-bold text-white">
            {Math.round((currentWeek / totalWeeks) * 100)}%
          </span>
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-secondary)" }}>
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${(currentWeek / totalWeeks) * 100}%`,
              background: "linear-gradient(90deg, #8b5cf6 0%, #ec4899 100%)"
            }}
          />
        </div>
        <div className="flex justify-between mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
          <span>{t("trainingPlanExtended.startLabel")}</span>
          <span>{fullCycle?.goal || "SEMI"}</span>
        </div>
      </div>

      {/* METRICS ROW - Cette semaine & Charge 28j */}
      <div className="grid grid-cols-2 gap-3">
        {/* Cette semaine */}
        <div 
          className="p-4 rounded-2xl animate-in"
          style={{ 
            background: "var(--bg-card)", 
            border: "1px solid var(--border-color)",
            animationDelay: "50ms" 
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-4 h-4" style={{ color: "var(--accent-violet)" }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
              {t("dashboard.thisWeek")}
            </span>
          </div>
          <div className="flex items-baseline">
            <span className="text-2xl font-bold text-white">
              {formatDistance(trainingMetrics?.load_7 || 0, { unitSystem })}
            </span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden mt-2" style={{ background: "var(--bg-secondary)" }}>
            <div 
              className="h-full rounded-full"
              style={{ 
                width: `${Math.min(100, ((trainingMetrics?.load_7 || 0) / (trainingMetrics?.weekly_target || 40)) * 100)}%`,
                background: "var(--accent-violet)"
              }}
            />
          </div>
        </div>

        {/* Charge 28j */}
        <div 
          className="p-4 rounded-2xl animate-in"
          style={{ 
            background: "var(--bg-card)", 
            border: "1px solid var(--border-color)",
            animationDelay: "100ms" 
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4" style={{ color: "var(--accent-pink)" }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
              {t("dashboard.load28Label")}
            </span>
          </div>
          <div className="flex items-baseline">
            <span className="text-2xl font-bold text-white">
              {formatDistance(trainingMetrics?.load_28 || 0, { unitSystem })}
            </span>
          </div>
          <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
            {t("dashboard.load28Subtitle")}
          </p>
        </div>
      </div>

      {/* ACWR & TSB ROW */}
      <div className="grid grid-cols-2 gap-3">
        {/* ACWR */}
        <div 
          className="p-4 rounded-2xl animate-in"
          style={{ 
            background: "var(--bg-card)", 
            border: "1px solid var(--border-color)",
            animationDelay: "120ms" 
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4" style={{ color: getAcwrColor(trainingMetrics?.acwr_status) }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
              ACWR
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold" style={{ color: getAcwrColor(trainingMetrics?.acwr_status) }}>
              {trainingMetrics?.acwr?.toFixed(2) || "1.00"}
            </span>
            {trainingMetrics?.acwr_status === "optimal" && (
              <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "#22c55e20", color: "#22c55e" }}>✓</span>
            )}
          </div>
          <p className="text-xs mt-1" style={{ color: getAcwrColor(trainingMetrics?.acwr_status) }}>
            {trainingMetrics?.acwr_status ? t(`dashboard.acwr_status.${trainingMetrics.acwr_status}`) : t("dashboard.acwr_status.optimal")}
          </p>
        </div>

        {/* TSB */}
        <div 
          className="p-4 rounded-2xl animate-in"
          style={{ 
            background: "var(--bg-card)", 
            border: "1px solid var(--border-color)",
            animationDelay: "140ms" 
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Heart className="w-4 h-4" style={{ color: getTsbColor(trainingMetrics?.tsb_status) }} />
            <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
              TSB
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold" style={{ color: getTsbColor(trainingMetrics?.tsb_status) }}>
              {trainingMetrics?.tsb?.toFixed(1) || "0.0"}
            </span>
          </div>
          <p className="text-xs mt-1" style={{ color: getTsbColor(trainingMetrics?.tsb_status) }}>
            {trainingMetrics?.tsb_label || t("dashboard.tsb_status.training")}
          </p>
        </div>
      </div>

      {/* TOUTES LES SEMAINES DU CYCLE */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
              {t("trainingPlanExtended.fullCycleLabel")} • {totalWeeks} {t("trainingPlanExtended.weeksSuffix")}
            </span>
          </div>
          <button
            onClick={() => setShowAllWeeks(!showAllWeeks)}
            className="text-xs flex items-center gap-1 px-2 py-1 rounded"
            style={{ color: "var(--text-secondary)", background: "var(--bg-secondary)" }}
          >
            {showAllWeeks ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {showAllWeeks ? t("trainingPlanExtended.collapse") : t("trainingPlanExtended.showAll")}
          </button>
        </div>

        <div className="space-y-2">
          {weeks.map((week, idx) => {
            const phaseStyle = PHASE_COLORS[week.phase] || PHASE_COLORS.build;
            const isExpanded = expandedWeek === week.week;
            const isCurrent = week.is_current;
            const isCompleted = week.is_completed;
            
            // Only show: current week, 2 before, 2 after, and first/last if not showing all
            const shouldShow = showAllWeeks || 
              isCurrent || 
              Math.abs(week.week - currentWeek) <= 2 ||
              week.week === 1 ||
              week.week === totalWeeks;
            
            if (!shouldShow) return null;

            return (
              <div
                key={week.week}
                className={`rounded-xl overflow-hidden transition-all ${isCurrent ? "ring-2 ring-violet-500" : ""}`}
                style={{
                  background: isCompleted ? "var(--bg-secondary)" : phaseStyle.bg,
                  border: `1px solid ${isCompleted ? "var(--border-color)" : phaseStyle.border}`,
                  opacity: isCompleted ? 0.6 : 1
                }}
                data-testid={`week-${week.week}`}
              >
                {/* Week Header */}
                <button
                  onClick={() => setExpandedWeek(isExpanded ? null : week.week)}
                  className="w-full p-3 flex items-center justify-between text-left"
                >
                  <div className="flex items-center gap-3">
                    <div 
                      className="w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm"
                      style={{ 
                        background: isCurrent ? "#8b5cf6" : isCompleted ? "var(--bg-tertiary)" : phaseStyle.border + "30",
                        color: isCurrent ? "white" : isCompleted ? "var(--text-tertiary)" : phaseStyle.text
                      }}
                    >
                      {isCompleted ? <CheckCircle2 className="w-4 h-4" /> : week.week}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`font-semibold text-sm ${isCompleted ? "line-through" : ""}`} style={{ color: isCompleted ? "var(--text-tertiary)" : "white" }}>
                          {t("trainingPlanExtended.weekLabel")} {week.week}
                        </span>
                        {isCurrent && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-violet-500 text-white">
                            {t("trainingPlanExtended.currentBadge")}
                          </span>
                        )}
                        {week.phase === "race" && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-500 text-white flex items-center gap-1">
                            <Trophy className="w-3 h-3" /> COURSE
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span 
                          className="text-[10px] font-mono uppercase"
                          style={{ color: isCompleted ? "var(--text-tertiary)" : phaseStyle.text }}
                        >
                          {week.phase_name}
                        </span>
                        <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>•</span>
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          ~{week.target_km} km
                        </span>
                        <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>•</span>
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {week.sessions} séances
                        </span>
                      </div>
                    </div>
                  </div>
                  <ChevronDown 
                    className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                    style={{ color: "var(--text-tertiary)" }}
                  />
                </button>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="px-3 pb-3 space-y-2">
                    <div className="text-xs p-2 rounded-lg" style={{ background: "rgba(0,0,0,0.2)", color: "var(--text-secondary)" }}>
                      <strong>{t("trainingPlanExtended.focus")}</strong> {week.phase_focus}
                    </div>
                    
                    {/* Session types for this week */}
                    <div className="flex flex-wrap gap-1">
                      {week.session_types?.map((type, i) => {
                        const styleKey = getSessionStyleKey(type);
                        const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
                        const label = typeof type === "string" && type === type.toLowerCase() && type.indexOf(" ") === -1
                          ? t(`trainingPlanSessionType.${type}`)
                          : type;
                        return (
                          <span 
                            key={i}
                            className="px-2 py-1 rounded-full text-[10px] font-medium"
                            style={{ background: style.badge, color: style.badgeText }}
                          >
                            {label}
                          </span>
                        );
                      })}
                    </div>

                    {/* If current week, show detailed sessions */}
                    {isCurrent && sessions.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-white/10 space-y-2">
                        <span className="text-[10px] font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
                          {t("trainingPlanExtended.weekDetails")}
                        </span>
                        {sessions.map((session, sidx) => {
                          const styleKey = getSessionStyleKey(session.type, session.intensity);
                          const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
                          const isRest = styleKey === "repos";
                          
                          return (
                            <div
                              key={sidx}
                              className="flex items-center gap-2 p-2 rounded-lg"
                              style={{ background: style.bg }}
                            >
                              <div 
                                className="w-1 h-8 rounded-full shrink-0"
                                style={{ background: style.border }}
                              />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-bold" style={{ color: style.text }}>
                                    {session.day}
                                  </span>
                                  <span className="text-[10px]" style={{ color: style.text, opacity: 0.8 }}>
                                    {session.type}
                                  </span>
                                </div>
                                {!isRest && session.details && (
                                  <span className="text-[10px] block truncate" style={{ color: style.text, opacity: 0.7 }}>
                                    {session.details}
                                  </span>
                                )}
                              </div>
                              <span 
                                className="px-2 py-0.5 rounded-full text-[9px] font-bold shrink-0"
                                style={{ background: style.badge, color: style.badgeText }}
                              >
                                {session.estimated_tss || 0} TSS
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Conseil du coach */}
      {plan?.plan?.advice && (
        <div 
          className="card-modern p-4" 
          style={{ 
            background: "linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(139, 92, 246, 0.05) 100%)", 
            border: "1px solid rgba(139, 92, 246, 0.3)", 
            borderRadius: "16px" 
          }}
        >
          <div className="flex gap-3">
            <div 
              className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center"
              style={{ background: "rgba(139, 92, 246, 0.2)" }}
            >
              <Activity className="w-5 h-5" style={{ color: "#8b5cf6" }} />
            </div>
            <div>
              <p className="text-xs font-mono uppercase mb-1" style={{ color: "var(--text-tertiary)" }}>
                {t("trainingPlanExtended.coachAdvice")}
              </p>
              <p className="text-sm text-white">{plan.plan.advice}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

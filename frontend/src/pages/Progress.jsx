import { useState, useEffect } from "react";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";
import { 
  LineChart,
  Line,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  ReferenceLine
} from "recharts";
import { 
  TrendingUp, 
  Activity,
  ChevronDown,
  ChevronUp,
  Calendar,
  Timer,
  Zap,
  ArrowUpRight,
  ArrowDownRight,
  Heart,
  Moon,
  TrendingDown,
  Minus,
  Brain
} from "lucide-react";
import Paywall from "@/components/Paywall";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

const formatDuration = (minutes) => {
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) {
    return `${hrs}h ${mins}m`;
  }
  return `${mins}m`;
};

// Format date as short label for chart axis
const formatDateLabel = (dateStr, locale = "fr-FR", granularity = "week") => {
  if (!dateStr) return "";
  const d = new Date(dateStr + "T00:00:00");
  if (granularity === "month") {
    return d.toLocaleDateString(locale, { month: "short", year: "2-digit" });
  }
  return d.toLocaleDateString(locale, { day: "numeric", month: "short" });
};

// Map language code to locale string
const langToLocale = (lang) => {
  const map = { fr: "fr-FR", en: "en-US", es: "es-ES" };
  return map[lang] || "fr-FR";
};

export default function Progress() {
  const [stats, setStats] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [fullCycle, setFullCycle] = useState(null);
  const [vmaHistory, setVmaHistory] = useState(null);
  const [garminHealth, setGarminHealth] = useState(null);
  const [runIndexHistory, setRunIndexHistory] = useState(null);
  const [runIndexPeriod, setRunIndexPeriod] = useState("6m");
  const [loading, setLoading] = useState(true);
  const [showPredictions, setShowPredictions] = useState(true);
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading } = useSubscription();
  const { unitSystem } = useUnitSystem();

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, predictionsRes, cycleRes, vmaHistoryRes] = await Promise.all([
          axios.get(`${API}/stats`),
          axios.get(`${API}/training/race-predictions`).catch(() => ({ data: null })),
          axios.get(`${API}/training/full-cycle`).catch(() => ({ data: null })),
          axios.get(`${API}/training/vma-history`).catch(() => ({ data: null }))
        ]);
        setStats(statsRes.data);

        // Garmin daily health metrics (HRV / resting HR / sleep)
        try {
          const garminRes = await axios.get(`${API}/garmin/daily-metrics?days=7`);
          if (garminRes.data?.count > 0) setGarminHealth(garminRes.data);
        } catch {
          /* Garmin not connected — section stays hidden */
        }

        let vmaData = vmaHistoryRes.data;
        if (vmaData) setVmaHistory(vmaData);

        let predData = predictionsRes.data;
        if (predData) setPredictions(predData);

        if (cycleRes.data) setFullCycle(cycleRes.data);
      } catch (error) {
        console.error("Failed to fetch data:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch RunIndex history when period changes
  useEffect(() => {
    const fetchRunIndexHistory = async () => {
      try {
        const res = await axios.get(`${API}/run-index/history?period=${runIndexPeriod}&language=${lang}`);
        setRunIndexHistory(res.data);
      } catch {
        setRunIndexHistory(null);
      }
    };
    fetchRunIndexHistory();
  }, [runIndexPeriod, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading || subLoading) {
    return (
      <div className="p-6 md:p-8 animate-pulse">
        <div className="h-8 w-48 bg-muted rounded mb-8" />
        <div className="h-64 bg-muted rounded mb-8" />
      </div>
    );
  }

  // Show paywall for free users
  if (isFree) {
    return <Paywall language={lang} returnPath="/progress" />;
  }

  // Utiliser les stats calculées côté backend (7 et 30 derniers jours)
  const sessions7Days = stats?.sessions_7_days || 0;
  const km7Days = stats?.km_7_days || 0;
  const km30Days = stats?.km_30_days || 0;

  const pillarIcons = {
    speed: "⚡",
    endurance: "🫀",
    consistency: "📈",
    efficiency: "🧠",
  };
  const pillarLabels = {
    speed: t("progressExtended.pillarSpeed"),
    endurance: t("progressExtended.pillarEndurance"),
    consistency: t("progressExtended.pillarConsistency"),
    efficiency: t("progressExtended.pillarEfficiency"),
  };

  const runIndexTrend = runIndexHistory?.trend ?? 0;
  const TrendIcon = runIndexTrend > 0 ? TrendingUp : runIndexTrend < 0 ? TrendingDown : Minus;
  const trendColor = runIndexTrend > 0 ? "text-emerald-500" : runIndexTrend < 0 ? "text-red-500" : "text-muted-foreground";
  const trendBg = runIndexTrend > 0 ? "bg-emerald-500/20" : runIndexTrend < 0 ? "bg-red-500/20" : "bg-muted/30";
  const trendEmoji = runIndexTrend > 0 ? "⬆️" : runIndexTrend < 0 ? "⬇️" : "➡️";
  const historyGranularity = runIndexHistory?.granularity || "week";

  const periodOptions = [
    { value: "3m", label: t("progressExtended.period3m") },
    { value: "6m", label: t("progressExtended.period6m") },
    { value: "12m", label: t("progressExtended.period12m") },
  ];

  return (
    <div className="p-6 md:p-8 pb-24 md:pb-8" data-testid="progress-page">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-heading text-2xl md:text-3xl uppercase tracking-tight font-bold mb-1">
          {t("progress.title")}
        </h1>
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {t("progress.subtitle")}
        </p>
      </div>

      {/* ===== RUNINDEX EVOLUTION (top of tab) ===== */}
      <div className="mb-8">
        <Card className="bg-card border-border overflow-hidden">
          <CardContent className="p-4">
            {/* Section title */}
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp className="w-4 h-4 text-primary" />
              <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                {t("progressExtended.runIndexEvolution")}
              </h2>
            </div>

            {/* Current RunIndex + Trend */}
            <div className="flex items-center justify-between mb-5">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                  {t("progressExtended.runIndexCurrent")}
                </p>
                <div className="flex items-baseline gap-2">
                  <span className="font-heading text-5xl font-bold text-white">
                    {runIndexHistory?.current_run_index ?? "--"}
                  </span>
                  <span className="text-sm text-muted-foreground">/ 1000</span>
                </div>
              </div>

              {runIndexHistory?.has_data && (
                <div className={`flex flex-col items-end gap-1`}>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {t("progressExtended.runIndexTrend")}
                  </p>
                  <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full ${trendBg}`}>
                    <span className="text-base">{trendEmoji}</span>
                    <span className={`text-sm font-bold ${trendColor}`}>
                      {(() => {
                        if (runIndexTrend === 0) {
                          return t("progressExtended.runIndexTrendStablePeriod");
                        }
                        return `${runIndexTrend > 0 ? "+" : ""}${runIndexTrend} ${t("progressExtended.runIndexTrendPeriod")}`;
                      })()}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Period selector */}
            <div className="flex gap-2 mb-4">
              {periodOptions.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setRunIndexPeriod(value)}
                  className={`px-3 py-1 rounded-full font-mono text-[10px] uppercase tracking-wider transition-all ${
                    runIndexPeriod === value
                      ? "bg-primary text-black font-bold"
                      : "bg-muted/30 text-muted-foreground hover:bg-muted/60"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {runIndexHistory?.has_data && !runIndexHistory?.has_full_period_data && (
              <div
                className="mb-4 px-3 py-2 rounded-xl"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
              >
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {t("progressExtended.insufficientPeriodData")}
                </p>
              </div>
            )}

            {/* RunIndex Chart */}
            {runIndexHistory?.has_data && runIndexHistory.history?.length > 0 ? (
              <div className="h-40 mb-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={runIndexHistory.history.filter(h => h.run_index !== null)}
                    margin={{ top: 5, right: 10, left: -20, bottom: 5 }}
                  >
                    <XAxis
                      dataKey="date"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9, fontFamily: "JetBrains Mono" }}
                      tickFormatter={(dateStr) => formatDateLabel(dateStr, langToLocale(lang), historyGranularity)}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      domain={[0, 1000]}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9, fontFamily: "JetBrains Mono" }}
                      ticks={[0, 250, 500, 750, 1000]}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          const d = payload[0].payload;
                          return (
                            <div className="bg-popover border border-border p-2 rounded-lg shadow-lg">
                              <p className="font-mono text-xs text-muted-foreground">
                                {formatDateLabel(d.date, langToLocale(lang), historyGranularity)}
                              </p>
                              <p className="font-bold text-white">RunIndex: {d.run_index}</p>
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    {runIndexHistory.current_run_index && (
                      <ReferenceLine
                        y={runIndexHistory.current_run_index}
                        stroke="rgba(110, 235, 90, 0.3)"
                        strokeDasharray="3 3"
                      />
                    )}
                    <Line
                      type="monotone"
                      dataKey="run_index"
                      stroke="#6EEB5A"
                      strokeWidth={2}
                      dot={{ fill: "#6EEB5A", strokeWidth: 0, r: 3 }}
                      activeDot={{ fill: "#6EEB5A", strokeWidth: 2, stroke: "white", r: 5 }}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="h-40 flex items-center justify-center mb-4">
                <p className="font-mono text-xs text-muted-foreground text-center">
                  {t("progressExtended.noDataYet")}
                </p>
              </div>
            )}

            {/* Pillar details */}
            {runIndexHistory?.has_data && runIndexHistory.pillars && (
              <div className="mb-4">
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
                  {t("progressExtended.pillarsTitle")}
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(runIndexHistory.pillars).map(([pillar, data]) => {
                    const evo = data.evolution;
                    const evoColor = evo > 0 ? "text-emerald-500" : evo < 0 ? "text-red-400" : "text-muted-foreground";
                    return (
                      <div
                        key={pillar}
                        className="flex items-center gap-2 p-3 rounded-xl"
                        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
                      >
                        <span className="text-xl">{pillarIcons[pillar]}</span>
                        <div className="flex-1 min-w-0">
                          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                            {pillarLabels[pillar]}
                          </p>
                          <div className="flex items-baseline gap-1.5">
                            {data.current === null || data.current === undefined ? (
                              <span className="font-heading text-lg font-bold text-muted-foreground">—</span>
                            ) : (
                              <span className="font-heading text-lg font-bold text-white">
                                {data.current}%
                              </span>
                            )}
                          </div>
                          {evo !== null && evo !== undefined && (
                            <p className={`font-mono text-[10px] uppercase tracking-wider ${evoColor}`}>
                              {`${evo > 0 ? "+" : ""}${evo}% ${t("progressExtended.sinceStartOfPeriod")}`}
                            </p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* AI Analysis */}
            {runIndexHistory?.ai_analysis && (
              <div
                className="p-3 rounded-xl"
                style={{ background: "rgba(110, 235, 90, 0.06)", border: "1px solid rgba(110, 235, 90, 0.15)" }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Brain className="w-3.5 h-3.5" style={{ color: "#6EEB5A" }} />
                  <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "rgba(110, 235, 90, 0.8)" }}>
                    {t("progressExtended.aiAnalysisTitle")}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {runIndexHistory.ai_analysis}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Weekly & Monthly Stats */}
      <div className="grid grid-cols-3 gap-2 sm:gap-3 mb-8">
        {/* Séances 7 jours */}
        <Card className="bg-card border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-4 h-4 text-primary" />
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("progressExtended.sessions7d")}
              </span>
            </div>
            <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
              {sessions7Days}
            </p>
          </CardContent>
        </Card>

        {/* Km 7 jours */}
        <Card className="bg-card border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-4 h-4 text-emerald-500" />
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("progressExtended.km7d")}
              </span>
            </div>
            <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
              {formatDistance(km7Days, { unitSystem })}
            </p>
          </CardContent>
        </Card>

        {/* Km 30 jours */}
        <Card className="bg-card border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Calendar className="w-4 h-4 text-primary" />
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("progressExtended.km30d")}
              </span>
            </div>
            <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
              {formatDistance(km30Days, { unitSystem })}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Garmin Health (HRV / Resting HR / Sleep) */}
      {garminHealth?.latest && (
        <div className="mb-8" data-testid="garmin-health-section">
          <div className="flex items-center gap-2 mb-3">
            <Heart className="w-4 h-4 text-rose-500" />
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Garmin Health · 7 days
            </h2>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            <Card className="bg-card border-border" data-testid="garmin-hrv">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Activity className="w-4 h-4 text-emerald-500" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    HRV
                  </span>
                </div>
                <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
                  {garminHealth.latest.hrv ?? "--"}
                  <span className="text-sm text-muted-foreground ml-1">ms</span>
                </p>
              </CardContent>
            </Card>

            <Card className="bg-card border-border" data-testid="garmin-resting-hr">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Heart className="w-4 h-4 text-rose-500" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Resting HR
                  </span>
                </div>
                <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
                  {garminHealth.latest.resting_hr ?? "--"}
                  <span className="text-sm text-muted-foreground ml-1">bpm</span>
                </p>
              </CardContent>
            </Card>

            <Card className="bg-card border-border" data-testid="garmin-sleep">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Moon className="w-4 h-4 text-blue-400" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Sleep
                  </span>
                </div>
                <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
                  {garminHealth.latest.sleep_hours ?? "--"}
                  <span className="text-sm text-muted-foreground ml-1">h</span>
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* VO2MAX Section with Chart */}
      {(predictions?.has_data || vmaHistory?.has_data) && (
        <div className="mb-6">
          <Card className="bg-card border-border overflow-hidden">
            <CardContent className="p-4">
              {/* Header with current VO2MAX */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 rounded-xl flex flex-col items-center justify-center" style={{ background: "rgba(110, 235, 90, 0.12)", border: "1px solid rgba(110, 235, 90, 0.25)" }}>
                    <Zap className="w-5 h-5" style={{ color: "#6EEB5A" }} />
                    <span className="text-[7px] font-mono uppercase mt-0.5" style={{ color: "rgba(110, 235, 90, 0.8)" }}>VO2MAX</span>
                  </div>
                  <div>
                    <div className="flex items-baseline gap-2">
                      <span className="text-4xl font-bold text-white">
                        {vmaHistory?.current_vo2max || predictions?.athlete_profile?.estimated_vo2max || "--"}
                      </span>
                      <span className="text-sm text-muted-foreground">ml/kg/min</span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {t("progressExtended.basedOn6Weeks")}
                    </p>
                  </div>
                </div>
                
                {/* Trend indicator */}
                {vmaHistory?.trend !== 0 && vmaHistory?.trend !== undefined && (
                  <div className={`flex items-center gap-1 px-3 py-1.5 rounded-full ${vmaHistory.trend > 0 ? 'bg-emerald-500/20' : 'bg-red-500/20'}`}>
                    {vmaHistory.trend > 0 ? (
                      <ArrowUpRight className="w-4 h-4 text-emerald-500" />
                    ) : (
                      <ArrowDownRight className="w-4 h-4 text-red-500" />
                    )}
                    <span className={`text-sm font-bold ${vmaHistory.trend > 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                      {vmaHistory.trend > 0 ? '+' : ''}{vmaHistory.trend}
                    </span>
                    <span className="text-xs text-muted-foreground ml-1">
                      ({t("progressExtended.months12")})
                    </span>
                  </div>
                )}
              </div>
              
              {/* VO2MAX Evolution Chart - 12 months */}
              {vmaHistory?.history && vmaHistory.history.length > 0 && (
                <div className="mt-4">
                  <p className="text-[10px] font-mono uppercase text-muted-foreground mb-3">
                    {t("progressExtended.evolution12Months")}
                  </p>
                  <div className="h-36">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart 
                        data={vmaHistory.history.filter(h => h.vo2max !== null)}
                        margin={{ top: 5, right: 10, left: -20, bottom: 5 }}
                      >
                        <XAxis 
                          dataKey="period_label" 
                          axisLine={false}
                          tickLine={false}
                          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9, fontFamily: "JetBrains Mono" }}
                          interval={1}
                        />
                        <YAxis 
                          domain={['dataMin - 2', 'dataMax + 2']}
                          axisLine={false}
                          tickLine={false}
                          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10, fontFamily: "JetBrains Mono" }}
                          tickFormatter={(value) => `${value}`}
                        />
                        <Tooltip 
                          content={({ active, payload }) => {
                            if (active && payload && payload.length) {
                              const data = payload[0].payload;
                              return (
                                <div className="bg-popover border border-border p-2 rounded-lg shadow-lg">
                                  <p className="font-mono text-xs text-muted-foreground">
                                    {data.month_label} {data.half === 1 ? "(1-15)" : "(16-fin)"}
                                  </p>
                                  <p className="font-bold text-white">{data.vo2max} ml/kg/min</p>
                                  <p className="text-[10px] text-muted-foreground">{data.sessions} {t("progressExtended.sessionsCount")}</p>
                                </div>
                              );
                            }
                            return null;
                          }}
                        />
                        <ReferenceLine 
                          y={vmaHistory.current_vo2max} 
                          stroke="rgba(110, 235, 90, 0.3)" 
                          strokeDasharray="3 3" 
                        />
                        <Line 
                          type="monotone" 
                          dataKey="vo2max" 
                          stroke="#6EEB5A" 
                          strokeWidth={2}
                          dot={{ fill: "#6EEB5A", strokeWidth: 0, r: 3 }}
                          activeDot={{ fill: "#6EEB5A", strokeWidth: 2, stroke: "white", r: 5 }}
                          connectNulls={true}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Race Predictions */}
      {predictions?.has_data && (
        <div className="mb-8">
          <Card className="bg-card border-border overflow-hidden">
            <CardContent className="p-0">
              {/* Header */}
              <div 
                className="flex items-center justify-between p-4 cursor-pointer"
                onClick={() => setShowPredictions(!showPredictions)}
                style={{ background: "linear-gradient(135deg, rgba(245,158,11,0.1) 0%, rgba(251,191,36,0.05) 100%)" }}
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "rgba(245,158,11,0.2)" }}>
                    <Timer className="w-5 h-5" style={{ color: "#f59e0b" }} />
                  </div>
                  <div>
                    <h2 className="font-heading text-lg uppercase tracking-tight font-semibold">
                      {t("progressExtended.racePredictions")}
                    </h2>
                    <p className="font-mono text-xs text-muted-foreground">
                      {t("progressExtended.basedOnVma")}
                    </p>
                  </div>
                </div>
                <button className="p-2 rounded-lg" style={{ background: "rgba(255,255,255,0.05)" }}>
                  {showPredictions ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
              </div>

              {showPredictions && (
                <div className="p-4 space-y-4">
                  {/* Predictions by distance */}
                  <div className="space-y-2">
                    {predictions.predictions?.map((pred) => (
                      <div 
                        key={pred.distance}
                        className="flex items-center gap-3 p-3 rounded-xl transition-all"
                        style={{ 
                          background: pred.distance === fullCycle?.goal ? `${pred.readiness_color}15` : "rgba(255,255,255,0.03)",
                          border: pred.distance === fullCycle?.goal ? `2px solid ${pred.readiness_color}` : "1px solid rgba(255,255,255,0.05)"
                        }}
                      >
                        {/* Distance badge */}
                        <div 
                          className="shrink-0 w-14 h-14 rounded-xl flex flex-col items-center justify-center"
                          style={{ background: `${pred.readiness_color}20` }}
                        >
                          <span className="text-sm font-bold" style={{ color: pred.readiness_color }}>
                            {pred.distance}
                          </span>
                        </div>

                        {/* Predicted time */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-xl font-bold text-white">{pred.predicted_time}</span>
                            {pred.distance === fullCycle?.goal && (
                              <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: "var(--accent-green)", color: "#0a0e1a" }}>
                                OBJECTIF
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {pred.predicted_pace} • {pred.predicted_range}
                          </p>
                        </div>

                        {/* Readiness */}
                        <div className="shrink-0 text-right">
                          <div 
                            className="px-3 py-1 rounded-full text-xs font-bold mb-1"
                            style={{ background: `${pred.readiness_color}20`, color: pred.readiness_color }}
                          >
                            {pred.readiness_label}
                          </div>
                          <p className="text-[10px] text-muted-foreground">
                            {pred.readiness_score}% prêt
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

    </div>
  );
}

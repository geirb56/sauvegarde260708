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

const formatMeasurementDate = (dateStr, lang) => {
  if (!dateStr) return null;
  try {
    return new Date(`${dateStr}T00:00:00Z`).toLocaleDateString(langToLocale(lang), {
      day: "numeric",
      month: "short",
    });
  } catch {
    return dateStr;
  }
};

// PR184 — map V2 goal_type (TrainingCycleV2Response) to race prediction distance label
const V2_GOAL_TO_PRED_DISTANCE = {
  five_k: "5K",
  ten_k: "10K",
  half_marathon: "Semi",
  marathon: "Marathon",
  ultra: "Ultra",
};

export default function Progress() {
  const [stats, setStats] = useState(null);
  const [predictions, setPredictions] = useState(null);
  // PR184: migrated training cycle from legacy full-cycle endpoint to /training/v2/cycle
  // PREDICTIONS_FRONTEND_PRESERVED = YES
  const [cycleV2, setCycleV2] = useState(null);
  const [garminHealth, setGarminHealth] = useState(null);
  const [runIndexCurrent, setRunIndexCurrent] = useState(null);
  const [garminVo2maxHistory, setGarminVo2maxHistory] = useState(null);
  const [runIndexHistory, setRunIndexHistory] = useState(null);
  const [runIndexPeriod, setRunIndexPeriod] = useState("6m");
  const [loading, setLoading] = useState(true);
  const [showPredictions, setShowPredictions] = useState(true);
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading } = useSubscription();
  const { unitSystem } = useUnitSystem();

  useEffect(() => {
    if (subLoading) return; // wait for subscription resolution
    if (isFree) {
      // FREE: paywall — no data fetches at all
      setLoading(false);
      return;
    }
    const fetchData = async () => {
      try {
        const [statsRes, predictionsRes, cycleRes, runIndexRes, vo2HistoryRes] = await Promise.all([
          axios.get(`${API}/stats`),
          axios.get(`${API}/training/race-predictions`).catch(() => ({ data: null })),
          // PR184: V2/cycle is the authority for cycle calendar (no session prescription)
          axios.get(`${API}/training/v2/cycle`).catch(() => ({ data: null })),
          axios.get(`${API}/run-index`).catch(() => ({ data: null })),
          axios.get(`${API}/garmin/vo2max-history?period=12m`).catch(() => ({ data: null })),
        ]);
        setStats(statsRes.data);

        // Garmin daily health metrics (HRV / resting HR / sleep)
        try {
          const garminRes = await axios.get(`${API}/garmin/daily-metrics?days=7`);
          if (garminRes.data?.count > 0) setGarminHealth(garminRes.data);
        } catch {
          /* Garmin not connected — section stays hidden */
        }

        let predData = predictionsRes.data;
        if (predData) setPredictions(predData);

        if (cycleRes.data) setCycleV2(cycleRes.data);
        if (runIndexRes.data?.metrics) setRunIndexCurrent(runIndexRes.data.metrics);
        if (vo2HistoryRes.data) setGarminVo2maxHistory(vo2HistoryRes.data);
      } catch (error) {
        console.error("Failed to fetch data:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [subLoading, isFree]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch RunIndex history when period changes — TRIAL/PREMIUM only
  useEffect(() => {
    if (subLoading || isFree) return;
    const fetchRunIndexHistory = async () => {
      try {
        const res = await axios.get(`${API}/run-index/history?period=${runIndexPeriod}&language=${lang}`);
        setRunIndexHistory(res.data);
      } catch {
        setRunIndexHistory(null);
      }
    };
    fetchRunIndexHistory();
  }, [runIndexPeriod, lang, subLoading, isFree]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const garminVo2CurrentValue = runIndexCurrent?.vo2max_running ?? garminVo2maxHistory?.current?.value ?? null;
  const garminVo2CurrentDate = runIndexCurrent?.vo2max_date ?? garminVo2maxHistory?.current?.date ?? null;
  const garminVo2Series = Array.isArray(garminVo2maxHistory?.history) ? garminVo2maxHistory.history : [];

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
                    data={runIndexHistory.history}
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
                      connectNulls={false}
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
              {t("progressExtended.garminHealthTitle")}
            </h2>
            {/* Staleness banner — show when latest measurement is not from today/yesterday */}
            {garminHealth.latest.is_current === false && garminHealth.latest.measurement_date && (
              <span
                className="font-mono text-[10px] uppercase tracking-wider text-amber-400 ml-1"
                data-testid="garmin-health-stale-banner"
              >
                · {formatMeasurementDate(garminHealth.latest.measurement_date, lang)}
              </span>
            )}
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
                  {garminHealth.latest.is_current !== false
                    ? (garminHealth.latest.hrv ?? "--")
                    : "--"}
                  <span className="text-sm text-muted-foreground ml-1">ms</span>
                </p>
                {garminHealth.latest.is_current === false && garminHealth.latest.hrv != null && (
                  <p className="font-mono text-[10px] text-amber-400 mt-1" data-testid="garmin-hrv-stale">
                    {garminHealth.latest.hrv} · {formatMeasurementDate(garminHealth.latest.measurement_date, lang)}
                  </p>
                )}
              </CardContent>
            </Card>

            <Card className="bg-card border-border" data-testid="garmin-resting-hr">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Heart className="w-4 h-4 text-rose-500" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {t("progressExtended.garminRestingHr")}
                  </span>
                </div>
                <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
                  {garminHealth.latest.is_current !== false
                    ? (garminHealth.latest.resting_hr ?? "--")
                    : "--"}
                  <span className="text-sm text-muted-foreground ml-1">bpm</span>
                </p>
                {garminHealth.latest.is_current === false && garminHealth.latest.resting_hr != null && (
                  <p className="font-mono text-[10px] text-amber-400 mt-1" data-testid="garmin-rhr-stale">
                    {garminHealth.latest.resting_hr} · {formatMeasurementDate(garminHealth.latest.measurement_date, lang)}
                  </p>
                )}
              </CardContent>
            </Card>

            <Card className="bg-card border-border" data-testid="garmin-sleep">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Moon className="w-4 h-4 text-blue-400" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {t("progressExtended.garminSleep")}
                  </span>
                </div>
                <p className="font-heading text-xl sm:text-3xl font-bold text-white break-words">
                  {garminHealth.latest.is_current !== false
                    ? (garminHealth.latest.sleep_hours ?? "--")
                    : "--"}
                  <span className="text-sm text-muted-foreground ml-1">h</span>
                </p>
                {garminHealth.latest.is_current === false && garminHealth.latest.sleep_hours != null && (
                  <p className="font-mono text-[10px] text-amber-400 mt-1" data-testid="garmin-sleep-stale">
                    {garminHealth.latest.sleep_hours} · {formatMeasurementDate(garminHealth.latest.measurement_date, lang)}
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Garmin native VO2MAX Section with sparse history */}
      <div className="mb-6">
        <Card className="bg-card border-border overflow-hidden">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-4">
                <div className="w-14 h-14 rounded-xl flex flex-col items-center justify-center" style={{ background: "rgba(110, 235, 90, 0.12)", border: "1px solid rgba(110, 235, 90, 0.25)" }}>
                  <Zap className="w-5 h-5" style={{ color: "#6EEB5A" }} />
                  <span className="text-[7px] font-mono uppercase mt-0.5" style={{ color: "rgba(110, 235, 90, 0.8)" }}>VO2MAX</span>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{t("progressExtended.garminVo2maxLabel")}</p>
                  <div className="flex items-baseline gap-2">
                    <span className="text-4xl font-bold text-white">
                      {garminVo2CurrentValue ?? "--"}
                    </span>
                    <span className="text-sm text-muted-foreground">ml/kg/min</span>
                  </div>
                  {garminVo2CurrentDate && (
                    <p className="text-xs text-muted-foreground">
                      {t("progressExtended.garminSourceLabel")} · {t("progressExtended.measurementDateLabel")} {formatMeasurementDate(garminVo2CurrentDate, lang)}
                    </p>
                  )}
                </div>
              </div>
            </div>

            {garminVo2CurrentValue == null ? (
              <p className="text-sm text-muted-foreground">{t("progressExtended.noGarminVo2maxAvailable")}</p>
            ) : null}

            {garminVo2Series.length > 0 ? (
              <div className="mt-4">
                <p className="text-[10px] font-mono uppercase text-muted-foreground mb-3">
                  {t("progressExtended.garminVo2maxHistoryTitle")}
                </p>
                <div className="h-36">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={garminVo2Series}
                      margin={{ top: 5, right: 10, left: -20, bottom: 5 }}
                    >
                      <XAxis
                        dataKey="date"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9, fontFamily: "JetBrains Mono" }}
                        tickFormatter={(dateStr) => formatDateLabel(dateStr, langToLocale(lang), "month")}
                        interval="preserveStartEnd"
                      />
                      <YAxis
                        domain={["dataMin - 2", "dataMax + 2"]}
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
                                  {formatMeasurementDate(data.date, lang)}
                                </p>
                                <p className="font-bold text-white">VO2MAX: {data.value} ml/kg/min</p>
                                <p className="text-[10px] text-muted-foreground">{t("progressExtended.garminSourceLabel")}</p>
                                {data.precise != null && (
                                  <p className="text-[10px] text-muted-foreground">{data.precise}</p>
                                )}
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      {garminVo2CurrentValue != null && (
                        <ReferenceLine
                          y={garminVo2CurrentValue}
                          stroke="rgba(110, 235, 90, 0.3)"
                          strokeDasharray="3 3"
                        />
                      )}
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke="#6EEB5A"
                        strokeWidth={2}
                        dot={{ fill: "#6EEB5A", strokeWidth: 0, r: 3 }}
                        activeDot={{ fill: "#6EEB5A", strokeWidth: 2, stroke: "white", r: 5 }}
                        connectNulls={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground mt-3">{t("progressExtended.noGarminVo2maxAvailable")}</p>
            )}
          </CardContent>
        </Card>
      </div>

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
                     {t("progressExtended.racePredictionBasis")}
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
                  {(() => {
                     // PR193: single lookup table for confidence — defined once, outside the per-prediction loop
                     const CONFIDENCE_MAP = {
                       high:         { i18nKey: "confidenceHigh",         color: "#22c55e" },
                       medium:       { i18nKey: "confidenceMedium",        color: "#f59e0b" },
                       low:          { i18nKey: "confidenceLow",           color: "#f97316" },
                       insufficient: { i18nKey: "confidenceInsufficient",  color: "#6b7280" },
                     };
                     const cycleGoalDist = cycleV2?.goal?.goal_type
                       ? V2_GOAL_TO_PRED_DISTANCE[cycleV2.goal.goal_type] ?? null
                       : null;
                     return predictions.predictions?.map((pred) => {
                     const isGoal = cycleGoalDist !== null && pred.distance === cycleGoalDist;
                     // PR193: colour and label derived from pred.confidence, not readiness
                     const { i18nKey: confidenceI18nKey, color: confidenceColor } =
                       CONFIDENCE_MAP[pred.confidence] ?? CONFIDENCE_MAP.insufficient;
                     const confidenceText = t(`progressExtended.${confidenceI18nKey}`);

                      return (
                      <div 
                        key={pred.distance}
                        className="flex items-center gap-3 p-3 rounded-xl transition-all"
                        style={{ 
                          background: isGoal ? "rgba(245,158,11,0.08)" : "rgba(255,255,255,0.03)",
                          border: isGoal ? "2px solid rgba(245,158,11,0.5)" : "1px solid rgba(255,255,255,0.05)"
                        }}
                      >
                        {/* Distance badge — GOAL badge attached here (PR193) */}
                        <div 
                          className="shrink-0 w-14 rounded-xl flex flex-col items-center justify-center gap-1 py-2"
                          style={{ background: `${confidenceColor}20` }}
                        >
                          <span className="text-sm font-bold" style={{ color: confidenceColor }}>
                            {pred.distance}
                          </span>
                          {isGoal && (
                            <span className="px-1.5 py-0.5 rounded-full text-[8px] font-bold leading-none" style={{ background: "var(--accent-green)", color: "#0a0e1a" }}>
                              {t("progressExtended.goalLabel")}
                            </span>
                          )}
                        </div>

                        {/* Predicted time */}
                        <div className="flex-1 min-w-0">
                          {pred.predicted_time ? (
                            <>
                              <span className="text-xl font-bold text-white">{pred.predicted_time}</span>
                              <p className="text-xs text-muted-foreground">
                                {pred.predicted_pace}
                              </p>
                            </>
                          ) : (
                            <span className="text-sm text-muted-foreground italic">
                              {t("progressExtended.notEnoughPredictionData")}
                            </span>
                          )}
                        </div>

                        {/* Confidence — PR193: replaces readiness display */}
                        <div className="shrink-0 text-right">
                          <p className="text-[9px] text-muted-foreground mb-0.5">
                            {t("progressExtended.confidenceLabel")}
                          </p>
                          <div 
                            className="px-2 py-0.5 rounded-full text-[10px] font-bold"
                            style={{ background: `${confidenceColor}20`, color: confidenceColor }}
                          >
                            {confidenceText}
                          </div>
                        </div>
                      </div>
                      );
                      });
                    })()}
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

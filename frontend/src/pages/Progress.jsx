import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
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
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Footprints,
  Calendar,
  Timer,
  Zap,
  Target,
  ArrowUpRight,
  ArrowDownRight,
  Heart,
  Moon
} from "lucide-react";
import Paywall from "@/components/Paywall";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default";

const formatDuration = (minutes) => {
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) {
    return `${hrs}h ${mins}m`;
  }
  return `${mins}m`;
};

export default function Progress() {
  const [stats, setStats] = useState(null);
  const [workouts, setWorkouts] = useState([]);
  const [predictions, setPredictions] = useState(null);
  const [fullCycle, setFullCycle] = useState(null);
  const [vmaHistory, setVmaHistory] = useState(null);
  const [garminHealth, setGarminHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showPredictions, setShowPredictions] = useState(true);
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading } = useSubscription();
  const { unitSystem } = useUnitSystem();

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, workoutsRes, predictionsRes, cycleRes, vmaHistoryRes] = await Promise.all([
          axios.get(`${API}/stats`),
          axios.get(`${API}/workouts`),
          axios.get(`${API}/training/race-predictions`, { headers: { "X-User-Id": USER_ID } }).catch(() => ({ data: null })),
          axios.get(`${API}/training/full-cycle`, { headers: { "X-User-Id": USER_ID } }).catch(() => ({ data: null })),
          axios.get(`${API}/training/vma-history`, { headers: { "X-User-Id": USER_ID } }).catch(() => ({ data: null }))
        ]);
        setStats(statsRes.data);
        setWorkouts(workoutsRes.data);

        // Garmin daily health metrics (HRV / resting HR / sleep)
        try {
          const garminRes = await axios.get(`${API}/garmin/daily-metrics?user_id=${USER_ID}&days=7`);
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
  }, []);

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

      {/* Weekly & Monthly Stats */}
      <div className="grid grid-cols-3 gap-3 mb-8">
        {/* Séances 7 jours */}
        <Card className="bg-card border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-4 h-4 text-primary" />
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("progressExtended.sessions7d")}
              </span>
            </div>
            <p className="font-heading text-3xl font-bold text-white">
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
            <p className="font-heading text-3xl font-bold text-white">
              {formatDistance(km7Days, { unitSystem })}
            </p>
          </CardContent>
        </Card>

        {/* Km 30 jours */}
        <Card className="bg-card border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Calendar className="w-4 h-4 text-violet-500" />
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("progressExtended.km30d")}
              </span>
            </div>
            <p className="font-heading text-3xl font-bold text-white">
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
          <div className="grid grid-cols-3 gap-3">
            <Card className="bg-card border-border" data-testid="garmin-hrv">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Activity className="w-4 h-4 text-emerald-500" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    HRV
                  </span>
                </div>
                <p className="font-heading text-3xl font-bold text-white">
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
                <p className="font-heading text-3xl font-bold text-white">
                  {garminHealth.latest.resting_hr ?? "--"}
                  <span className="text-sm text-muted-foreground ml-1">bpm</span>
                </p>
              </CardContent>
            </Card>

            <Card className="bg-card border-border" data-testid="garmin-sleep">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Moon className="w-4 h-4 text-violet-400" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Sleep
                  </span>
                </div>
                <p className="font-heading text-3xl font-bold text-white">
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
                  <div className="w-14 h-14 rounded-xl flex flex-col items-center justify-center" style={{ background: "linear-gradient(135deg, rgba(139,92,246,0.2) 0%, rgba(168,85,247,0.15) 100%)", border: "1px solid rgba(139,92,246,0.3)" }}>
                    <Zap className="w-5 h-5" style={{ color: "#a855f7" }} />
                    <span className="text-[7px] font-mono uppercase mt-0.5" style={{ color: "rgba(168,85,247,0.8)" }}>VO2MAX</span>
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
                          stroke="rgba(139,92,246,0.3)" 
                          strokeDasharray="3 3" 
                        />
                        <Line 
                          type="monotone" 
                          dataKey="vo2max" 
                          stroke="#a855f7" 
                          strokeWidth={2}
                          dot={{ fill: "#a855f7", strokeWidth: 0, r: 3 }}
                          activeDot={{ fill: "#a855f7", strokeWidth: 2, stroke: "white", r: 5 }}
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
                              <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: "#8b5cf6", color: "white" }}>
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

      {/* All Workouts */}
      <div>
        <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-4">
          {t("progress.allWorkouts")}
        </h2>
        <div className="space-y-3">
          {workouts.map((workout, index) => {
            const typeLabel = t(`workoutTypes.${workout.type}`) || workout.type;
            return (
              <Link
                key={workout.id}
                to={`/workout/${workout.id}`}
                data-testid={`progress-workout-${workout.id}`}
                className="block animate-in"
                style={{ animationDelay: `${index * 30}ms` }}
              >
                <Card className="metric-card bg-card border-border hover:border-primary/30 transition-colors">
                  <CardContent className="p-4">
                    <div className="flex items-center gap-4">
                      <div className="flex-shrink-0 w-10 h-10 flex items-center justify-center bg-muted border border-border">
                        <Footprints className="w-5 h-5 text-muted-foreground" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="workout-type-badge">
                            {typeLabel}
                          </span>
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {new Date(workout.date).toLocaleDateString(lang === "fr" ? "fr-FR" : "en-US", {
                              month: "short",
                              day: "numeric"
                            })}
                          </span>
                        </div>
                        <p className="font-medium text-sm truncate">
                          {workout.name}
                        </p>
                      </div>
                      <div className="flex items-center gap-4">
                        <div className="text-right">
                          <p className="font-mono text-sm font-medium">
                            {formatDistance(workout.distance_km || 0, { unitSystem })}
                          </p>
                          <p className="font-mono text-[10px] text-muted-foreground">
                            {formatDuration(workout.duration_minutes)}
                          </p>
                        </div>
                        <ChevronRight className="w-4 h-4 text-muted-foreground" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}

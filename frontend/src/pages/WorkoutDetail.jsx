import { useState, useEffect } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage } from "@/context/LanguageContext";
import {
  ArrowLeft,
  Heart,
  Zap,
  Scale,
  Activity,
  MessageSquare,
  Loader2,
  Bike,
  Footprints,
  HeartPulse,
  AlertCircle,
  Lightbulb,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;
const ALLOWED_BACK_ROUTES = new Set(["/sessions", "/training", "/progress"]);

const getWorkoutIcon = (type) => {
  if (type === "cycle") return Bike;
  return Footprints;
};

const formatDuration = (minutes) => {
  if (!minutes && minutes !== 0) return "--";
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) return `${hrs}h${mins > 0 ? mins : ""}`;
  return `${mins}m`;
};

const formatPaceDisplay = (pace) => {
  if (pace == null) return "--";
  const mins = Math.floor(pace);
  const secs = Math.round((pace % 1) * 60);
  return `${mins}:${String(secs).padStart(2, "0")}/km`;
};

const formatSignedMetric = (metric, suffix = "") => {
  if (!metric || metric.difference == null) return "--";
  const sign = metric.difference > 0 ? "+" : "";
  return `${sign}${metric.difference}${suffix}`;
};

const SplitsChart = ({ splits, t }) => {
  if (!splits || splits.length === 0) return null;

  const paces = splits.map((s) => s.pace_min_km);
  const minPace = Math.min(...paces);
  const maxPace = Math.max(...paces);
  const avgPace = paces.reduce((a, b) => a + b, 0) / paces.length;
  const chartMin = Math.max(0, minPace - 0.2);
  const chartMax = maxPace + 0.2;
  const range = chartMax - chartMin;
  const fastestIdx = paces.indexOf(minPace);
  const slowestIdx = paces.indexOf(maxPace);

  const getBarWidth = (pace) => ((chartMax - pace) / range) * 100;
  const getBarColor = (pace, idx) => {
    if (idx === fastestIdx) return "#22c55e";
    if (idx === slowestIdx) return "#f97316";
    if (pace < avgPace - 0.15) return "#3b82f6";
    if (pace > avgPace + 0.15) return "#eab308";
    return "#6EEB5A";
  };

  const formatPace = (pace) => {
    const mins = Math.floor(pace);
    const secs = Math.round((pace % 1) * 60);
    return `${mins}:${String(secs).padStart(2, "0")}`;
  };

  const displaySplits = splits.length > 25 ? splits.filter((_, i) => i % 2 === 0 || i === splits.length - 1) : splits;
  const showAllKm = splits.length <= 25;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs">
        <div className="flex gap-4">
          <div>
            <p className="font-mono text-[9px] text-muted-foreground uppercase">{t("workoutDetailExtended.fastest")}</p>
            <p className="font-mono text-xs font-semibold text-emerald-400">
              Km {splits[fastestIdx]?.km} • {splits[fastestIdx]?.pace_str}
            </p>
          </div>
          <div>
            <p className="font-mono text-[9px] text-muted-foreground uppercase">{t("workoutDetailExtended.slowest")}</p>
            <p className="font-mono text-xs font-semibold text-orange-400">
              Km {splits[slowestIdx]?.km} • {splits[slowestIdx]?.pace_str}
            </p>
          </div>
          <div>
            <p className="font-mono text-[9px] text-muted-foreground uppercase">{t("workoutDetailExtended.average")}</p>
            <p className="font-mono text-xs font-semibold">{formatPace(avgPace)}/km</p>
          </div>
        </div>
      </div>

      <div className="bg-muted/20 rounded-lg p-3 space-y-1">
        {(showAllKm ? splits : displaySplits).map((split, idx) => {
          const actualIdx = showAllKm ? idx : splits.findIndex((s) => s.km === split.km);
          const width = getBarWidth(split.pace_min_km);
          const color = getBarColor(split.pace_min_km, actualIdx);
          const isFastest = actualIdx === fastestIdx;
          const isSlowest = actualIdx === slowestIdx;

          return (
            <div key={split.km} className="flex items-center gap-2 group">
              <div className="w-8 text-right shrink-0">
                <span className={`font-mono text-[10px] ${isFastest ? "text-emerald-400 font-bold" : isSlowest ? "text-orange-400 font-bold" : "text-muted-foreground"}`}>
                  {split.km}
                </span>
              </div>

              <div className="flex-1 h-5 bg-muted/30 rounded-sm relative overflow-hidden">
                <div className="absolute top-0 bottom-0 w-px bg-white/40 z-10" style={{ left: `${getBarWidth(avgPace)}%` }} />
                <div
                  className={`h-full rounded-sm transition-all duration-300 flex items-center ${isFastest || isSlowest ? "ring-1 ring-white/20" : ""}`}
                  style={{ width: `${Math.max(width, 5)}%`, backgroundColor: color, minWidth: "20px" }}
                >
                  {width > 25 && (
                    <span className="font-mono text-[9px] text-white font-semibold px-1.5 drop-shadow-sm">
                      {split.pace_str}
                    </span>
                  )}
                </div>
              </div>

              <div className="w-12 shrink-0">
                <span className={`font-mono text-[10px] ${isFastest ? "text-emerald-400 font-bold" : isSlowest ? "text-orange-400 font-bold" : "text-muted-foreground"}`}>
                  {split.pace_str}
                </span>
              </div>

              {split.avg_hr && (
                <div className="w-14 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                  <span className="font-mono text-[9px] text-red-400">{split.avg_hr} bpm</span>
                </div>
              )}
            </div>
          );
        })}

        {!showAllKm && (
          <p className="text-center font-mono text-[9px] text-muted-foreground pt-2">
            {t("workoutDetailExtended.simplifiedView").replace("{count}", splits.length)}
          </p>
        )}
      </div>
    </div>
  );
};

const HRZonesChart = ({ zones, t }) => {
  if (!zones) return null;

  const zoneConfig = [
    { key: "z1", color: "#3B82F6", label: "Z1", desc: "recovery" },
    { key: "z2", color: "#22C55E", label: "Z2", desc: "endurance" },
    { key: "z3", color: "#EAB308", label: "Z3", desc: "tempo" },
    { key: "z4", color: "#F97316", label: "Z4", desc: "threshold" },
    { key: "z5", color: "#EF4444", label: "Z5", desc: "max" },
  ];
  const maxPct = Math.max(...zoneConfig.map((z) => zones[z.key] || 0), 1);

  return (
    <div className="space-y-2">
      {zoneConfig.map((zone) => {
        const pct = zones[zone.key] || 0;
        const barWidth = Math.max((pct / maxPct) * 100, pct > 0 ? 8 : 0);
        return (
          <div key={zone.key} className="flex items-center gap-2">
            <span className="font-mono text-[10px] w-6 text-muted-foreground">{zone.label}</span>
            <div className="flex-1 h-5 bg-muted/30 relative overflow-hidden">
              <div
                className="h-full transition-all duration-500 ease-out flex items-center"
                style={{ width: `${barWidth}%`, backgroundColor: zone.color, minWidth: pct > 0 ? "24px" : "0" }}
              >
                {pct > 0 && (
                  <span className="font-mono text-[10px] text-white font-semibold px-1.5 drop-shadow-sm">
                    {pct}%
                  </span>
                )}
              </div>
            </div>
            <span className="font-mono text-[9px] w-16 text-muted-foreground hidden sm:block">{t(`zones.${zone.desc}`)}</span>
          </div>
        );
      })}
    </div>
  );
};

const ZoneSummary = ({ zones, t }) => {
  if (!zones) return null;
  const easyPct = (zones.z1 || 0) + (zones.z2 || 0);
  const moderatePct = zones.z3 || 0;
  const hardPct = (zones.z4 || 0) + (zones.z5 || 0);
  let dominant = "balanced";
  let dominantColor = "text-chart-3";
  if (hardPct >= 50) {
    dominant = "hard";
    dominantColor = "text-chart-1";
  } else if (easyPct >= 60) {
    dominant = "easy";
    dominantColor = "text-chart-2";
  }

  return (
    <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
      <div className="flex gap-4">
        <div className="text-center">
          <p className="font-mono text-xs font-semibold text-chart-2">{easyPct}%</p>
          <p className="font-mono text-[8px] text-muted-foreground uppercase">{t("zones.easy")}</p>
        </div>
        <div className="text-center">
          <p className="font-mono text-xs font-semibold text-chart-3">{moderatePct}%</p>
          <p className="font-mono text-[8px] text-muted-foreground uppercase">{t("zones.moderate")}</p>
        </div>
        <div className="text-center">
          <p className="font-mono text-xs font-semibold text-chart-1">{hardPct}%</p>
          <p className="font-mono text-[8px] text-muted-foreground uppercase">{t("zones.hard")}</p>
        </div>
      </div>
      <div className={`px-2 py-1 rounded-sm ${dominant === "hard" ? "bg-chart-1/10" : dominant === "easy" ? "bg-chart-2/10" : "bg-chart-3/10"}`}>
        <p className={`font-mono text-[10px] font-semibold ${dominantColor}`}>{t(`zones.dominant_${dominant}`)}</p>
      </div>
    </div>
  );
};

const AnalysisSkeleton = () => (
  <div className="space-y-2">
    <Skeleton className="h-3 w-3/4" />
    <Skeleton className="h-3 w-full" />
    <Skeleton className="h-3 w-5/6" />
  </div>
);

const AnalysisError = ({ t }) => (
  <div className="flex items-center gap-2 text-muted-foreground">
    <AlertCircle className="w-3.5 h-3.5 shrink-0" />
    <span className="font-mono text-xs">{t("workoutDetailExtended.analysisUnavailable") || "Analyse indisponible"}</span>
  </div>
);

export default function WorkoutDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { t, lang } = useLanguage();
  const [workout, setWorkout] = useState(null);
  const [workoutLoading, setWorkoutLoading] = useState(true);
  const [workoutError, setWorkoutError] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(true);
  const [analysisError, setAnalysisError] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);

  useEffect(() => {
    setWorkout(null);
    setWorkoutLoading(true);
    setWorkoutError(false);
    setAnalysis(null);
    setAnalysisLoading(true);
    setAnalysisError(false);

    const controller = new AbortController();
    const { signal } = controller;

    axios.get(`${API}/workouts/${id}`, { signal })
      .then((res) => {
        setWorkout(res.data);
        setWorkoutLoading(false);
      })
      .catch((err) => {
        if (!axios.isCancel(err)) {
          setWorkoutError(true);
          setWorkoutLoading(false);
        }
      });

    axios.get(`${API}/coach/workout-analysis/${id}?language=${lang}`, { signal })
      .then((res) => {
        setAnalysis(res.data);
        setAnalysisLoading(false);
      })
      .catch((err) => {
        if (!axios.isCancel(err)) {
          setAnalysisError(true);
          setAnalysisLoading(false);
        }
      });

    return () => controller.abort();
  }, [id, lang]);

  const goToAskCoach = () => navigate("/coach");
  const backTo = ALLOWED_BACK_ROUTES.has(location.state?.from) ? location.state.from : "/sessions";

  if (workoutLoading) {
    return (
      <div className="p-4 pb-24 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.analyzing")}</span>
        </div>
      </div>
    );
  }

  if (!workout && analysisLoading) {
    return (
      <div className="p-4 pb-24 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.analyzing")}</span>
        </div>
      </div>
    );
  }

  if (workoutError || !workout) {
    return (
      <div className="p-4 pb-24" data-testid="workout-not-found">
        <Link to="/" className="inline-flex items-center gap-2 text-muted-foreground mb-6">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-xs uppercase">{t("workout.back")}</span>
        </Link>
        <p className="text-muted-foreground">{t("workout.notFound")}</p>
      </div>
    );
  }

  const Icon = getWorkoutIcon(workout.type);
  const typeLabel = t(`workoutTypes.${workout.type}`) || workout.type;
  const dateStr = new Date(workout.date).toLocaleDateString(lang === "fr" ? "fr-FR" : "en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const comparison = analysis?.comparison;
  const physiology = analysis?.physiology;
  const pacing = analysis?.pacing;
  const evidence = analysis?.evidence;

  const getSessionTypeStyle = (label) => {
    if (label === "hard" || label === "very_high") return "text-chart-1 bg-chart-1/10";
    if (label === "easy" || label === "low") return "text-chart-2 bg-chart-2/10";
    return "text-chart-3 bg-chart-3/10";
  };

  return (
    <div className="p-4 pb-24" data-testid="workout-detail">
      <div className="mb-4 flex items-center justify-between gap-3">
        <Link to={backTo} className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-[10px] uppercase tracking-widest">{t("workout.back")}</span>
        </Link>
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-muted-foreground" />
          <span className="font-mono text-[10px] uppercase text-muted-foreground">{typeLabel}</span>
        </div>
        <span className="font-mono text-[10px] text-muted-foreground">{dateStr}</span>
      </div>

      <h1 className="font-heading text-base uppercase tracking-tight font-bold mb-4 leading-tight">{workout.name}</h1>

      <Card className="bg-card border-border mb-3">
        <CardContent className="p-3">
          {analysisLoading ? (
            <AnalysisSkeleton />
          ) : analysisError ? (
            <AnalysisError t={t} />
          ) : analysis?.summary?.text ? (
            <p className="font-mono text-sm leading-relaxed" data-testid="coach-summary">{analysis.summary.text}</p>
          ) : null}
        </CardContent>
      </Card>

      <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Card className="bg-card border-border overflow-hidden">
          <CardContent className="p-2">
            <div className="flex items-center gap-1 mb-1">
              <Zap className="w-3 h-3 text-muted-foreground" />
              <span className="font-mono text-[8px] uppercase tracking-widest text-muted-foreground">{t("analysis.intensity")}</span>
            </div>
            {analysisLoading ? (
              <Skeleton className="h-5 w-full" />
            ) : analysis?.signals?.intensity?.available ? (
              <>
                <span className={`inline-block px-2 py-0.5 rounded-sm font-mono text-xs ${getSessionTypeStyle(analysis.signals.intensity.code)}`}>
                  {analysis.signals.intensity.text}
                </span>
                {physiology?.avg_hr != null && (
                  <p className="font-mono text-[10px] text-muted-foreground flex items-center gap-1 mt-1">
                    <Heart className="w-2.5 h-2.5" />
                    {physiology.avg_hr} bpm
                  </p>
                )}
              </>
            ) : analysis?.signals?.intensity ? (
              <div data-testid="intensity-card-unavailable">
                <span className="inline-block px-2 py-0.5 rounded-sm font-mono text-xs bg-muted text-muted-foreground">--</span>
                {analysis.signals.intensity.reason_unavailable && (
                  <p className="font-mono text-[10px] text-muted-foreground leading-relaxed mt-1">
                    {analysis.signals.intensity.reason_unavailable}
                  </p>
                )}
                {physiology?.avg_hr != null && (
                  <p className="font-mono text-[10px] text-muted-foreground flex items-center gap-1 mt-1">
                    <Heart className="w-2.5 h-2.5" />
                    {physiology.avg_hr} bpm
                  </p>
                )}
              </div>
            ) : (
              <span className="font-mono text-xs text-muted-foreground">--</span>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardContent className="p-2">
            <div className="flex items-center gap-1 mb-1">
              <Scale className="w-3 h-3 text-muted-foreground" />
              <span className="font-mono text-[8px] uppercase tracking-widest text-muted-foreground">{t("analysis.load")}</span>
            </div>
            {analysisLoading ? (
              <Skeleton className="h-5 w-full" />
            ) : analysis?.signals?.volume ? (
              <>
                <p className="font-mono text-xs font-semibold leading-tight">{analysis.signals.volume.text}</p>
                <p className="font-mono text-[10px] text-muted-foreground">{workout.distance_km} km • {formatDuration(workout.duration_minutes)}</p>
                {comparison?.distance_km && (
                  <p className="font-mono text-[9px] mt-1 text-muted-foreground">{formatSignedMetric(comparison.distance_km, " km")}</p>
                )}
              </>
            ) : (
              <span className="font-mono text-xs text-muted-foreground">--</span>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardContent className="p-2">
            <div className="flex items-center gap-1 mb-1">
              <Activity className="w-3 h-3 text-muted-foreground" />
              <span className="font-mono text-[8px] uppercase tracking-widest text-muted-foreground">{t("analysis.type")}</span>
            </div>
            {analysisLoading ? (
              <Skeleton className="h-5 w-full" />
            ) : analysis?.signals?.session_type ? (
              <div className={`inline-block px-2 py-1 rounded-sm ${getSessionTypeStyle(analysis.signals.session_type.code)}`}>
                <p className="font-mono text-xs font-semibold">{analysis.signals.session_type.text}</p>
              </div>
            ) : (
              <span className="font-mono text-xs text-muted-foreground">--</span>
            )}
          </CardContent>
        </Card>
      </div>

      {physiology?.available && physiology?.zone_distribution && (
        <Card className="bg-card border-border mb-3" data-testid="hr-zones-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <HeartPulse className="w-4 h-4 text-chart-1" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">{t("analysis.hrZones")}</span>
              {physiology.avg_hr != null && (
                <span className="ml-auto font-mono text-[10px] text-muted-foreground flex items-center gap-1">
                  <Heart className="w-3 h-3" />
                  {t("analysis.avgHr")}: {physiology.avg_hr} bpm
                </span>
              )}
            </div>
            <HRZonesChart zones={physiology.zone_distribution} t={t} />
            <ZoneSummary zones={physiology.zone_distribution} t={t} />
          </CardContent>
        </Card>
      )}

      {workout.km_splits && workout.km_splits.length > 0 && (
        <Card className="bg-card border-border mb-3" data-testid="splits-chart-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-4 h-4 text-primary" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.pacePerKm")}</span>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">{workout.km_splits.length} km</span>
            </div>
            <SplitsChart splits={workout.km_splits} t={t} />
          </CardContent>
        </Card>
      )}

      {pacing?.available && (
        <Card className="bg-card border-border mb-3" data-testid="pacing-summary-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-4 h-4 text-primary" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.comparison")}</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {pacing.average_pace_min_km != null && (
                <div>
                  <p className="font-mono text-[10px] text-muted-foreground">{t("workoutDetailExtended.average")}</p>
                  <p className="font-mono font-semibold">{formatPaceDisplay(pacing.average_pace_min_km)}</p>
                </div>
              )}
              {pacing.fastest_split_min_km != null && (
                <div>
                  <p className="font-mono text-[10px] text-muted-foreground">{t("workoutDetailExtended.fastest")}</p>
                  <p className="font-mono font-semibold">{formatPaceDisplay(pacing.fastest_split_min_km)}</p>
                </div>
              )}
              {pacing.slowest_split_min_km != null && (
                <div>
                  <p className="font-mono text-[10px] text-muted-foreground">{t("workoutDetailExtended.slowest")}</p>
                  <p className="font-mono font-semibold">{formatPaceDisplay(pacing.slowest_split_min_km)}</p>
                </div>
              )}
              {pacing.pace_drop_min_km != null && (
                <div>
                  <p className="font-mono text-[10px] text-muted-foreground">{t("workoutDetailExtended.paceDrop")}</p>
                  <p className="font-mono font-semibold">{formatPaceDisplay(pacing.pace_drop_min_km)}</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {comparison?.available && (
        <Card className="bg-card border-border mb-3" data-testid="comparison-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <Scale className="w-4 h-4 text-muted-foreground" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.comparison")}</span>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {comparison.distance_km && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[9px] uppercase text-muted-foreground">Distance</p>
                  <p className="font-mono text-xs">{formatSignedMetric(comparison.distance_km, " km")}</p>
                </div>
              )}
              {comparison.duration_minutes && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[9px] uppercase text-muted-foreground">Duration</p>
                  <p className="font-mono text-xs">{formatSignedMetric(comparison.duration_minutes, " min")}</p>
                </div>
              )}
              {comparison.avg_heart_rate && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[9px] uppercase text-muted-foreground">HR</p>
                  <p className="font-mono text-xs">{formatSignedMetric(comparison.avg_heart_rate, " bpm")}</p>
                </div>
              )}
              {(comparison.avg_pace_min_km || comparison.avg_speed_kmh) && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[9px] uppercase text-muted-foreground">Pace / Speed</p>
                  <p className="font-mono text-xs">
                    {comparison.avg_pace_min_km
                      ? formatSignedMetric(comparison.avg_pace_min_km, "/km")
                      : formatSignedMetric(comparison.avg_speed_kmh, " km/h")}
                  </p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border mb-3">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-muted-foreground" />
            <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.meaning")}</span>
          </div>
          {analysisLoading ? (
            <AnalysisSkeleton />
          ) : analysisError ? (
            <AnalysisError t={t} />
          ) : analysis?.meaning?.text ? (
            <p className="font-mono text-xs text-muted-foreground leading-relaxed" data-testid="meaning-text">{analysis.meaning.text}</p>
          ) : null}
        </CardContent>
      </Card>

      <Card className="bg-primary/5 border-primary/20 mb-3">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-2">
            <Lightbulb className="w-4 h-4 text-primary" />
            <span className="font-mono text-[10px] uppercase tracking-widest text-primary">{t("workoutDetailExtended.coachAdvice")}</span>
          </div>
          {analysisLoading ? (
            <AnalysisSkeleton />
          ) : analysisError ? (
            <AnalysisError t={t} />
          ) : analysis?.advice?.text ? (
            <p className="font-mono text-xs text-primary leading-relaxed" data-testid="advice-text">{analysis.advice.text}</p>
          ) : null}
        </CardContent>
      </Card>

      {(analysisLoading || analysis || analysisError) && (
        <Card className="bg-card border-border mb-3">
          <CardContent className="p-3">
            {analysisLoading ? (
              <AnalysisSkeleton />
            ) : (
              <>
                <button
                  onClick={() => setShowEvidence(!showEvidence)}
                  className="w-full flex items-center justify-between text-left"
                  data-testid="advanced-toggle"
                >
                  <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.goFurther")}</span>
                  {showEvidence ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
                </button>
                {showEvidence && analysis && (
                  <div className="mt-3 border-t border-border pt-3 space-y-2" data-testid="evidence-card">
                    <p className="font-mono text-[11px] text-muted-foreground">version: {analysis.version}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">HR: {evidence?.has_heart_rate ? "yes" : "no"}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">HR zones: {evidence?.has_hr_zones ? "yes" : "no"}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">Splits: {evidence?.has_splits ? "yes" : "no"}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">Baseline: {evidence?.has_baseline ? `yes (${comparison?.baseline_sample_count})` : "no"}</p>
                    {!physiology?.available && physiology?.reason_unavailable && (
                      <p className="font-mono text-[11px] text-muted-foreground">{physiology.reason_unavailable}</p>
                    )}
                    {!comparison?.available && comparison?.reason_unavailable && (
                      <p className="font-mono text-[11px] text-muted-foreground">{comparison.reason_unavailable}</p>
                    )}
                    {!pacing?.available && pacing?.reason_unavailable && (
                      <p className="font-mono text-[11px] text-muted-foreground">{pacing.reason_unavailable}</p>
                    )}
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      <div className="mt-4">
        <Button
          onClick={goToAskCoach}
          data-testid="ask-coach-btn"
          className="w-full bg-primary text-white hover:bg-primary/90 rounded-none h-10 font-mono text-xs uppercase tracking-wider flex items-center justify-center gap-2"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          {t("workoutDetailExtended.askCoach")}
        </Button>
      </div>
    </div>
  );
}

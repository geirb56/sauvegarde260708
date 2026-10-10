import { useState, useEffect } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage } from "@/context/LanguageContext";
import { formatPaceDisplay, formatPaceDelta, getAnalysisLimitations, hasCoachObservation } from "@/lib/workoutAnalysis";
import { formatSpeed } from "@/utils/units";
import {
  ArrowLeft,
  Scale,
  Activity,
  MessageSquare,
  Loader2,
  Bike,
  Footprints,
  AlertCircle,
} from "lucide-react";

import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;
const ALLOWED_BACK_ROUTES = new Set(["/sessions", "/training", "/progress"]);
const hasPositiveFiniteMetric = (value) => Number.isFinite(value) && value > 0;

const getWorkoutIcon = (type) => {
  if (type === "cycle") return Bike;
  return Footprints;
};

const formatDuration = (minutes) => {
  if (!Number.isFinite(minutes) || minutes < 0) return "--";
  const roundedMinutes = Math.round(minutes);
  const hrs = Math.floor(roundedMinutes / 60);
  const mins = roundedMinutes % 60;
  if (hrs > 0) return `${hrs}h${mins > 0 ? mins : ""}`;
  return `${mins}m`;
};

const formatHeartRate = (value) => Number.isFinite(value) ? `${Math.round(value)} bpm` : "--";

const distanceNumberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  useGrouping: false,
});

export const formatDistance = (value) => {
  if (!Number.isFinite(value)) return "--";
  const rounded = distanceNumberFormatter.format(value);
  return `${rounded === "-0" ? "0" : rounded} km`;
};

export const formatSignedDistance = (metric) => {
  const distance = formatDistance(metric?.difference);
  if (distance === "--" || distance === "0 km") return distance;
  return `${metric.difference > 0 ? "+" : ""}${distance}`;
};

const formatSignedMetric = (metric, suffix = "", round = false) => {
  if (!metric || metric.difference == null || !Number.isFinite(metric.difference)) return "--";
  const difference = round ? Math.round(metric.difference) : metric.difference;
  const sign = difference > 0 ? "+" : "";
  return `${sign}${difference}${suffix}`;
};

const SplitsChart = ({ splits, t }) => {
  const validSplits = Array.isArray(splits) ? splits.filter((split) => Number.isFinite(split?.pace_min_km) && split.pace_min_km > 0) : [];
  if (validSplits.length === 0) return null;
  splits = validSplits;

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

  return (
    <div className="space-y-3">
      <div className="text-xs">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="font-mono text-[11px] text-muted-foreground uppercase">{t("workoutDetailExtended.fastest")}</p>
            <p className="font-mono text-xs font-semibold text-emerald-400">
              Km {splits[fastestIdx]?.km} • {formatPaceDisplay(minPace)}
            </p>
          </div>
          <div>
            <p className="font-mono text-[11px] text-muted-foreground uppercase">{t("workoutDetailExtended.slowest")}</p>
            <p className="font-mono text-xs font-semibold text-orange-400">
              Km {splits[slowestIdx]?.km} • {formatPaceDisplay(maxPace)}
            </p>
          </div>
        </div>
      </div>

      <div className="bg-muted/20 rounded-lg p-2 max-h-96 overflow-y-auto" tabIndex={0} role="region" aria-label={t("workoutDetailExtended.pacePerKm")}>
        {splits.map((split, actualIdx) => {
          const width = getBarWidth(split.pace_min_km);
          const color = getBarColor(split.pace_min_km, actualIdx);
          const isFastest = actualIdx === fastestIdx;
          const isSlowest = actualIdx === slowestIdx;

          return (
            <div key={`${split.km}-${actualIdx}`} className="flex min-h-11 items-center gap-2">
              <div className="w-8 text-right shrink-0">
                <span className={`font-mono text-[11px] ${isFastest ? "text-emerald-400 font-bold" : isSlowest ? "text-orange-400 font-bold" : "text-muted-foreground"}`}>
                  {split.km}
                </span>
              </div>

              <div className="flex-1 min-w-0 h-5 bg-muted/30 rounded-sm relative overflow-hidden">
                <div className="absolute top-0 bottom-0 w-px bg-white/40 z-10" style={{ left: `${getBarWidth(avgPace)}%` }} />
                <div
                  className={`h-full rounded-sm transition-all duration-300 flex items-center ${isFastest || isSlowest ? "ring-1 ring-white/20" : ""}`}
                  style={{ width: `${Math.max(width, 5)}%`, backgroundColor: color, minWidth: "20px" }}
                >
                  {width > 25 && (
                    <span className="font-mono text-[11px] text-primary-foreground font-semibold px-1.5">
                      {formatPaceDisplay(split.pace_min_km).replace("/km", "")}
                    </span>
                  )}
                </div>
              </div>

              <div className="w-12 shrink-0">
                <span className={`font-mono text-[11px] ${isFastest ? "text-emerald-400 font-bold" : isSlowest ? "text-orange-400 font-bold" : "text-muted-foreground"}`}>
                  {formatPaceDisplay(split.pace_min_km).replace("/km", "")}
                </span>
              </div>

              {Number.isFinite(split.avg_hr) && split.avg_hr > 0 && (
                <div className="w-14 shrink-0">
                  <span className="font-mono text-[11px] text-red-400">{formatHeartRate(split.avg_hr)}</span>
                </div>
              )}
            </div>
          );
        })}

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
  const validZones = zoneConfig.filter((zone) => Number.isFinite(zones[zone.key]) && zones[zone.key] >= 0 && zones[zone.key] <= 100);
  const maxPct = Math.max(...validZones.map((z) => zones[z.key]), 1);

  return (
    <div className="space-y-2">
      {validZones.map((zone) => {
        const pct = zones[zone.key];
        const barWidth = Math.max((pct / maxPct) * 100, pct > 0 ? 8 : 0);
        return (
          <div key={zone.key} className="flex items-center gap-2">
            <span className="font-mono text-[11px] w-6 text-muted-foreground">{zone.label}</span>
            <div className="flex-1 h-5 bg-muted/30 relative overflow-hidden">
              <div
                className="h-full transition-all duration-500 ease-out flex items-center"
                style={{ width: `${barWidth}%`, backgroundColor: zone.color, minWidth: pct > 0 ? "24px" : "0" }}
              >
                {pct > 0 && (
                  <span className="font-mono text-[11px] text-primary-foreground font-semibold px-1.5">
                    {pct}%
                  </span>
                )}
              </div>
            </div>
            <span className="font-mono text-xs w-12 shrink-0 text-right">{pct}%</span>
          </div>
        );
      })}
    </div>
  );
};

const formatPhaseDuration = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const rounded = Math.round(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainingSeconds = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`
    : `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
};

const formatPhaseNumber = (value, lang, digits = 1) => new Intl.NumberFormat(
  { fr: "fr-FR", en: "en-US", es: "es-ES" }[lang] || "en-US",
  { maximumFractionDigits: digits },
).format(value);

const phaseMissingLabels = {
  duration: "phaseMissingDuration",
  distance: "phaseMissingDistance",
  pace: "phaseMissingPace",
  heart_rate: "phaseMissingHeartRate",
};

const phaseLimitationLabels = {
  incoherent_pace: "phaseLimitationIncoherentPace",
  efforts_not_comparable: "phaseLimitationNotComparable",
  efforts_partially_comparable: "phaseLimitationPartiallyComparable",
  effort_paces_incomplete: "phaseLimitationIncompletePaces",
  insufficient_comparable_effort_paces: "phaseLimitationInsufficientPaces",
};

const PhaseMetric = ({ label, value }) => (
  <div className="min-w-0">
    <dt className="text-xs text-muted-foreground">{label}</dt>
    <dd className="font-mono text-sm font-semibold break-words">{value}</dd>
  </div>
);

const WorkoutPhaseAnalysis = ({ phaseAnalysis, t, lang }) => {
  if (phaseAnalysis?.available !== true) return null;

  const sortPhases = (phases) => (Array.isArray(phases) ? phases : [])
      .map((phase, index) => ({ phase, index }))
      .sort((left, right) => {
        const leftOrder = Number.isFinite(left.phase?.order) ? left.phase.order : left.index;
        const rightOrder = Number.isFinite(right.phase?.order) ? right.phase.order : right.index;
        return leftOrder - rightOrder || left.index - right.index;
      })
      .map(({ phase }) => phase);
  const efforts = sortPhases(phaseAnalysis.efforts)
    .filter((phase) => phase?.phase_type === "effort");
  const recoveries = sortPhases(phaseAnalysis.recoveries)
    .filter((phase) => phase?.phase_type === "recovery");
  const chronologicalPhases = sortPhases(phaseAnalysis.phases);
  const recoveryAfterEffort = new Map();
  const associatedRecoveryPhases = new Set();
  chronologicalPhases.forEach((phase, index) => {
    const next = chronologicalPhases[index + 1];
    if (phase?.phase_type === "effort" && next?.phase_type === "recovery") {
      recoveryAfterEffort.set(phase.order, next);
      associatedRecoveryPhases.add(next);
    }
  });
  const phaseRows = [];
  if (chronologicalPhases.length > 0) {
    chronologicalPhases.forEach((phase) => {
      if (phase?.phase_type === "effort") {
        phaseRows.push({ kind: "effort", phase, associatedRecovery: recoveryAfterEffort.get(phase.order) || null });
      } else if (phase?.phase_type === "recovery") {
        if (!associatedRecoveryPhases.has(phase)) phaseRows.push({ kind: "recovery", phase });
      } else {
        phaseRows.push({ kind: "additional", phase });
      }
    });
  } else {
    efforts.forEach((phase) => phaseRows.push({ kind: "effort", phase, associatedRecovery: null }));
    recoveries.forEach((phase) => phaseRows.push({ kind: "recovery", phase }));
  }
  const effortStatistics = phaseAnalysis.effort_statistics || {};
  const regularity = phaseAnalysis.effort_regularity || {};
  const missingData = Array.isArray(phaseAnalysis.missing_data) ? phaseAnalysis.missing_data : [];
  const limitations = Array.isArray(phaseAnalysis.limitations) ? phaseAnalysis.limitations : [];
  const number = (value, digits = 1) => Number.isFinite(value) ? formatPhaseNumber(value, lang, digits) : null;
  const secondsDelta = (value) => {
    if (!Number.isFinite(value)) return null;
    const formatted = formatPhaseNumber(Math.abs(value), lang, 1);
    return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatted} s/km`;
  };
  const interpolate = (key, values) => Object.entries(values).reduce(
    (text, [name, value]) => text.replace(`{${name}}`, String(value)),
    t(`workoutDetailExtended.${key}`),
  );
  const phaseMetrics = (phase) => [
    [t("workoutDetailExtended.duration"), formatPhaseDuration(phase?.duration_s)],
    [t("workoutDetailExtended.distance"), Number.isFinite(phase?.distance_m) && phase.distance_m >= 0
      ? `${formatPhaseNumber(phase.distance_m, lang, 0)} m`
      : null],
    [t("workoutDetailExtended.pace"), Number.isFinite(phase?.pace_sec_per_km) && phase.pace_sec_per_km > 0
      ? formatPaceDisplay(phase.pace_sec_per_km / 60)
      : null],
    [t("workoutDetailExtended.averageHeartRate"), Number.isFinite(phase?.average_hr) && phase.average_hr > 0
      ? formatHeartRate(phase.average_hr)
      : null],
    [t("workoutDetailExtended.maximumHeartRate"), Number.isFinite(phase?.max_hr) && phase.max_hr > 0
      ? formatHeartRate(phase.max_hr)
      : null],
  ];
  const supplementaryPhaseLabel = (phase) => {
    if (phase?.phase_type === "warmup") return t("workoutDetailExtended.phaseWarmup");
    if (phase?.phase_type === "cooldown") return t("workoutDetailExtended.phaseCooldown");
    return t("workoutDetailExtended.phaseOther");
  };
  const uniqueMessages = (items, labels, fallback) => {
    const messages = items.map((item) => labels[item]).filter(Boolean).map((key) => t(`workoutDetailExtended.${key}`));
    if (items.some((item) => !labels[item])) messages.push(t(`workoutDetailExtended.${fallback}`));
    return [...new Set(messages)];
  };

  return (
    <section aria-labelledby="structured-phases-title" data-testid="structured-phase-analysis">
      <h2 id="structured-phases-title" className="text-base font-semibold mb-2">
        {t("workoutDetailExtended.structuredPhases")}
      </h2>
      <Card className="bg-card border-border">
        <CardContent className="p-4 space-y-4">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3" data-testid="phase-summary">
            <PhaseMetric label={t("workoutDetailExtended.effortCount")} value={efforts.length} />
            <PhaseMetric label={t("workoutDetailExtended.recoveryCount")} value={recoveries.length} />
            {Number.isFinite(effortStatistics.total_duration_s) && effortStatistics.total_duration_s >= 0 && (
              <PhaseMetric
                label={t("workoutDetailExtended.totalEffortDuration")}
                value={formatPhaseDuration(effortStatistics.total_duration_s) || t("workoutDetailExtended.dataUnavailable")}
              />
            )}
            {Number.isFinite(effortStatistics.total_distance_m) && effortStatistics.total_distance_m >= 0 && (
              <PhaseMetric
                label={t("workoutDetailExtended.totalEffortDistance")}
                value={`${formatPhaseNumber(effortStatistics.total_distance_m / 1000, lang, 2)} km`}
              />
            )}
            {Number.isFinite(effortStatistics.average_pace_sec_per_km) && effortStatistics.average_pace_sec_per_km > 0 && (
              <PhaseMetric
                label={t("workoutDetailExtended.averageEffortPace")}
                value={formatPaceDisplay(effortStatistics.average_pace_sec_per_km / 60)}
              />
            )}
          </dl>

          {efforts.length === 0 && <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.phaseNoEfforts")}</p>}
          {phaseRows.length > 0 && <div className="space-y-3">
            {efforts.length > 0 && <h3 className="text-sm font-semibold">{t("workoutDetailExtended.repetitions")}</h3>}
            <ol className="space-y-3">
              {phaseRows.map((row, index) => {
                if (row.kind === "effort") {
                  const effort = row.phase;
                  return (
                    <li key={`${effort.order ?? index}-${index}`} data-testid="phase-effort-card" className="rounded-md border border-border/70 p-3 min-w-0">
                      <h4 className="text-sm font-semibold mb-2">
                        {interpolate("effortNumber", { number: effort.effort_number ?? index + 1 })}
                      </h4>
                      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
                        {phaseMetrics(effort).map(([label, value]) => (
                          <PhaseMetric key={label} label={label} value={value || t("workoutDetailExtended.dataUnavailable")} />
                        ))}
                      </dl>
                      {row.associatedRecovery && <div className="mt-3 border-t border-border/70 pt-3">
                        <h5 className="text-xs font-semibold text-muted-foreground mb-2">{t("workoutDetailExtended.recoveryAfterEffort")}</h5>
                        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
                          {phaseMetrics(row.associatedRecovery).map(([label, value]) => (
                            <PhaseMetric key={label} label={label} value={value || t("workoutDetailExtended.dataUnavailable")} />
                          ))}
                        </dl>
                      </div>}
                    </li>
                  );
                }
                if (row.kind === "recovery") {
                  return (
                    <li key={`${row.phase.order ?? index}-${index}`} data-testid="phase-recovery-card" className="rounded-md bg-muted/20 p-3 min-w-0">
                      <h4 className="text-sm font-semibold mb-2">
                        {interpolate("phaseRecoveryNumber", { number: row.phase.recovery_number ?? index + 1 })}
                      </h4>
                      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
                        {phaseMetrics(row.phase).map(([label, value]) => (
                          <PhaseMetric key={label} label={label} value={value || t("workoutDetailExtended.dataUnavailable")} />
                        ))}
                      </dl>
                    </li>
                  );
                }
                return (
                  <li key={`${row.phase?.order ?? index}-${index}`} data-testid="phase-additional-card" className="rounded-md bg-muted/20 p-3 min-w-0">
                    <h4 className="text-sm font-semibold mb-2">{supplementaryPhaseLabel(row.phase)}</h4>
                    <dl className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
                      {phaseMetrics(row.phase).map(([label, value]) => (
                        <PhaseMetric key={label} label={label} value={value || t("workoutDetailExtended.dataUnavailable")} />
                      ))}
                    </dl>
                  </li>
                );
              })}
            </ol>
          </div>}

          {regularity.available === true && <section className="space-y-2" data-testid="effort-regularity">
            <h3 className="text-sm font-semibold">{t("workoutDetailExtended.effortRegularity")}</h3>
            <p className="text-sm">
              {interpolate("comparableEfforts", {
                count: number(regularity.comparable_effort_count, 0) ?? t("workoutDetailExtended.dataUnavailable"),
              })}
            </p>
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Number.isFinite(regularity.pace_dispersion_sec_per_km) && regularity.pace_dispersion_sec_per_km >= 0 && (
                <PhaseMetric
                  label={t("workoutDetailExtended.paceDispersion")}
                  value={`${number(regularity.pace_dispersion_sec_per_km)} s/km`}
                />
              )}
              {secondsDelta(regularity.first_to_last_pace_change_sec_per_km) != null && (
                <PhaseMetric
                  label={t("workoutDetailExtended.firstToLastPace")}
                  value={secondsDelta(regularity.first_to_last_pace_change_sec_per_km)}
                />
              )}
              {Number.isFinite(regularity.average_hr_change_bpm) && (
                <PhaseMetric
                  label={t("workoutDetailExtended.averageHeartRateEvolution")}
                  value={`${regularity.average_hr_change_bpm > 0 ? "+" : ""}${number(regularity.average_hr_change_bpm)} bpm`}
                />
              )}
            </dl>
            {regularity.partial_comparison === true && (
              <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.partialEffortComparison")}</p>
            )}
          </section>}

          {(missingData.length > 0 || limitations.length > 0) && <section className="space-y-2" data-testid="phase-data-limits">
            <h3 className="text-sm font-semibold">{t("workoutDetailExtended.phaseDataLimits")}</h3>
            {uniqueMessages(missingData, phaseMissingLabels, "phaseMissingGeneric").map((message) => (
              <p key={message} className="text-sm text-muted-foreground">{message}</p>
            ))}
            {uniqueMessages(limitations, phaseLimitationLabels, "phaseLimitationGeneric").map((message) => (
              <p key={message} className="text-sm text-muted-foreground">{message}</p>
            ))}
          </section>}
        </CardContent>
      </Card>
    </section>
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
    <span className="font-sans text-sm">{t("workoutDetailExtended.analysisLoadError")}</span>
  </div>
);

export default function WorkoutDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { t, lang } = useLanguage();
  const [workout, setWorkout] = useState(null);
  const [workoutLoading, setWorkoutLoading] = useState(true);
  const [workoutError, setWorkoutError] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(true);
  const [analysisError, setAnalysisError] = useState(false);

  useEffect(() => {
    setWorkout(null);
    setWorkoutLoading(true);
    setWorkoutError(null);
    setAnalysis(null);
    setAnalysisLoading(true);
    setAnalysisError(false);

    const controller = new AbortController();
    const { signal } = controller;

    axios.get(`${API}/workouts/${id}`, { signal })
      .then((res) => {
        if (signal.aborted) return;
        setWorkout(res.data);
        setWorkoutLoading(false);
      })
      .catch((err) => {
        if (!signal.aborted && !axios.isCancel(err)) {
          setWorkoutError(err.response?.status === 404 ? "missing" : "network");
          setWorkoutLoading(false);
        }
      });

    axios.get(`${API}/coach/workout-analysis/${id}?language=${lang}`, { signal })
      .then((res) => {
        if (signal.aborted) return;
        setAnalysis(res.data);
        setAnalysisLoading(false);
      })
      .catch((err) => {
        if (!signal.aborted && !axios.isCancel(err)) {
          setAnalysisError(true);
          setAnalysisLoading(false);
        }
      });

    return () => controller.abort();
  }, [id, lang]);

  const goToAskCoach = () => navigate(id ? `/coach?analyze=${encodeURIComponent(id)}` : "/coach");
  const backTo = ALLOWED_BACK_ROUTES.has(location.state?.from) ? location.state.from : "/sessions";

  if (workoutLoading) {
    return (
      <div className="p-4 pb-24 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">{t("workoutDetailExtended.analyzing")}</span>
        </div>
      </div>
    );
  }

  if (workoutError || !workout) {
    return (
      <div className="p-4 pb-24" data-testid="workout-not-found">
        <Link to={backTo} className="inline-flex items-center gap-2 text-muted-foreground mb-6">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-xs uppercase">{t("workout.back")}</span>
        </Link>
        <p className="text-muted-foreground">{t(workoutError === "network" ? "workoutDetailExtended.workoutLoadError" : "workout.notFound")}</p>
      </div>
    );
  }

  const Icon = getWorkoutIcon(workout.type);
  const translatedType = t(`workoutTypes.${workout.type}`);
  const typeLabel = translatedType === `workoutTypes.${workout.type}` ? (workout.type || t("workoutDetailExtended.dataUnavailable")) : translatedType;
  const date = workout.date ? new Date(workout.date) : null;
  const dateStr = date && Number.isFinite(date.getTime()) ? date.toLocaleDateString({ fr: "fr-FR", en: "en-US", es: "es-ES" }[lang], {
    weekday: "short",
    month: "short",
    day: "numeric",
  }) : t("workoutDetailExtended.dataUnavailable");
  const comparison = analysis?.comparison;
  const physiology = analysis?.physiology;
  const pacing = analysis?.pacing;
  const isCycle = workout.type === "cycle";
  const averageSpeed = hasPositiveFiniteMetric(workout.avg_speed_kmh) ? workout.avg_speed_kmh
    : pacing?.available === true && hasPositiveFiniteMetric(pacing.average_speed_kmh) ? pacing.average_speed_kmh : null;
  const hasWorkoutPace = hasPositiveFiniteMetric(workout.avg_pace_min_km);
  const showSummarySpeed = isCycle || (!hasWorkoutPace && averageSpeed != null);
  const hasAveragePace = hasPositiveFiniteMetric(pacing?.average_pace_min_km);
  const showPacingSpeed = isCycle || !hasAveragePace;
  const evidence = analysis?.evidence;
  const similar = comparison?.similar;
  const hasAnalysis = Boolean(analysis && !analysisLoading && !analysisError);
  const displayMetric = (value) => value === "--" ? t("workoutDetailExtended.dataUnavailable") : value;
  const avgHr = Number.isFinite(workout.avg_heart_rate) && workout.avg_heart_rate > 0 ? workout.avg_heart_rate : physiology?.avg_hr;
  const maxHr = Number.isFinite(workout.max_heart_rate) && workout.max_heart_rate > 0 ? workout.max_heart_rate : physiology?.max_hr;
  const hasHr = (Number.isFinite(avgHr) && avgHr > 0) || (Number.isFinite(maxHr) && maxHr > 0);
  const hasSplits = Array.isArray(workout.km_splits) && workout.km_splits.some((split) => Number.isFinite(split?.pace_min_km) && split.pace_min_km > 0);
  const hasZones = physiology?.available === true && ["z1", "z2", "z3", "z4", "z5"].some((key) => Number.isFinite(physiology.zone_distribution?.[key]) && physiology.zone_distribution[key] > 0 && physiology.zone_distribution[key] <= 100);
  const hasPacing = pacing?.available === true && (
    (!isCycle && hasAveragePace) || (showPacingSpeed && hasPositiveFiniteMetric(pacing.average_speed_kmh))
    || ["fastest_split_min_km", "slowest_split_min_km"].some((key) => hasPositiveFiniteMetric(pacing[key]))
    || ["pace_drop_min_km", "consistency_score", "variability"].some((key) => Number.isFinite(pacing[key]))
  );
  const technicalLimitations = getAnalysisLimitations(analysis, t);
  const hasLimitation = (code) => technicalLimitations.some((item) => item.code === `limitations.${code}`);
  const observationAvailable = hasCoachObservation(analysis);
  const interpolate = (key, values) => Object.entries(values).reduce(
    (text, [name, value]) => text.replace(`{${name}}`, value == null ? t("workoutDetailExtended.dataUnavailable") : String(value)),
    t(`workoutDetailExtended.${key}`),
  );
  const formatSampleCount = (count) => interpolate(count === 1 ? "sampleCountOne" : "sampleCount", { count });

  const getSessionTypeStyle = (label) => {
    if (label === "hard" || label === "very_high") return "text-chart-1 bg-chart-1/10";
    if (label === "easy" || label === "low") return "text-chart-2 bg-chart-2/10";
    return "text-chart-3 bg-chart-3/10";
  };

  return (
    <div className="p-4 pb-24 max-w-3xl mx-auto min-w-0 break-words space-y-5" data-testid="workout-detail">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to={backTo} className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-[11px] uppercase tracking-widest">{t("workout.back")}</span>
        </Link>
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-muted-foreground" />
          <span className="font-mono text-[11px] uppercase text-muted-foreground">{typeLabel}</span>
        </div>
      </div>

      <section aria-labelledby="session-summary-title" data-testid="session-summary">
        <h2 id="session-summary-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.sessionSummary")}</h2>
        <Card className="bg-card border-border">
        <CardContent className="p-4 space-y-3">
          <div>
            <h1 className="font-heading text-xl font-bold leading-tight">{workout.name || typeLabel}</h1>
            <p className="text-sm text-muted-foreground mt-1">{dateStr} · {typeLabel}</p>
          </div>
          <dl className="grid grid-cols-2 gap-3" data-testid="primary-metrics">
            {[
              ["distance", formatDistance(workout.distance_km)],
              ["duration", formatDuration(workout.duration_minutes)],
              showSummarySpeed
                ? ["averageSpeed", averageSpeed == null ? t("workoutDetailExtended.speedUnavailable") : formatSpeed(averageSpeed, { unitSystem: "metric" })]
                : ["averagePace", hasWorkoutPace ? formatPaceDisplay(workout.avg_pace_min_km) : "--"],
              ...(Number.isFinite(avgHr) && avgHr > 0 ? [["averageHeartRate", formatHeartRate(avgHr)]] : []),
            ].map(([label, value]) => <div key={label} className="min-w-0">
              <dt className="text-sm text-muted-foreground">{t(`workoutDetailExtended.${label}`)}</dt>
              <dd className="text-base font-semibold">{displayMetric(value)}</dd>
            </div>)}
          </dl>
          {analysisLoading ? (
            <AnalysisSkeleton />
          ) : analysisError ? (
            <AnalysisError t={t} />
          ) : analysis?.summary?.text ? (
            <p className="font-sans text-sm leading-relaxed" data-testid="coach-summary">{analysis.summary.text}</p>
          ) : <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.analysisUnavailable")}</p>}
        </CardContent>
      </Card>
      </section>

      <WorkoutPhaseAnalysis phaseAnalysis={analysis?.phase_analysis} t={t} lang={lang} />

      {hasAnalysis && <section aria-labelledby="takeaways-title">
        <h2 id="takeaways-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.takeaways")}</h2>
        <Card className="bg-card border-border"><CardContent className="p-4 space-y-3">
          <p className="text-sm leading-relaxed" data-testid="meaning-text">{analysis.meaning?.text || t("workoutDetailExtended.meaningUnavailable")}</p>
          <div className="flex flex-wrap gap-2">
            {[["volume", "load"], ["session_type", "type"]].map(([key, label]) => analysis.signals?.[key]?.available === true && analysis.signals[key].text ? (
              <p key={key} className="text-sm rounded bg-muted/30 p-2">{t(`analysis.${label}`)}: {analysis.signals[key].text}</p>
            ) : null)}
          </div>
          {analysis.signals?.intensity?.available === true && analysis.signals.intensity.text ? (
            <p className={`text-sm rounded p-2 ${getSessionTypeStyle(analysis.signals.intensity.code)}`}>{t("analysis.intensity")}: {analysis.signals.intensity.text}</p>
          ) : <p className="text-sm text-muted-foreground" data-testid="intensity-card-unavailable">{t("workoutDetailExtended.intensityUnavailable")}</p>}
          {technicalLimitations.length > 0 && <a
            href="#workout-analysis-details"
            className="text-sm text-muted-foreground underline inline-flex items-center min-h-11"
            onClick={() => { document.getElementById("workout-analysis-details").open = true; }}
          >{t("workoutDetailExtended.viewLimitations")}</a>}
        </CardContent></Card>
      </section>}

      <section aria-labelledby="pacing-title">
      <h2 id="pacing-title" className="text-base font-semibold mb-2">{t(`workoutDetailExtended.${isCycle ? "speedSection" : "pacingSection"}`)}</h2>
      {hasPacing && (
        <Card className="bg-card border-border mb-3" data-testid="pacing-summary-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-4 h-4 text-primary" />
              <span className="text-sm font-semibold text-muted-foreground">{t(`workoutDetailExtended.${showPacingSpeed ? "speed" : "pace"}`)}</span>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              {!isCycle && hasAveragePace && (
                <div>
                  <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.average")}</p>
                  <p className="font-mono font-semibold">{formatPaceDisplay(pacing.average_pace_min_km)}</p>
                </div>
              )}
              {showPacingSpeed && hasPositiveFiniteMetric(pacing.average_speed_kmh) && <div>
                <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.speed")}</p>
                <p className="font-mono font-semibold">{formatSpeed(pacing.average_speed_kmh, { unitSystem: "metric" })}</p>
              </div>}
              {hasPositiveFiniteMetric(pacing.fastest_split_min_km) && (
                <div>
                  <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.fastest")}</p>
                  <p className="font-mono font-semibold">{formatPaceDisplay(pacing.fastest_split_min_km)}</p>
                </div>
              )}
              {hasPositiveFiniteMetric(pacing.slowest_split_min_km) && (
                <div>
                  <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.slowest")}</p>
                  <p className="font-mono font-semibold">{formatPaceDisplay(pacing.slowest_split_min_km)}</p>
                </div>
              )}
              {Number.isFinite(pacing.pace_drop_min_km) && (
                <div>
                  <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.paceDrop")}</p>
                  <p className="font-mono font-semibold">{formatPaceDelta(pacing.pace_drop_min_km)}</p>
                </div>
              )}
              {Number.isFinite(pacing.consistency_score) && <div>
                <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.consistency")}</p>
                <p className="font-mono font-semibold">{pacing.consistency_score}/100</p>
              </div>}
              {Number.isFinite(pacing.variability) && <div>
                <p className="text-sm text-muted-foreground">{t("workoutDetailExtended.recordedVariability")}</p>
                <p className="font-mono font-semibold">{pacing.variability}</p>
              </div>}
            </div>
          </CardContent>
        </Card>
      )}
      {!hasPacing && !analysisLoading && !analysisError && <p className="text-sm text-muted-foreground">{(!hasLimitation("splits") && pacing?.reason_unavailable) || t("workoutDetailExtended.pacingUnavailable")}</p>}
      {hasSplits && <div className="mt-3" data-testid="splits-chart-card">
        <h3 className="text-sm font-semibold mb-2">{t("workoutDetailExtended.recordedSplits")}</h3>
        <SplitsChart splits={workout.km_splits} t={t} />
      </div>}
      {Array.isArray(workout.km_splits) && workout.km_splits.some((split) => !Number.isFinite(split?.pace_min_km) || split.pace_min_km <= 0) && <p className="text-sm text-muted-foreground mt-2">{t("workoutDetailExtended.invalidSplits")}</p>}
      {!hasSplits && <p className="text-sm text-muted-foreground mt-2">{t("workoutDetailExtended.splitsUnavailable")}</p>}
      </section>

      <section aria-labelledby="heart-response-title" data-testid="heart-response">
        <h2 id="heart-response-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.heartResponse")}</h2>
        {hasHr || hasZones ? <Card className="bg-card border-border"><CardContent className="p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 text-sm">
            {Number.isFinite(avgHr) && avgHr > 0 && <p>{t("workoutDetailExtended.averageHeartRate")}<br /><strong>{formatHeartRate(avgHr)}</strong></p>}
            {Number.isFinite(maxHr) && maxHr > 0 && <p>{t("workoutDetailExtended.maximumHeartRate")}<br /><strong>{formatHeartRate(maxHr)}</strong></p>}
          </div>
          {hasZones && <div data-testid="hr-zones-card">
            <h3 className="text-sm font-semibold">{t("analysis.hrZones")}</h3>
            <p className="text-sm text-muted-foreground my-2">{t("workoutDetailExtended.zonesProvenance")}</p>
            <HRZonesChart zones={physiology.zone_distribution} t={t} />
          </div>}
        </CardContent></Card> : <p className="text-sm text-muted-foreground">{(!hasLimitation("heart_rate") && physiology?.reason_unavailable) || t("workoutDetailExtended.heartRateUnavailable")}</p>}
      </section>

      {hasAnalysis && <section aria-labelledby="history-title" data-testid="history-section">
      <h2 id="history-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.historyComparison")}</h2>
      <p className="text-sm text-muted-foreground mb-3">{t("workoutDetailExtended.descriptiveComparison")}</p>
      {comparison?.available && (
        <Card className="bg-card border-border mb-3" data-testid="comparison-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <Scale className="w-4 h-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold">{interpolate("recentComparison", { days: comparison.baseline_period_days })}</h3>
            </div>
            {comparison.baseline_sample_count != null && <p className="font-sans text-sm text-muted-foreground mb-2">{formatSampleCount(comparison.baseline_sample_count)}</p>}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Number.isFinite(comparison.distance_km?.difference) && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[11px] uppercase text-muted-foreground">{t("workoutDetailExtended.distance")}</p>
                  <p className="font-mono text-xs">{formatSignedDistance(comparison.distance_km)}</p>
                </div>
              )}
              {Number.isFinite(comparison.duration_minutes?.difference) && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[11px] uppercase text-muted-foreground">{t("workoutDetailExtended.duration")}</p>
                  <p className="font-mono text-xs">{formatSignedMetric(comparison.duration_minutes, " min", true)}</p>
                </div>
              )}
              {Number.isFinite(comparison.avg_heart_rate?.difference) && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[11px] uppercase text-muted-foreground">{t("workoutDetailExtended.heartRate")}</p>
                  <p className="font-mono text-xs">{formatSignedMetric(comparison.avg_heart_rate, " bpm", true)}</p>
                </div>
              )}
              {(Number.isFinite(comparison.avg_pace_min_km?.difference) || Number.isFinite(comparison.avg_speed_kmh?.difference)) && (
                <div className="rounded-sm bg-muted/20 p-2">
                  <p className="font-mono text-[11px] uppercase text-muted-foreground">{t(Number.isFinite(comparison.avg_pace_min_km?.difference) ? "workoutDetailExtended.pace" : "workoutDetailExtended.speed")}</p>
                  <p className="font-mono text-xs">
                    {Number.isFinite(comparison.avg_pace_min_km?.difference)
                      ? formatPaceDelta(comparison.avg_pace_min_km.difference)
                      : formatSignedMetric(comparison.avg_speed_kmh, " km/h")}
                  </p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {!comparison?.available && <p className="text-sm text-muted-foreground mb-3">{(!hasLimitation("baseline") && comparison?.reason_unavailable) || t("workoutDetailExtended.historyUnavailable")}</p>}
      {similar && (
        <Card className="bg-card border-border mb-3" data-testid="similar-comparison-card">
          <CardContent className="p-3 space-y-2 font-sans text-sm leading-relaxed">
            <h3 className="text-sm font-semibold">{interpolate("similarComparison", { days: similar.period_days })}</h3>
            {similar.available ? (
              <>
                {similar.sample_count != null && <p>{formatSampleCount(similar.sample_count)}</p>}
                {Number.isFinite(similar.avg_distance_km) && <p>{t("workoutDetailExtended.averageDistance")}: {formatDistance(similar.avg_distance_km)}</p>}
                {(hasPositiveFiniteMetric(similar.avg_pace_min_km) || Number.isFinite(similar.pace_difference_min_km)) && (
                  <div data-testid="similar-pace">
                    {hasPositiveFiniteMetric(similar.avg_pace_min_km) && <p>{t("workoutDetailExtended.averagePace")}: {formatPaceDisplay(similar.avg_pace_min_km)}</p>}
                    {Number.isFinite(similar.pace_difference_min_km) && <p>{t("workoutDetailExtended.difference")}: {formatPaceDelta(similar.pace_difference_min_km)}</p>}
                    {similar.pace_sample_count != null && similar.sample_count != null && <p className="text-muted-foreground">{interpolate("paceSampleCount", { count: similar.pace_sample_count, total: similar.sample_count })}</p>}
                  </div>
                )}
                {(similar.avg_heart_rate != null || similar.heart_rate_difference_bpm != null) && (
                  <div data-testid="similar-heart-rate">
                    {Number.isFinite(similar.avg_heart_rate) && <p>{t("workoutDetailExtended.averageHeartRate")}: {formatHeartRate(similar.avg_heart_rate)}</p>}
                    {Number.isFinite(similar.heart_rate_difference_bpm) && <p>{t("workoutDetailExtended.difference")}: {formatSignedMetric({ difference: similar.heart_rate_difference_bpm }, " bpm", true)}</p>}
                    {similar.hr_sample_count != null && similar.sample_count != null && <p className="text-muted-foreground">{interpolate("hrSampleCount", { count: similar.hr_sample_count, total: similar.sample_count })}</p>}
                  </div>
                )}
                <p className="text-muted-foreground" data-testid="similar-comparability-caveat">{t(`workoutDetailExtended.${similar.comparable === true ? "comparableReference" : "limitedComparability"}`)}</p>
              </>
            ) : (
              <p className="text-muted-foreground">{(!(Array.isArray(analysis.limitations) && analysis.limitations.some((item) => item?.code === "limitations.no_comparable_reference")) && similar.reason_unavailable) || t("workoutDetailExtended.similarUnavailable")}</p>
            )}
          </CardContent>
        </Card>
      )}
      </section>}

      <section aria-labelledby="coach-advice-title">
        <h2 id="coach-advice-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.coachObservation")}</h2>
        {hasAnalysis && <p className={`text-sm leading-relaxed mb-3${observationAvailable ? "" : " text-muted-foreground"}`} data-testid={observationAvailable ? "advice-text" : "advice-unavailable"}>
          {observationAvailable ? analysis.advice.text : t("workoutDetailExtended.adviceUnavailable")}
        </p>}
        <Button
          onClick={goToAskCoach}
          data-testid="ask-coach-btn"
          className="w-full bg-primary text-primary-foreground hover:bg-primary/90 min-h-11 h-auto py-3 whitespace-normal text-sm flex items-center justify-center gap-2"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          {t("workoutDetailExtended.askCoach")}
        </Button>
      </section>

      {hasAnalysis && (
        <details id="workout-analysis-details" className="bg-card border border-border p-3 mb-3" data-testid="analysis-details">
          <summary className="cursor-pointer text-sm min-h-11 content-center" data-testid="advanced-toggle">{t("workoutDetailExtended.advancedDetails")}</summary>
          <div className="mt-3 space-y-3">
            {analysis.version != null && <p className="text-sm">{t("workoutDetailExtended.version")}: {analysis.version}</p>}
            {hasAnalysis && evidence && (
              <section className="font-sans text-sm leading-relaxed text-secondary-foreground space-y-1" data-testid="evidence-card">
                <h3 className="text-sm font-semibold">{t("workoutDetailExtended.evidence")}</h3>
                {[
                  ["has_heart_rate", "heartRate"],
                  ["has_hr_zones", "hrZonesEvidence"],
                  ["has_splits", "splitsEvidence"],
                  ["has_baseline", "baselineEvidence"],
                  ["has_cadence", "cadenceEvidence"],
                  ["has_elevation", "elevationEvidence"],
                ].map(([key, label]) => (
                  evidence[key] == null ? null : <p key={key}>{t(`workoutDetailExtended.${label}`)}: {t(`workoutDetailExtended.${evidence[key] ? "yes" : "no"}`)}</p>
                ))}
              </section>
            )}
            {technicalLimitations.length > 0 && <section className="font-sans text-sm leading-relaxed text-secondary-foreground space-y-1" data-testid="analysis-limitations">
              <h3 className="text-sm font-semibold">{t("workoutDetailExtended.limitations")}</h3>
              {technicalLimitations.map((item) => <p key={item.code}>{item.text}</p>)}
            </section>}
          </div>
        </details>
      )}
    </div>
  );
}

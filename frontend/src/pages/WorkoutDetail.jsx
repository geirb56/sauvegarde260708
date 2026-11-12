import { useState, useEffect } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import WorkoutAnalysisAccessNotice from "@/components/WorkoutAnalysisAccessNotice";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { formatPaceDisplay, getSessionClassification, getAnalysisObservations, getAnalysisFallback, getSessionSynthesis, getRenderableAnalysisPhases } from "@/lib/workoutAnalysis";
import { formatSpeed } from "@/utils/units";
import WorkoutPhaseAnalysis from "@/components/workout/WorkoutPhaseAnalysis";
import WorkoutKilometerSplits from "@/components/workout/WorkoutKilometerSplits";
import WorkoutFacts, { DetailsDisclosure, getWorkoutNarrative, getWorkoutFacts } from "@/components/workout/WorkoutFacts";
import useWorkoutIntelligence from "@/hooks/useWorkoutIntelligence";
import WorkoutCoachPending from "@/components/workout/WorkoutCoachPending";
import { formatAnalysisNumber } from "@/lib/analysisFormat";
import {
  ArrowLeft,
  MessageSquare,
  Loader2,
  Bike,
  Footprints,
  AlertCircle,
  Route,
  Timer,
  Gauge,
  Heart,
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

export const formatDistance = (value, lang = "en") => {
  if (!Number.isFinite(value)) return "--";
  return `${formatAnalysisNumber(value, lang, 2)} km`;
};

export const formatSignedDistance = (metric, lang = "en") => {
  const distance = formatDistance(metric?.difference, lang);
  if (distance === "--" || distance === "0 km") return distance;
  return `${metric.difference > 0 ? "+" : ""}${distance}`;
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
  const { unitSystem } = useUnitSystem();
  const { loading: subscriptionLoading, hasFeature } = useSubscription();
  const canAccessAnalysis = !subscriptionLoading && hasFeature("coach_workout_analysis") === true;
  const { data: intelligence, error: intelligenceError, loading: intelligenceLoading, scope } = useWorkoutIntelligence(id, lang, canAccessAnalysis);
  const hasFacts = canAccessAnalysis && Boolean(getWorkoutFacts(intelligence) || getWorkoutNarrative(intelligence, lang));
  const [workout, setWorkout] = useState(null);
  const [workoutScope, setWorkoutScope] = useState(null);
  const [workoutLoading, setWorkoutLoading] = useState(true);
  const [workoutError, setWorkoutError] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisScope, setAnalysisScope] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(true);
  const [analysisError, setAnalysisError] = useState(false);

  useEffect(() => {
    setWorkout(null);
    setWorkoutScope(id);
    setWorkoutLoading(true);
    setWorkoutError(null);

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

    return () => controller.abort();
  }, [id]);

  useEffect(() => {
    setAnalysisScope(scope);
    setAnalysis(null);
    setAnalysisError(false);
    setAnalysisLoading(canAccessAnalysis);
    if (!canAccessAnalysis) return undefined;

    const controller = new AbortController();
    const { signal } = controller;
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
  }, [id, lang, canAccessAnalysis, scope]);

  const goToAskCoach = () => navigate(id ? `/coach?analyze=${encodeURIComponent(id)}` : "/coach");
  const backTo = ALLOWED_BACK_ROUTES.has(location.state?.from) ? location.state.from : "/sessions";

  if (workoutLoading || workoutScope !== id) {
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
  const analysisForRender = canAccessAnalysis && analysisScope === scope
    && !analysisLoading && !analysisError ? analysis : null;
  const physiology = analysisForRender?.physiology;
  const pacing = analysisForRender?.pacing;
  const isCycle = workout.type === "cycle";
  const averageSpeed = hasPositiveFiniteMetric(workout.avg_speed_kmh) ? workout.avg_speed_kmh
    : pacing?.available === true && hasPositiveFiniteMetric(pacing.average_speed_kmh) ? pacing.average_speed_kmh : null;
  const hasWorkoutPace = hasPositiveFiniteMetric(workout.avg_pace_min_km);
  const hasAnalysis = Boolean(analysisForRender);
  const avgHr = Number.isFinite(workout.avg_heart_rate) && workout.avg_heart_rate > 0 ? workout.avg_heart_rate : physiology?.avg_hr;
  const synthesis = getSessionSynthesis(analysisForRender);
  const synthesisItems = synthesis
    ? [synthesis.primary, ...synthesis.supporting].filter((item) =>
      item && item.kind !== "interpretation"
      && !["synthesis.recorded_totals", "recorded_totals"].includes(item.code.trim()))
    : [];
  const [synthesisPrimary, ...synthesisSupport] = synthesisItems;
  const synthesisLimitations = synthesis?.limitations || [];
  const hasAvailableSynthesis = synthesis?.status === "available" && synthesisItems.length > 0;
  // Validated V2 content is folded into the factual markers/details of WorkoutFacts (no separate card).
  const synthesisForFacts = { items: hasAvailableSynthesis ? synthesisItems : [], limitations: synthesisLimitations };
  const factsRendered = !intelligenceLoading && (hasFacts
    || synthesisForFacts.items.length > 0 || synthesisForFacts.limitations.length > 0);
  const observations = synthesis ? [] : getAnalysisObservations(analysisForRender, { keepReplaced: true });
  const fallback = synthesis ? null : getAnalysisFallback(analysisForRender, t);
  const classification = hasFacts ? null : getSessionClassification(analysisForRender, t);
  const intensity = analysisForRender?.signals?.intensity;
  const detailsAvailable = (analysisForRender?.phase_analysis?.available === true
    && getRenderableAnalysisPhases(analysisForRender.phase_analysis).length > 0)
    || (Array.isArray(workout.km_splits) && workout.km_splits.some((split) =>
      Number.isFinite(split?.km) && split.km > 0
      && Number.isFinite(split?.pace_min_km) && split.pace_min_km > 0));
  const analysisDetails = <>
    <WorkoutPhaseAnalysis phaseAnalysis={analysisForRender?.phase_analysis} t={t} lang={lang} />
    <WorkoutKilometerSplits splits={workout.km_splits} workoutType={workout.type} unitSystem={unitSystem} t={t} lang={lang} />
  </>;

  const coachButton = canAccessAnalysis ? (
    <Button
      onClick={goToAskCoach}
      data-testid="ask-coach-btn"
      className="w-full rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 min-h-12 h-auto py-3 whitespace-normal text-base font-semibold flex items-center justify-center gap-2 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      <MessageSquare className="w-4 h-4" aria-hidden="true" />
      {t("workoutDetailExtended.askCoach")}
    </Button>
  ) : null;

  return (
    <div className="p-4 pb-24 max-w-3xl mx-auto min-w-0 break-words space-y-5" data-testid="workout-detail">
      <header className="flex items-center gap-3">
        <Link to={backTo} aria-label={t("workout.back")}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-border/60 bg-card text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
          <ArrowLeft className="w-5 h-5" aria-hidden="true" />
        </Link>
        <h1 id="session-summary-title" className="min-w-0 flex-1 font-heading text-xl font-bold leading-tight">{t("workoutDetailExtended.sessionSummary")}</h1>
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary" data-testid="sport-icon">
          <Icon className="w-5 h-5" aria-hidden="true" />
        </span>
      </header>

      <section aria-labelledby="session-summary-title" data-testid={hasAnalysis ? "coach-summary" : "session-summary"}>
        <Card className="bg-card border-border/60 rounded-2xl">
        <CardContent className="p-4 space-y-4">
          <div className="min-w-0">
            <h2 className="font-heading text-lg font-bold leading-tight">{workout.name || typeLabel}</h2>
            <p className="text-sm text-muted-foreground mt-1">{dateStr} · {typeLabel}</p>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-5" data-testid="primary-metrics">
            {[
              Number.isFinite(workout.distance_km) && workout.distance_km > 0
                ? ["distance", formatDistance(workout.distance_km, lang), Route] : null,
              Number.isFinite(workout.duration_minutes) && workout.duration_minutes > 0
                ? ["duration", formatDuration(workout.duration_minutes), Timer] : null,
              isCycle
                ? (averageSpeed == null ? null : ["averageSpeed", formatSpeed(averageSpeed, { unitSystem: "metric", lang }), Gauge])
                : (hasWorkoutPace
                  ? ["averagePace", formatPaceDisplay(workout.avg_pace_min_km), Gauge]
                  : averageSpeed == null ? null : ["averageSpeed", formatSpeed(averageSpeed, { unitSystem: "metric", lang }), Gauge]),
              Number.isFinite(avgHr) && avgHr > 0 ? ["averageHeartRate", formatHeartRate(avgHr), Heart] : null,
            ].filter(Boolean).map(([label, value, MetricIcon]) => <div key={label} className="min-w-0">
              <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <MetricIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="min-w-0">{t(`workoutDetailExtended.${label}`)}</span>
              </dt>
              <dd className="mt-1 text-2xl font-bold leading-none tabular-nums">{value}</dd>
            </div>)}
          </dl>
          {canAccessAnalysis && !hasFacts && analysisLoading ? (
            <AnalysisSkeleton />
          ) : canAccessAnalysis && !hasFacts && analysisError ? (
            <AnalysisError t={t} />
          ) : !canAccessAnalysis && !subscriptionLoading ? (
            <WorkoutAnalysisAccessNotice t={t} />
          ) : null}
        </CardContent>
      </Card>
      </section>

      {canAccessAnalysis && intelligenceError && <p role="status" className="text-sm text-muted-foreground">{t("workoutNarrative.unavailable")}</p>}
      {intelligenceLoading && <WorkoutCoachPending t={t} />}
      {intelligenceLoading && detailsAvailable && <DetailsDisclosure>{analysisDetails}</DetailsDisclosure>}
      {canAccessAnalysis && !factsRendered && coachButton}
      {!intelligenceLoading && <WorkoutFacts data={canAccessAnalysis ? intelligence : null} lang={lang} t={t} detailsAvailable={detailsAvailable}
        synthesis={synthesisForFacts} action={coachButton}>
        {analysisDetails}
      </WorkoutFacts>}
      {!intelligenceLoading && <>
      {synthesis && !hasAvailableSynthesis && <p className="text-sm leading-relaxed text-muted-foreground" data-testid="synthesis-abstention">
        {synthesis.status === "available" ? t("workoutDetailExtended.noReliableObservations") : synthesis.abstention}
      </p>}
      {!factsRendered && detailsAvailable && <DetailsDisclosure>{analysisDetails}</DetailsDisclosure>}

      {(observations.length > 0 || fallback || classification || (intensity?.available === true && intensity.text)) && <section aria-labelledby="takeaways-title">
        <h2 id="takeaways-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.takeaways")}</h2>
        <Card className="bg-card border-border"><CardContent className="p-4 space-y-2">
          {observations.length > 0 && <div className="space-y-2 text-sm leading-relaxed" data-testid="meaning-text">
            {observations.map((text) => <p key={text}>{text}</p>)}
          </div>}
          {fallback && <p className="text-sm leading-relaxed text-muted-foreground" data-testid="analysis-fallback">{fallback}</p>}
          {classification && <p className="text-sm text-muted-foreground" data-testid="session-classification">{classification.label}: {classification.text}</p>}
          {intensity?.available === true && intensity.text && (
            <p className="text-sm" data-testid="available-intensity">{t("analysis.intensity")}: {intensity.text}</p>
          )}
        </CardContent></Card>
      </section>}
      </>}

    </div>
  );
}

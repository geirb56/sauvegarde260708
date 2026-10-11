import { useState, useEffect } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import WorkoutAnalysisAccessNotice from "@/components/WorkoutAnalysisAccessNotice";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { getDistinctCoachObservation, getSessionClassification, getAnalysisTakeaway } from "@/lib/workoutAnalysis";
import { formatSpeed } from "@/utils/units";
import WorkoutPhaseAnalysis from "@/components/workout/WorkoutPhaseAnalysis";
import {
  ArrowLeft,
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
  const { loading: subscriptionLoading, hasFeature } = useSubscription();
  const canAccessAnalysis = !subscriptionLoading && hasFeature("coach_workout_analysis") === true;
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
  }, [id, lang, canAccessAnalysis]);

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
  const analysisForRender = canAccessAnalysis && !analysisLoading && !analysisError ? analysis : null;
  const physiology = analysisForRender?.physiology;
  const pacing = analysisForRender?.pacing;
  const isCycle = workout.type === "cycle";
  const averageSpeed = hasPositiveFiniteMetric(workout.avg_speed_kmh) ? workout.avg_speed_kmh
    : pacing?.available === true && hasPositiveFiniteMetric(pacing.average_speed_kmh) ? pacing.average_speed_kmh : null;
  const hasWorkoutPace = hasPositiveFiniteMetric(workout.avg_pace_min_km);
  const hasAnalysis = Boolean(analysisForRender);
  const avgHr = Number.isFinite(workout.avg_heart_rate) && workout.avg_heart_rate > 0 ? workout.avg_heart_rate : physiology?.avg_hr;
  const coachObservation = getDistinctCoachObservation(analysisForRender);
  const takeaway = getAnalysisTakeaway(analysisForRender);
  const classification = getSessionClassification(analysisForRender, t);

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
              Number.isFinite(workout.distance_km) && workout.distance_km > 0
                ? ["distance", formatDistance(workout.distance_km)] : null,
              Number.isFinite(workout.duration_minutes) && workout.duration_minutes > 0
                ? ["duration", formatDuration(workout.duration_minutes)] : null,
              isCycle
                ? (averageSpeed == null ? null : ["averageSpeed", formatSpeed(averageSpeed, { unitSystem: "metric" })])
                : (hasWorkoutPace ? ["averagePace", formatPaceDisplay(workout.avg_pace_min_km)] : null),
              Number.isFinite(avgHr) && avgHr > 0 ? ["averageHeartRate", formatHeartRate(avgHr)] : null,
            ].filter(Boolean).map(([label, value]) => <div key={label} className="min-w-0">
              <dt className="text-sm text-muted-foreground">{t(`workoutDetailExtended.${label}`)}</dt>
              <dd className="text-base font-semibold">{value}</dd>
            </div>)}
          </dl>
          {canAccessAnalysis && analysisLoading ? (
            <AnalysisSkeleton />
          ) : canAccessAnalysis && analysisError ? (
            <AnalysisError t={t} />
          ) : !subscriptionLoading ? (
            <WorkoutAnalysisAccessNotice t={t} />
          ) : null}
        </CardContent>
      </Card>
      </section>

      <WorkoutPhaseAnalysis phaseAnalysis={analysisForRender?.phase_analysis} t={t} lang={lang} />

      {takeaway && <section aria-labelledby="takeaways-title">
        <h2 id="takeaways-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.takeaways")}</h2>
        <Card className="bg-card border-border"><CardContent className="p-4 space-y-2">
          <p className="text-sm leading-relaxed" data-testid="meaning-text">{takeaway}</p>
          {classification && <p className="text-sm text-muted-foreground" data-testid="session-classification">{classification.label}: {classification.text}</p>}
          {analysisForRender.signals?.intensity?.available === true && analysisForRender.signals.intensity.text && (
            <p className="text-sm" data-testid="available-intensity">{t("analysis.intensity")}: {analysisForRender.signals.intensity.text}</p>
          )}
        </CardContent></Card>
      </section>}

      {canAccessAnalysis && <section aria-labelledby="coach-advice-title">
        {coachObservation && <div className="mb-3">
          <h2 id="coach-advice-title" className="text-base font-semibold mb-2">{t("workoutDetailExtended.coachObservation")}</h2>
          <p className="text-sm leading-relaxed" data-testid="advice-text">{coachObservation}</p>
        </div>}
        <Button
          onClick={goToAskCoach}
          data-testid="ask-coach-btn"
          className="w-full bg-primary text-primary-foreground hover:bg-primary/90 min-h-11 h-auto py-3 whitespace-normal text-sm flex items-center justify-center gap-2"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          {t("workoutDetailExtended.askCoach")}
        </Button>
      </section>}
    </div>
  );
}

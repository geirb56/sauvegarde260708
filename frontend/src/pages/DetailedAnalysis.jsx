import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import axios from "axios";
import { ArrowLeft, Loader2, MessageSquare } from "lucide-react";

import { API_BASE_URL } from "@/config";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { Button } from "@/components/ui/button";
import WorkoutAnalysisAccessNotice from "@/components/WorkoutAnalysisAccessNotice";
import WorkoutPhaseAnalysis from "@/components/workout/WorkoutPhaseAnalysis";
import WorkoutKilometerSplits from "@/components/workout/WorkoutKilometerSplits";
import NarrativeWorkoutAnalysis, { getWorkoutNarrative } from "@/components/workout/NarrativeWorkoutAnalysis";
import useWorkoutIntelligence from "@/hooks/useWorkoutIntelligence";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance, formatSpeed } from "@/utils/units";
import { formatDuration } from "@/utils/workoutHelpers";
import { formatPaceDisplay, getCoachConclusions, getDistinctCoachObservation, getSessionClassification, getAnalysisObservations, getAnalysisFallback, getRenderableAnalysisPhases } from "@/lib/workoutAnalysis";

const API = API_BASE_URL;
const isCycling = (type) => ["cycle", "cycling", "ride"].includes(type);

export default function DetailedAnalysis() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const { loading: subscriptionLoading, hasFeature } = useSubscription();
  const canAccessAnalysis = !subscriptionLoading && hasFeature("coach_workout_analysis") === true;
  const { data: intelligence, error: intelligenceError, loading: intelligenceLoading } = useWorkoutIntelligence(id, lang, canAccessAnalysis);
  const narrative = canAccessAnalysis && getWorkoutNarrative(intelligence, lang);
  const [loadedAnalysis, setAnalysis] = useState(null);
  const [loadedWorkout, setWorkout] = useState(null);
  const [loading, setLoading] = useState(true);
  const [requestScope, setRequestScope] = useState(null);
  const scope = `${id}:${lang}`;
  const isCurrentRequest = requestScope === scope;
  const analysis = canAccessAnalysis && isCurrentRequest ? loadedAnalysis : null;
  const workout = canAccessAnalysis && isCurrentRequest ? loadedWorkout : null;

  useEffect(() => {
    setRequestScope(`${id}:${lang}`);
    setAnalysis(null);
    setWorkout(null);
    if (!canAccessAnalysis) {
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    const workoutRequest = axios.get(`${API}/workouts/${id}`, { signal })
      .then((res) => {
        if (!signal.aborted) setWorkout(res.data);
      })
      .catch(() => {
        if (!signal.aborted) setWorkout(null);
      });
    const analysisRequest = axios.get(`${API}/coach/workout-analysis/${id}?language=${lang}`, { signal })
      .then((res) => {
        if (!signal.aborted) setAnalysis(res.data);
      })
      .catch(() => {
        if (!signal.aborted) setAnalysis(null);
      });
    Promise.all([workoutRequest, analysisRequest]).finally(() => {
      if (!signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [id, lang, canAccessAnalysis]);

  if (subscriptionLoading || (canAccessAnalysis && !narrative
    && (!isCurrentRequest || loading || (!analysis && !workout && intelligenceLoading)))) {
    return (
      <div className="p-4 pb-24 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">{t("detailedAnalysis.loading")}</span>
        </div>
      </div>
    );
  }

  if (!canAccessAnalysis) {
    return (
      <div className="p-4 pb-24" data-testid="analysis-access-denied">
        <Link to={`/workout/${id}`} className="inline-flex items-center gap-2 text-muted-foreground mb-6">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-xs uppercase">{t("workout.back")}</span>
        </Link>
        <WorkoutAnalysisAccessNotice t={t} />
      </div>
    );
  }

  if (!analysis && !narrative && !workout) {
    return (
      <div className="p-4 pb-24" data-testid="analysis-not-found">
        <Link to="/" className="inline-flex items-center gap-2 text-muted-foreground mb-6">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-xs uppercase">{t("workout.back")}</span>
        </Link>
        <p className="text-muted-foreground">{t("workout.notFound")}</p>
        {intelligenceError && <p role="status" className="text-sm text-muted-foreground">{t("workoutNarrative.unavailable")}</p>}
      </div>
    );
  }

  const cycling = isCycling(analysis?.workout?.type || workout?.type);
  const pace = analysis?.pacing?.average_pace_min_km ?? workout?.avg_pace_min_km;
  const speed = analysis?.pacing?.average_speed_kmh ?? workout?.avg_speed_kmh;
  const distance = analysis?.comparison?.distance_km?.current ?? workout?.distance_km;
  const duration = analysis?.comparison?.duration_minutes?.current ?? workout?.duration_minutes;
  const heartRate = analysis?.physiology?.avg_hr ?? workout?.avg_heart_rate;
  const metrics = [
    Number.isFinite(distance) && distance > 0
      ? [t("workoutDetailExtended.distance"), formatDistance(distance, { unitSystem: "metric", lang })] : null,
    Number.isFinite(duration) && duration > 0
      ? [t("workoutDetailExtended.duration"), formatDuration(duration)] : null,
    cycling
      ? (Number.isFinite(speed) && speed > 0 ? [t("workoutDetailExtended.averageSpeed"), formatSpeed(speed, { unitSystem: "metric", lang })] : null)
      : (Number.isFinite(pace) && pace > 0
        ? [t("workoutDetailExtended.averagePace"), formatPaceDisplay(pace)]
        : Number.isFinite(speed) && speed > 0 ? [t("workoutDetailExtended.averageSpeed"), formatSpeed(speed, { unitSystem: "metric", lang })] : null),
    Number.isFinite(heartRate) && heartRate > 0
      ? [t("workoutDetailExtended.averageHeartRate"), `${heartRate} bpm`] : null,
  ].filter(Boolean);
  const classification = getSessionClassification(analysis, t);
  const coachConclusions = getCoachConclusions(analysis);
  const observation = getDistinctCoachObservation(analysis);
  const observations = getAnalysisObservations(analysis);
  const fallback = getAnalysisFallback(analysis, t);
  const date = new Date(analysis?.workout?.date || workout?.date);
  const dateStr = Number.isFinite(date.getTime()) ? date.toLocaleDateString(
    { fr: "fr-FR", es: "es-ES", en: "en-US" }[lang] || "en-US",
    { weekday: "short", month: "short", day: "numeric" },
  ) : "";
  const detailsAvailable = (analysis?.phase_analysis?.available === true
    && getRenderableAnalysisPhases(analysis.phase_analysis).length > 0)
    || (Array.isArray(workout?.km_splits) && workout.km_splits.some((split) =>
      Number.isFinite(split?.km) && split.km > 0
      && Number.isFinite(split?.pace_min_km) && split.pace_min_km > 0));
  const analysisDetails = <>
    <WorkoutPhaseAnalysis phaseAnalysis={analysis?.phase_analysis} t={t} lang={lang} />
    <WorkoutKilometerSplits splits={workout?.km_splits} workoutType={analysis?.workout?.type || workout?.type} unitSystem={unitSystem} t={t} lang={lang} />
  </>;

  return (
    <div className="min-w-0 break-words p-4 pb-24" data-testid="detailed-analysis">
      <div className="flex items-center justify-between mb-3">
        <Link to={`/workout/${id}`} className="text-muted-foreground hover:text-foreground" aria-label={t("workout.back")}>
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <span className="font-mono text-[11px] uppercase text-muted-foreground">{t("detailedAnalysis.title")}</span>
        <span className="font-mono text-[11px] text-muted-foreground">{dateStr}</span>
      </div>

      <section className="mb-3 rounded-xl border border-border bg-card p-3" aria-labelledby="workout-summary-title">
        <h1 id="workout-summary-title" className="mb-2 font-heading text-base font-bold leading-tight">{analysis?.workout?.name || workout?.name}</h1>
        {metrics.length > 0 && <dl className="grid grid-cols-2 gap-3" data-testid="primary-metrics">
          {metrics.map(([label, value]) => <div key={label}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-sm font-semibold">{value}</dd>
          </div>)}
        </dl>}
        {!narrative && metrics.length === 0 && analysis?.coach_language?.version !== "v1" && analysis?.summary?.text && <p className="mt-3 font-sans text-sm leading-relaxed" data-testid="header-context">{analysis.summary.text}</p>}
      </section>

      {intelligenceError && <p role="status" className="text-sm text-muted-foreground">{t("workoutNarrative.unavailable")}</p>}
      {narrative ? <NarrativeWorkoutAnalysis data={intelligence} analysis={analysis} lang={lang} t={t} detailsAvailable={detailsAvailable}>
        {analysisDetails}
      </NarrativeWorkoutAnalysis> : <>
      {!analysis && <p className="text-muted-foreground" data-testid="analysis-not-found">{t("workout.notFound")}</p>}
      {coachConclusions.length > 0 && <section className="my-3 space-y-2 rounded-xl border border-border bg-card p-4" data-testid="coach-language">
        <h2 className="text-base font-semibold">{t("workoutDetailExtended.coachObservation")}</h2>
        {coachConclusions.map((item, index) => <p key={item.code} className="text-sm leading-relaxed" data-testid={index === 0 ? "coach-primary" : "coach-complementary"}>{item.text}</p>)}
      </section>}
      {analysisDetails}

      {(observations.length > 0 || fallback || classification || (analysis?.signals?.intensity?.available === true && analysis.signals.intensity.text)) && <section className="my-3 rounded-xl border border-border bg-card p-3">
        <h2 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">{t("detailedAnalysis.meaning")}</h2>
        {observations.length > 0 && <div className="space-y-2 font-sans text-sm leading-relaxed" data-testid="meaning-text">
          {observations.map((text) => <p key={text}>{text}</p>)}
        </div>}
        {fallback && <p className="text-sm leading-relaxed text-muted-foreground" data-testid="analysis-fallback">{fallback}</p>}
        {classification && <p className="mt-2 text-sm text-muted-foreground" data-testid="session-classification">{classification.label}: {classification.text}</p>}
        {analysis?.signals?.intensity?.available === true && analysis.signals.intensity.text && (
          <p className="mt-2 text-sm">{t("analysis.intensity")}: {analysis.signals.intensity.text}</p>
        )}
      </section>}
      </>}

      {!narrative && observation && <section className="my-3 rounded-xl border border-border bg-card p-3">
        <h2 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-primary">{t("workoutDetailExtended.coachObservation")}</h2>
        <p className="font-sans text-sm leading-relaxed" data-testid="advice-text">{observation}</p>
      </section>}

      <Button
        onClick={() => navigate(id ? `/coach?analyze=${encodeURIComponent(id)}` : "/coach")}
        data-testid="ask-coach-btn"
        className="mt-4 w-full bg-muted text-foreground border border-border rounded-none h-11 font-mono text-xs uppercase tracking-wider flex items-center justify-center gap-2"
      >
        <MessageSquare className="w-3.5 h-3.5" />
        {t("detailedAnalysis.askCoach")}
      </Button>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import axios from "axios";
import {
  ArrowLeft,
  MessageSquare,
  Scale,
} from "lucide-react";

import { API_BASE_URL } from "@/config";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import WorkoutAnalysisAccessNotice from "@/components/WorkoutAnalysisAccessNotice";
import WorkoutPhaseAnalysis from "@/components/workout/WorkoutPhaseAnalysis";
import WorkoutKilometerSplits from "@/components/workout/WorkoutKilometerSplits";
import NarrativeWorkoutAnalysis, { getWorkoutNarrative } from "@/components/workout/NarrativeWorkoutAnalysis";
import useWorkoutIntelligence from "@/hooks/useWorkoutIntelligence";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDistance, formatPace, formatSpeed } from "@/utils/units";
import { formatDuration } from "@/utils/workoutHelpers";
import { getCoachConclusions, getDistinctCoachObservation, getSessionClassification, getAnalysisObservations, getAnalysisFallback, getRenderableAnalysisPhases } from "@/lib/workoutAnalysis";

const API = API_BASE_URL;

const localeByLang = {
  en: "en-US",
  fr: "fr-FR",
  es: "es-ES",
};

const formatLabel = (key) => key
  .replace(/_/g, " ")
  .replace(/\b\w/g, (char) => char.toUpperCase());

const formatWorkoutTypeLabel = (type, t) => {
  const translated = t(`workoutTypes.${type}`);
  return translated === `workoutTypes.${type}` ? formatLabel(type || "") : translated;
};

const DetailSkeleton = () => (
  <div className="space-y-4 p-4 pb-24">
    <Skeleton className="h-7 w-40" />
    <Skeleton className="h-24 w-full" />
    <Skeleton className="h-48 w-full" />
    <Skeleton className="h-56 w-full" />
  </div>
);

export default function SessionDetail() {
  const { id } = useParams();
  const { t, lang } = useLanguage();
  const { loading: subscriptionLoading, hasFeature } = useSubscription();
  const canAccessAnalysis = !subscriptionLoading && hasFeature("coach_workout_analysis") === true;
  const { data: intelligence, error: intelligenceError } = useWorkoutIntelligence(id, lang, canAccessAnalysis);
  const narrative = canAccessAnalysis && getWorkoutNarrative(intelligence, lang);
  const { unitSystem } = useUnitSystem();
  const [session, setSession] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisScope, setAnalysisScope] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadSession = async () => {
      setLoading(true);
      try {
        const sessionRes = await axios.get(`${API}/workouts/${id}`);
        setSession(sessionRes.data);
      } catch (error) {
        setSession(null);
      } finally {
        setLoading(false);
      }
    };

    loadSession();
  }, [id]);

  useEffect(() => {
    let active = true;
    setAnalysisScope(JSON.stringify([id, lang]));
    setAnalysis(null);
    if (!canAccessAnalysis) return () => { active = false; };

    axios.get(`${API}/coach/workout-analysis/${id}?language=${lang}`)
      .then((res) => {
        if (active) setAnalysis(res.data);
      })
      .catch(() => {
        if (active) setAnalysis(null);
      });

    return () => { active = false; };
  }, [id, lang, canAccessAnalysis]);

  const locale = localeByLang[lang] || "en-US";
  const primaryMetrics = useMemo(() => {
    if (!session) return [];
    const cycling = ["cycle", "cycling", "ride"].includes(session.type);
    const metrics = [
      Number.isFinite(session.distance_km) && session.distance_km > 0
        ? { label: t("sessions.columns.distance"), value: formatDistance(session.distance_km, { unitSystem, lang }) } : null,
      Number.isFinite(session.duration_minutes) && session.duration_minutes > 0
        ? { label: t("sessions.columns.duration"), value: formatDuration(session.duration_minutes) } : null,
      cycling
        ? (Number.isFinite(session.avg_speed_kmh) && session.avg_speed_kmh > 0
          ? { label: t("workout.avgSpeed"), value: formatSpeed(session.avg_speed_kmh, { unitSystem, lang }) } : null)
        : (Number.isFinite(session.avg_pace_min_km) && session.avg_pace_min_km > 0
          ? { label: t("sessions.columns.pace"), value: formatPace(session.avg_pace_min_km * 60, { unitSystem }) } : null),
      Number.isFinite(session.avg_heart_rate) && session.avg_heart_rate > 0
        ? { label: t("workout.avgHeartRate"), value: `${Math.round(session.avg_heart_rate)} bpm` } : null,
    ].filter(Boolean);
    return metrics;
  }, [session, t, unitSystem, lang]);

  if (loading) return <DetailSkeleton />;

  if (!session) {
    return (
      <div className="p-4 pb-24">
        <Link to="/sessions" className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <ArrowLeft className="h-4 w-4" />
          {t("sessions.back")}
        </Link>
        <p className="mt-6 text-muted-foreground">{t("workout.notFound")}</p>
      </div>
    );
  }

  const analysisForRender = canAccessAnalysis && analysisScope === JSON.stringify([id, lang]) ? analysis : null;
  const coachConclusions = getCoachConclusions(analysisForRender);
  const classification = getSessionClassification(analysisForRender, t);
  const observation = getDistinctCoachObservation(analysisForRender);
  const observations = getAnalysisObservations(analysisForRender);
  const fallback = getAnalysisFallback(analysisForRender, t);
  const detailsAvailable = (analysisForRender?.phase_analysis?.available === true
    && getRenderableAnalysisPhases(analysisForRender.phase_analysis).length > 0)
    || (Array.isArray(session.km_splits) && session.km_splits.some((split) =>
      Number.isFinite(split?.km) && split.km > 0
      && Number.isFinite(split?.pace_min_km) && split.pace_min_km > 0));
  const analysisDetails = <>
    <WorkoutPhaseAnalysis phaseAnalysis={analysisForRender?.phase_analysis} t={t} lang={lang} />
    <WorkoutKilometerSplits splits={session.km_splits} workoutType={session.type} unitSystem={unitSystem} t={t} lang={lang} />
  </>;

  return (
    <div className="max-w-3xl mx-auto min-w-0 break-words p-4 pb-24 space-y-4" data-testid="session-detail-page">
      <div className="space-y-3">
        <Link to="/sessions" className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <ArrowLeft className="h-4 w-4" />
          {t("sessions.back")}
        </Link>

        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{formatWorkoutTypeLabel(session.type, t)}</p>
            <h1 className="text-2xl font-semibold tracking-tight">{session.name}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {new Date(session.date).toLocaleString(locale, {
              year: "numeric",
              month: "long",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        </div>
      </div>

      {canAccessAnalysis && intelligenceError && <p role="status" className="text-sm text-muted-foreground">{t("workoutNarrative.unavailable")}</p>}
      {narrative && <NarrativeWorkoutAnalysis data={intelligence} analysis={analysisForRender} lang={lang} t={t} detailsAvailable={detailsAvailable}>
        {analysisDetails}
      </NarrativeWorkoutAnalysis>}

      <section className="space-y-3 rounded-2xl border border-border bg-card/30 p-4">
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {t("sessions.metrics")}
          </h2>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {primaryMetrics.map((metric) => (
            <div key={metric.label} className="rounded-xl border border-border/70 bg-background/60 p-3">
              <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{metric.label}</p>
              <p className="mt-2 text-sm font-medium">{metric.value}</p>
            </div>
          ))}
        </div>
      </section>

      {!narrative && <>
      {coachConclusions.length > 0 && <section className="space-y-2 rounded-xl border border-border bg-card p-4" data-testid="coach-language">
        <h2 className="text-base font-semibold">{t("workoutDetailExtended.coachObservation")}</h2>
        {coachConclusions.map((item, index) => <p key={item.code} className="text-sm leading-relaxed" data-testid={index === 0 ? "coach-primary" : "coach-complementary"}>{item.text}</p>)}
      </section>}
      {analysisDetails}
      </>}

      {canAccessAnalysis ? <>
        {!narrative && analysisForRender && (observations.length > 0 || fallback || classification || observation
          || (analysisForRender.signals?.intensity?.available === true && analysisForRender.signals.intensity.text)) && <section className="space-y-3 rounded-2xl border border-border bg-card/30 p-4" data-testid="session-analysis">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {t("workoutDetailExtended.meaning")}
          </h2>
        </div>
        {observations.length > 0 && <div className="space-y-2 text-sm leading-6" data-testid="meaning-text">
          {observations.map((text) => <p key={text}>{text}</p>)}
        </div>}
        {fallback && <p className="text-sm leading-6 text-muted-foreground" data-testid="analysis-fallback">{fallback}</p>}
        {classification && <p className="text-sm text-muted-foreground" data-testid="session-classification">{classification.label}: {classification.text}</p>}
        {analysisForRender.signals?.intensity?.available === true && analysisForRender.signals.intensity.text && (
          <p className="text-sm">{t("analysis.intensity")}: {analysisForRender.signals.intensity.text}</p>
        )}
        {observation && <div>
          <h3 className="text-sm font-medium">{t("workoutDetailExtended.coachObservation")}</h3>
          <p className="mt-1 text-sm leading-6" data-testid="advice-text">{observation}</p>
        </div>}
        </section>}
        {(analysisForRender || narrative) && <Link to={`/coach?analyze=${encodeURIComponent(id)}`} data-testid="ask-coach-btn" className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-none border border-border bg-muted px-4 py-3 text-sm font-mono uppercase tracking-wider text-foreground">
          <MessageSquare className="h-3.5 w-3.5" />
          {t("workoutDetailExtended.askCoach")}
        </Link>}
      </> : !subscriptionLoading && <WorkoutAnalysisAccessNotice t={t} />}
    </div>
  );
}

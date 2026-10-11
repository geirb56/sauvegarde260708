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
import { formatDistance, formatSpeed } from "@/utils/units";
import { formatDuration } from "@/utils/workoutHelpers";
import { formatPaceDisplay, getDistinctCoachObservation, getSessionClassification, getAnalysisTakeaway } from "@/lib/workoutAnalysis";

const API = API_BASE_URL;
const isCycling = (type) => ["cycle", "cycling", "ride"].includes(type);

export default function DetailedAnalysis() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t, lang } = useLanguage();
  const { loading: subscriptionLoading, hasFeature } = useSubscription();
  const canAccessAnalysis = !subscriptionLoading && hasFeature("coach_workout_analysis") === true;
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setAnalysis(null);
    if (!canAccessAnalysis) {
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    axios.get(`${API}/coach/workout-analysis/${id}?language=${lang}`, { signal: controller.signal })
      .then((res) => setAnalysis(res.data))
      .catch(() => setAnalysis(null))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [id, lang, canAccessAnalysis]);

  if (subscriptionLoading || (canAccessAnalysis && loading)) {
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

  if (!analysis) {
    return (
      <div className="p-4 pb-24" data-testid="analysis-not-found">
        <Link to="/" className="inline-flex items-center gap-2 text-muted-foreground mb-6">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-xs uppercase">{t("workout.back")}</span>
        </Link>
        <p className="text-muted-foreground">{t("workout.notFound")}</p>
      </div>
    );
  }

  const cycling = isCycling(analysis.workout?.type);
  const pace = analysis.pacing?.average_pace_min_km;
  const speed = analysis.pacing?.average_speed_kmh;
  const metrics = [
    Number.isFinite(analysis.comparison?.distance_km?.current) && analysis.comparison.distance_km.current > 0
      ? [t("workoutDetailExtended.distance"), formatDistance(analysis.comparison.distance_km.current, { unitSystem: "metric" })] : null,
    Number.isFinite(analysis.comparison?.duration_minutes?.current) && analysis.comparison.duration_minutes.current > 0
      ? [t("workoutDetailExtended.duration"), formatDuration(analysis.comparison.duration_minutes.current)] : null,
    cycling
      ? (Number.isFinite(speed) && speed > 0 ? [t("workoutDetailExtended.averageSpeed"), formatSpeed(speed, { unitSystem: "metric" })] : null)
      : (Number.isFinite(pace) && pace > 0
        ? [t("workoutDetailExtended.averagePace"), formatPaceDisplay(pace)]
        : Number.isFinite(speed) && speed > 0 ? [t("workoutDetailExtended.averageSpeed"), formatSpeed(speed, { unitSystem: "metric" })] : null),
    Number.isFinite(analysis.physiology?.avg_hr) && analysis.physiology.avg_hr > 0
      ? [t("workoutDetailExtended.averageHeartRate"), `${analysis.physiology.avg_hr} bpm`] : null,
  ].filter(Boolean);
  const classification = getSessionClassification(analysis, t);
  const observation = getDistinctCoachObservation(analysis);
  const date = new Date(analysis.workout?.date);
  const dateStr = Number.isFinite(date.getTime()) ? date.toLocaleDateString(
    { fr: "fr-FR", es: "es-ES", en: "en-US" }[lang] || "en-US",
    { weekday: "short", month: "short", day: "numeric" },
  ) : "";

  return (
    <div className="p-4 pb-24" data-testid="detailed-analysis">
      <div className="flex items-center justify-between mb-3">
        <Link to={`/workout/${id}`} className="text-muted-foreground hover:text-foreground" aria-label={t("workout.back")}>
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <span className="font-mono text-[11px] uppercase text-muted-foreground">{t("detailedAnalysis.title")}</span>
        <span className="font-mono text-[11px] text-muted-foreground">{dateStr}</span>
      </div>

      <section className="mb-3 rounded-xl border border-border bg-card p-3" aria-labelledby="workout-summary-title">
        <h1 id="workout-summary-title" className="mb-2 font-heading text-base font-bold leading-tight">{analysis.workout?.name}</h1>
        {metrics.length > 0 && <dl className="grid grid-cols-2 gap-3" data-testid="primary-metrics">
          {metrics.map(([label, value]) => <div key={label}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-sm font-semibold">{value}</dd>
          </div>)}
        </dl>}
        {metrics.length === 0 && analysis.summary?.text && <p className="mt-3 font-sans text-sm leading-relaxed" data-testid="header-context">{analysis.summary.text}</p>}
      </section>

      <WorkoutPhaseAnalysis phaseAnalysis={analysis.phase_analysis} t={t} lang={lang} />

      {(getAnalysisTakeaway(analysis) || classification || analysis.signals?.intensity?.available === true) && <section className="my-3 rounded-xl border border-border bg-card p-3">
        <h2 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">{t("detailedAnalysis.meaning")}</h2>
        {getAnalysisTakeaway(analysis) && <p className="font-sans text-sm leading-relaxed" data-testid="meaning-text">{getAnalysisTakeaway(analysis)}</p>}
        {classification && <p className="mt-2 text-sm text-muted-foreground" data-testid="session-classification">{classification.label}: {classification.text}</p>}
        {analysis.signals?.intensity?.available === true && analysis.signals.intensity.text && (
          <p className="mt-2 text-sm">{t("analysis.intensity")}: {analysis.signals.intensity.text}</p>
        )}
      </section>}

      {observation && <section className="my-3 rounded-xl border border-border bg-card p-3">
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

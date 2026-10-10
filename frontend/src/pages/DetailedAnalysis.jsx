import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { getAnalysisLimitations, hasCoachObservation } from "@/lib/workoutAnalysis";
import WorkoutAnalysisAccessNotice from "@/components/WorkoutAnalysisAccessNotice";
import {
  ArrowLeft,
  Zap,
  Scale,
  Activity,
  Lightbulb,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  Loader2,
  Bike,
  Footprints,
  HeartPulse,
} from "lucide-react";

import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

const getWorkoutIcon = (type) => {
  if (type === "cycle") return Bike;
  return Footprints;
};

const formatSignedMetric = (metric, suffix = "") => {
  if (!metric || metric.difference == null) return "--";
  const sign = metric.difference > 0 ? "+" : "";
  return `${sign}${metric.difference}${suffix}`;
};

export default function DetailedAnalysis() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t, lang } = useLanguage();
  const { loading: subscriptionLoading, hasFeature } = useSubscription();
  const canAccessAnalysis = !subscriptionLoading && hasFeature("coach_workout_analysis") === true;
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);

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

  const goToAskCoach = () => navigate("/coach");

  if (subscriptionLoading || (canAccessAnalysis && loading)) {
    return (
      <div className="p-4 pb-24 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {t("detailedAnalysis.loading")}
          </span>
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

  const Icon = getWorkoutIcon(analysis.workout?.type);
  const limitations = getAnalysisLimitations(analysis, t);
  const observationAvailable = hasCoachObservation(analysis);
  const dateStr = new Date(analysis.workout?.date).toLocaleDateString(
    lang === "fr" ? "fr-FR" : lang === "es" ? "es-ES" : "en-US",
    { weekday: "short", month: "short", day: "numeric" },
  );

  return (
    <div className="p-4 pb-24" data-testid="detailed-analysis">
      <div className="flex items-center justify-between mb-3">
        <Link to={`/workout/${id}`} className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-muted-foreground" />
          <span className="font-mono text-[11px] uppercase text-muted-foreground">{t("detailedAnalysis.title")}</span>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">{dateStr}</span>
      </div>

      <Card className="bg-card border-border mb-3">
        <CardContent className="p-3">
          <h1 className="font-heading text-base uppercase tracking-tight font-bold mb-2 leading-tight">
            {analysis.workout?.name}
          </h1>
          <p className="font-sans text-sm text-secondary-foreground leading-relaxed" data-testid="header-context">
            {analysis.summary?.text}
          </p>
        </CardContent>
      </Card>

      <Card className="bg-card border-border mb-3">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-muted-foreground" />
            <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              {t("detailedAnalysis.execution")}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <p className="font-mono text-[11px] uppercase text-muted-foreground mb-1">{t("detailedAnalysis.intensity")}</p>
              <p className="font-mono text-xs">{analysis.signals?.intensity?.available ? analysis.signals.intensity.text : "--"}</p>
            </div>
            <div>
              <p className="font-mono text-[11px] uppercase text-muted-foreground mb-1">{t("detailedAnalysis.volume")}</p>
              <p className="font-mono text-xs">{analysis.signals?.volume?.text || "--"}</p>
            </div>
            <div>
              <p className="font-mono text-[11px] uppercase text-muted-foreground mb-1">{t("analysis.type")}</p>
              <p className="font-mono text-xs">{analysis.signals?.session_type?.text || "--"}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {analysis.physiology?.available && (
        <Card className="bg-card border-border mb-3" data-testid="physiology-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <HeartPulse className="w-4 h-4 text-muted-foreground" />
              <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                {t("sessions.physiology")}
              </span>
            </div>
            <p className="font-mono text-xs text-muted-foreground leading-relaxed">
              HR {analysis.physiology.avg_hr ?? "--"} / max {analysis.physiology.max_hr ?? "--"}
            </p>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border mb-3">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-muted-foreground" />
            <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              {t("detailedAnalysis.meaning")}
            </span>
          </div>
          <p className="font-sans text-sm text-secondary-foreground leading-relaxed" data-testid="meaning-text">
            {analysis.meaning?.text || t("workoutDetailExtended.meaningUnavailable")}
          </p>
        </CardContent>
      </Card>

        <Card className="bg-card border-border mb-3">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <Lightbulb className="w-4 h-4 text-primary" />
              <span className="font-mono text-[11px] uppercase tracking-widest text-primary">
                {t("workoutDetailExtended.coachObservation")}
              </span>
            </div>
            <p className={`font-sans text-sm leading-relaxed ${observationAvailable ? "text-secondary-foreground" : "text-muted-foreground"}`} data-testid={observationAvailable ? "advice-text" : "advice-unavailable"}>
              {observationAvailable ? analysis.advice.text : t("workoutDetailExtended.adviceUnavailable")}
            </p>
          </CardContent>
        </Card>

      <Card className="bg-card border-border mb-3">
        <CardContent className="p-0">
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="w-full p-3 flex items-center justify-between text-left"
            data-testid="advanced-toggle"
            aria-expanded={showAdvanced}
            aria-controls="detailed-analysis-advanced"
          >
            <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              {t("detailedAnalysis.advanced")}
            </span>
            {showAdvanced ? (
              <ChevronUp className="w-4 h-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="w-4 h-4 text-muted-foreground" />
            )}
          </button>
          {showAdvanced && (
            <div id="detailed-analysis-advanced" className="px-3 pb-3 border-t border-border pt-3 grid gap-2" data-testid="advanced-text">
              <p className="font-mono text-[11px] text-muted-foreground">version: {analysis.version}</p>
              <p className="font-mono text-[11px] text-muted-foreground">
                baseline: {analysis.comparison?.baseline_sample_count ?? "--"}
              </p>
              {analysis.comparison?.distance_km && (
                <p className="font-mono text-[11px] text-muted-foreground">
                  distance: {formatSignedMetric(analysis.comparison.distance_km, " km")}
                </p>
              )}
              {analysis.comparison?.duration_minutes && (
                <p className="font-mono text-[11px] text-muted-foreground">
                  duration: {formatSignedMetric(analysis.comparison.duration_minutes, " min")}
                </p>
              )}
              {!limitations.some((item) => item.code === "limitations.heart_rate") && !analysis.physiology?.available && analysis.physiology?.reason_unavailable && (
                <p className="font-sans text-sm leading-relaxed text-secondary-foreground">{analysis.physiology.reason_unavailable}</p>
              )}
              {!limitations.some((item) => item.code === "limitations.baseline") && !analysis.comparison?.available && analysis.comparison?.reason_unavailable && (
                <p className="font-sans text-sm leading-relaxed text-secondary-foreground">{analysis.comparison.reason_unavailable}</p>
              )}
              {limitations.length > 0 && <section data-testid="analysis-limitations">
                <h3 className="text-sm font-semibold">{t("workoutDetailExtended.limitations")}</h3>
                {limitations.map((item) => <p key={item.code} className="text-sm text-muted-foreground">{item.text}</p>)}
              </section>}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="mt-4">
        <Button
          onClick={goToAskCoach}
          data-testid="ask-coach-btn"
          className="w-full bg-muted hover:bg-muted/80 text-foreground border border-border rounded-none h-11 sm:h-10 font-mono text-xs uppercase tracking-wider flex items-center justify-center gap-2"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          {t("detailedAnalysis.askCoach")}
        </Button>
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/context/LanguageContext";
import { 
  ArrowLeft, 
  Zap,
  Scale,
  Activity,
  AlertCircle,
  Lightbulb,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  Loader2,
  Bike,
  Footprints
} from "lucide-react";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

const getWorkoutIcon = (type) => {
  if (type === "cycle") return Bike;
  return Footprints;
};

export default function DetailedAnalysis() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t, lang } = useLanguage();
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    loadAnalysis();
  }, [id, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadAnalysis = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/coach/detailed-analysis/${id}?language=${lang}`);
      setAnalysis(res.data);
    } catch (error) {
      console.error("Failed to load analysis:", error);
    } finally {
      setLoading(false);
    }
  };

  const goToAskCoach = () => {
    navigate("/coach");
  };

  if (loading) {
    return (
      <div className="p-4 pb-24 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            {t("detailedAnalysis.loading")}
          </span>
        </div>
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

  const Icon = getWorkoutIcon(analysis.workout_type);
  const dateStr = new Date(analysis.workout_date).toLocaleDateString(
    lang === "fr" ? "fr-FR" : "en-US",
    { weekday: "short", month: "short", day: "numeric" }
  );

  // Get execution badge colors
  const getIntensityColor = (intensity) => {
    const lower = intensity?.toLowerCase();
    if (lower?.includes("soutenu") || lower?.includes("sustain") || lower?.includes("hard")) {
      return "text-chart-1 bg-chart-1/10";
    }
    if (lower?.includes("facile") || lower?.includes("easy")) {
      return "text-chart-2 bg-chart-2/10";
    }
    return "text-chart-3 bg-chart-3/10";
  };

  return (
    <div className="p-4 pb-24" data-testid="detailed-analysis">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <Link to={`/workout/${id}`} className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-muted-foreground" />
          <span className="font-mono text-[10px] uppercase text-muted-foreground">
            {t("detailedAnalysis.title")}
          </span>
        </div>
        <span className="font-mono text-[10px] text-muted-foreground">{dateStr}</span>
      </div>

      {/* 1) HEADER - Session Context */}
      <Card className="bg-card border-border mb-3">
        <CardContent className="p-3">
          <h1 className="font-heading text-base uppercase tracking-tight font-bold mb-2 leading-tight">
            {analysis.header?.session_name || analysis.workout_name}
          </h1>
          <p className="font-mono text-sm text-muted-foreground leading-relaxed" data-testid="header-context">
            {analysis.header?.context}
          </p>
        </CardContent>
      </Card>

      {/* 2) CARD - EXECUTION */}
      <Card className="bg-card border-border mb-3">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-muted-foreground" />
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              {t("detailedAnalysis.execution")}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <p className="font-mono text-[9px] uppercase text-muted-foreground mb-1">
                {t("detailedAnalysis.intensity")}
              </p>
              <span className={`inline-block px-2 py-0.5 rounded-sm font-mono text-xs ${getIntensityColor(analysis.execution?.intensity)}`}>
                {analysis.execution?.intensity}
              </span>
            </div>
            <div>
              <p className="font-mono text-[9px] uppercase text-muted-foreground mb-1">
                {t("detailedAnalysis.volume")}
              </p>
              <p className="font-mono text-xs">{analysis.execution?.volume}</p>
            </div>
            <div>
              <p className="font-mono text-[9px] uppercase text-muted-foreground mb-1">
                {t("detailedAnalysis.regularity")}
              </p>
              <p className="font-mono text-xs">{analysis.execution?.regularity}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 3) CARD - WHAT IT MEANS */}
      {analysis.meaning?.text && (
        <Card className="bg-card border-border mb-3">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-4 h-4 text-muted-foreground" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                {t("detailedAnalysis.meaning")}
              </span>
            </div>
            <p className="font-mono text-xs text-muted-foreground leading-relaxed" data-testid="meaning-text">
              {analysis.meaning.text}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 4) CARD - RISK & RECOVERY */}
      {analysis.recovery?.text && (
        <Card className="bg-orange-500/5 border-orange-500/20 mb-3">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="w-4 h-4 text-orange-400" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-orange-400">
                {t("detailedAnalysis.recovery")}
              </span>
            </div>
            <p className="font-mono text-xs text-orange-300 leading-relaxed" data-testid="recovery-text">
              {analysis.recovery.text}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 5) CARD - COACH ADVICE */}
      {analysis.advice?.text && (
        <Card className="bg-primary/5 border-primary/20 mb-3">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <Lightbulb className="w-4 h-4 text-primary" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-primary">
                {t("detailedAnalysis.advice")}
              </span>
            </div>
            <p className="font-mono text-xs text-primary leading-relaxed" data-testid="advice-text">
              {analysis.advice.text}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 6) ACCORDION - GO FURTHER (Optional) */}
      {analysis.advanced?.comparisons && (
        <Card className="bg-card border-border mb-3">
          <CardContent className="p-0">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="w-full p-3 flex items-center justify-between text-left"
              data-testid="advanced-toggle"
            >
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                {t("detailedAnalysis.advanced")}
              </span>
              {showAdvanced ? (
                <ChevronUp className="w-4 h-4 text-muted-foreground" />
              ) : (
                <ChevronDown className="w-4 h-4 text-muted-foreground" />
              )}
            </button>
            {showAdvanced && (
              <div className="px-3 pb-3 border-t border-border pt-3">
                <p className="font-mono text-[11px] text-muted-foreground leading-relaxed whitespace-pre-line" data-testid="advanced-text">
                  {analysis.advanced.comparisons}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="mt-4">
        <Button
          onClick={goToAskCoach}
          data-testid="ask-coach-btn"
          className="w-full bg-muted hover:bg-muted/80 text-foreground border border-border rounded-none h-10 font-mono text-xs uppercase tracking-wider flex items-center justify-center gap-2"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          {t("detailedAnalysis.askCoach")}
        </Button>
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/context/LanguageContext";
import { 
  TrendingUp, 
  TrendingDown, 
  Minus, 
  Activity, 
  Flame,
  Target,
  Calendar,
  MessageCircle,
  Loader2,
  RefreshCw,
  CheckCircle2,
  History,
  Flag,
  Sparkles,
  AlertTriangle
} from "lucide-react";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default";

// CARTE 2 - Signal Card Component
function SignalCard({ signal, t }) {
  const getIcon = () => {
    if (signal.key === "load") {
      if (signal.status === "up") return <TrendingUp className="w-5 h-5" />;
      if (signal.status === "down") return <TrendingDown className="w-5 h-5" />;
      return <Minus className="w-5 h-5" />;
    }
    if (signal.key === "intensity") {
      if (signal.status === "hard") return <Flame className="w-5 h-5" />;
      if (signal.status === "easy") return <Activity className="w-5 h-5" />;
      return <Target className="w-5 h-5" />;
    }
    return <Calendar className="w-5 h-5" />;
  };

  const getColor = () => {
    if (signal.key === "load") {
      if (signal.status === "up") return "text-orange-400";
      if (signal.status === "down") return "text-blue-400";
      return "text-emerald-400";
    }
    if (signal.key === "intensity") {
      if (signal.status === "hard") return "text-orange-400";
      if (signal.status === "easy") return "text-emerald-400";
      return "text-primary";
    }
    // Regularity
    if (signal.status === "high") return "text-emerald-400";
    if (signal.status === "moderate") return "text-amber-400";
    return "text-red-400";
  };

  const getLabel = () => {
    if (signal.key === "load") {
      return t(`digest.load.${signal.status}`);
    }
    if (signal.key === "intensity") {
      return t(`digest.intensity.${signal.status}`);
    }
    return t(`digest.regularity.${signal.status}`);
  };

  return (
    <div className="flex flex-col items-center p-3 bg-muted/30 rounded-lg">
      <div className={`mb-2 ${getColor()}`}>
        {getIcon()}
      </div>
      <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground mb-1">
        {t(`digest.signals.${signal.key}`)}
      </p>
      <p className={`font-mono text-xs font-semibold ${getColor()}`}>
        {signal.value || getLabel()}
      </p>
    </div>
  );
}

export default function Digest() {
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const navigate = useNavigate();
  const [review, setReview] = useState(null);
  const [ragReview, setRagReview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState("current"); // "current" or "history"
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);

  useEffect(() => {
    loadReview();
  }, [lang]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === "history" && history.length === 0) {
      loadHistory();
    }
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadReview = async (forceRefresh = false) => {
    if (forceRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    
    try {
      const [res, ragRes] = await Promise.all([
        axios.get(`${API}/coach/digest?user_id=${USER_ID}&language=${lang}`),
        axios.get(`${API}/rag/weekly-review`).catch(() => ({ data: null }))
      ]);
      setReview(res.data);
      setRagReview(ragRes.data);
    } catch (error) {
      console.error("Failed to load review:", error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const loadHistory = async (loadMore = false) => {
    setHistoryLoading(true);
    try {
      const skip = loadMore ? history.length : 0;
      const res = await axios.get(`${API}/coach/digest/history?user_id=${USER_ID}&limit=10&skip=${skip}`);
      if (loadMore) {
        setHistory(prev => [...prev, ...res.data.digests]);
      } else {
        setHistory(res.data.digests);
      }
      setHasMoreHistory(res.data.has_more);
    } catch (error) {
      console.error("Failed to load history:", error);
    } finally {
      setHistoryLoading(false);
    }
  };

  const formatDateRange = () => {
    if (!review) return "";
    const start = new Date(review.period_start);
    const end = new Date(review.period_end);
    const locale = lang === "fr" ? "fr-FR" : "en-US";
    const opts = { month: "short", day: "numeric" };
    return `${start.toLocaleDateString(locale, opts)} - ${end.toLocaleDateString(locale, opts)}`;
  };

  const formatHours = (minutes) => {
    if (!minutes) return "0";
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours === 0) return `${mins}min`;
    if (mins === 0) return `${hours}h`;
    return `${hours}h${mins}`;
  };

  const calculateDaysUntil = (dateStr) => {
    if (!dateStr) return null;
    const eventDate = new Date(dateStr);
    const today = new Date();
    const diffTime = eventDate - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays > 0 ? diffDays : null;
  };

  if (loading) {
    return (
      <div className="p-6 md:p-8 pb-24 md:pb-8 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
          <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            {t("digest.generating")}
          </span>
        </div>
      </div>
    );
  }

  const metrics = review?.metrics || {};
  const comparison = review?.comparison || {};
  const signals = review?.signals || [];
  const recommendations = review?.recommendations || [];
  const recommendationsFollowup = review?.recommendations_followup;
  const userGoal = review?.user_goal;
  const daysUntil = userGoal ? calculateDaysUntil(userGoal.event_date) : null;

  // Format date for history items
  const formatHistoryDate = (dateStr) => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    const locale = lang === "fr" ? "fr-FR" : "en-US";
    return date.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
  };

  // Render history view
  const renderHistory = () => {
    if (historyLoading && history.length === 0) {
      return (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
        </div>
      );
    }

    if (history.length === 0) {
      return (
        <div className="text-center py-12">
          <History className="w-10 h-10 mx-auto mb-3 text-muted-foreground/50" />
          <p className="text-muted-foreground text-sm">
            {t("digestExtended.noPreviousReviews")}
          </p>
        </div>
      );
    }

    return (
      <div className="space-y-3">
        {history.map((digest, index) => (
          <Card key={index} className="bg-card border-border">
            <CardContent className="p-4">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                    {formatHistoryDate(digest.generated_at)}
                  </p>
                  <p className="font-mono text-[9px] text-muted-foreground/70">
                    {digest.period_start && digest.period_end && (
                      <>
                        {new Date(digest.period_start).toLocaleDateString(lang === "fr" ? "fr-FR" : "en-US", { day: "numeric", month: "short" })}
                        {" - "}
                        {new Date(digest.period_end).toLocaleDateString(lang === "fr" ? "fr-FR" : "en-US", { day: "numeric", month: "short" })}
                      </>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-2 text-right">
                  <div>
                    <p className="font-mono text-sm font-bold">{digest.metrics?.total_sessions || 0}</p>
                    <p className="font-mono text-[8px] uppercase text-muted-foreground">
                      {t("digestExtended.sessionsCount")}
                    </p>
                  </div>
                  <div>
                    <p className="font-mono text-sm font-bold">
                      {formatDistance(digest.metrics?.total_km || 0, { unitSystem })}
                    </p>
                    <p className="font-mono text-[8px] uppercase text-muted-foreground">
                      {t("digest.km")}
                    </p>
                  </div>
                </div>
              </div>
              <p className="font-mono text-xs leading-relaxed text-muted-foreground line-clamp-2">
                {digest.coach_summary || "-"}
              </p>
            </CardContent>
          </Card>
        ))}
        
        {hasMoreHistory && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadHistory(true)}
            disabled={historyLoading}
            className="w-full"
          >
            {historyLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              t("digestExtended.loadMore")
            )}
          </Button>
        )}
      </div>
    );
  };

  return (
    <div className="p-4 md:p-8 pb-24 md:pb-8 max-w-lg mx-auto" data-testid="digest-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="font-heading text-xl md:text-2xl uppercase tracking-tight font-bold mb-0.5">
            {t("digest.title")}
          </h1>
          {activeTab === "current" && (
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              {formatDateRange()}
            </p>
          )}
        </div>
        {activeTab === "current" && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => loadReview(true)}
            disabled={refreshing}
            data-testid="refresh-review"
            className="text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-4">
        <Button
          variant={activeTab === "current" ? "default" : "outline"}
          size="sm"
          onClick={() => setActiveTab("current")}
          className="flex-1"
          data-testid="tab-current"
        >
          <Calendar className="w-4 h-4 mr-2" />
          {t("digestExtended.thisWeek")}
        </Button>
        <Button
          variant={activeTab === "history" ? "default" : "outline"}
          size="sm"
          onClick={() => setActiveTab("history")}
          className="flex-1"
          data-testid="tab-history"
        >
          <History className="w-4 h-4 mr-2" />
          {t("digestExtended.history")}
        </Button>
      </div>

      {/* History Tab Content */}
      {activeTab === "history" ? (
        renderHistory()
      ) : (
        <>
          {/* User Goal Context - if exists */}
      {userGoal && daysUntil && (
        <Card className="bg-amber-500/5 border-amber-500/20 mb-4">
          <CardContent className="p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Flag className="w-4 h-4 text-amber-400 flex-shrink-0" />
                <div>
                  <p className="font-mono text-xs text-amber-400 font-semibold">
                    {userGoal.event_name}
                  </p>
                  <p className="font-mono text-[10px] text-muted-foreground">
                    {formatDistance(userGoal.distance_km, { unitSystem })} • {daysUntil}{" "}
                    {t("settingsExtended.days")}
                  </p>
                </div>
              </div>
              {userGoal.target_pace && (
                <div className="text-right">
                  <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                    {t("settings.targetPace")}
                  </p>
                  <p className="font-mono text-sm font-bold text-amber-400">
                    {userGoal.target_pace}
                  </p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* CARTE 1 - Synthèse du Coach */}
      <Card className="bg-card border-border mb-4">
        <CardContent className="p-4">
          <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground mb-2">
            {t("digest.coachSummary")}
          </p>
          <p className="font-mono text-sm md:text-base leading-relaxed" data-testid="coach-summary">
            {review?.coach_summary || t("digest.noData")}
          </p>
        </CardContent>
      </Card>

      {/* CARTE 2 - Signaux Clés */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        {signals.map((signal) => (
          <SignalCard 
            key={signal.key}
            signal={signal}
            t={t}
          />
        ))}
      </div>

      {/* CARTE 3 - Chiffres Essentiels */}
      <Card className="bg-card border-border mb-4">
        <CardContent className="p-4">
          <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground mb-3">
            {t("digest.essentialNumbers")}
          </p>
          <div className="flex items-center justify-between divide-x divide-border">
            <div className="flex-1 text-center pr-3">
              <p className="font-mono text-2xl font-bold text-foreground">
                {metrics.total_sessions || 0}
              </p>
              <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {t("digest.sessions")}
              </p>
            </div>
            <div className="flex-1 text-center px-3">
              <p className="font-mono text-2xl font-bold text-foreground">
                {formatDistance(metrics.total_distance_km || 0, { unitSystem })}
              </p>
              <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {t("digest.km")}
              </p>
            </div>
            <div className="flex-1 text-center pl-3">
              <p className="font-mono text-2xl font-bold text-foreground">
                {formatHours(metrics.total_duration_min)}
              </p>
              <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {t("digest.hours")}
              </p>
            </div>
          </div>
          {/* Comparison vs last week */}
          {comparison.distance_diff_pct !== undefined && comparison.distance_diff_pct !== 0 && (
            <div className="mt-3 pt-3 border-t border-border">
              <p className={`font-mono text-xs text-center ${
                comparison.distance_diff_pct > 0 ? "text-orange-400" : "text-blue-400"
              }`}>
                {comparison.distance_diff_pct > 0 ? "+" : ""}{comparison.distance_diff_pct}% {t("digest.vsLastWeek")}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recommendations Followup - Last week's advice */}
      {recommendationsFollowup && (
        <Card className="bg-muted/30 border-border mb-4">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <History className="w-4 h-4 text-muted-foreground flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground mb-1">
                  {t("digest.recommendationsFollowup")}
                </p>
                <p className="font-mono text-xs text-muted-foreground leading-relaxed" data-testid="recommendations-followup">
                  {recommendationsFollowup}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* CARTE 4 - Lecture du Coach */}
      {review?.coach_reading && (
        <Card className="bg-card border-border mb-4">
          <CardContent className="p-4">
            <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground mb-2">
              {t("digest.coachReading")}
            </p>
            <p className="font-mono text-sm leading-relaxed text-muted-foreground" data-testid="coach-reading">
              {review.coach_reading}
            </p>
          </CardContent>
        </Card>
      )}

      {/* CARTE 5 - Préconisations du Coach (OBLIGATOIRE) */}
      {recommendations.length > 0 && (
        <Card className="bg-primary/5 border-primary/20 mb-4">
          <CardContent className="p-4">
            <p className="font-mono text-[9px] uppercase tracking-widest text-primary mb-3">
              {t("digest.recommendations")}
            </p>
            <div className="space-y-2">
              {recommendations.map((rec, idx) => (
                <div key={idx} className="flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 mt-0.5 text-primary flex-shrink-0" />
                  <p className="font-mono text-sm text-foreground leading-relaxed">
                    {rec}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* RAG ENRICHED INSIGHTS - NEW */}
      {ragReview && (
        <Card className="bg-card border-border mb-4" data-testid="rag-weekly-card">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles className="w-4 h-4 text-amber-400" />
              <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {t("digestExtended.personalizedRag")}
              </p>
            </div>
            
            {/* RAG Summary */}
            <p className="font-mono text-xs text-muted-foreground leading-relaxed mb-3 whitespace-pre-line" data-testid="rag-weekly-summary">
              {ragReview.rag_summary?.split('\n').slice(0, 5).join('\n')}
            </p>
            
            {/* RAG Metrics inline */}
            {ragReview.metrics && (
              <div className="flex items-center gap-4 mb-3 p-2 bg-muted/30 rounded-sm">
                <div className="text-center">
                  <p className="font-mono text-sm font-bold">
                    {formatDistance(ragReview.metrics.km_total || 0, { unitSystem })}
                  </p>
                  <p className="font-mono text-[8px] text-muted-foreground uppercase">
                    {t("digest.km")}
                  </p>
                </div>
                <div className="text-center">
                  <p className="font-mono text-sm font-bold">{ragReview.metrics.nb_seances}</p>
                  <p className="font-mono text-[8px] text-muted-foreground uppercase">
                    {t("digestExtended.sessionsCount")}
                  </p>
                </div>
                <div className="text-center">
                  <p className="font-mono text-sm font-bold">{ragReview.metrics.allure_moy}</p>
                  <p className="font-mono text-[8px] text-muted-foreground uppercase">/km</p>
                </div>
                <div className="text-center">
                  <p className="font-mono text-sm font-bold">{ragReview.metrics.duree_totale}</p>
                  <p className="font-mono text-[8px] text-muted-foreground uppercase">
                    {t("digestExtended.duration")}
                  </p>
                </div>
              </div>
            )}
            
            {/* Comparison badge */}
            {ragReview.comparison?.vs_prev_week && (
              <div className={`inline-flex items-center gap-1 px-2 py-1 rounded-sm ${
                ragReview.comparison.vs_prev_week.includes('+') ? 'bg-emerald-500/10 text-emerald-400' : 'bg-blue-500/10 text-blue-400'
              }`}>
                {ragReview.comparison.vs_prev_week.includes('+') ? (
                  <TrendingUp className="w-3 h-3" />
                ) : (
                  <TrendingDown className="w-3 h-3" />
                )}
                <span className="font-mono text-[10px]">{ragReview.comparison.vs_prev_week}</span>
              </div>
            )}

            {/* Points forts & améliorer */}
            {(ragReview.points_forts?.length > 0 || ragReview.points_ameliorer?.length > 0) && (
              <div className="mt-3 pt-3 border-t border-border flex flex-wrap gap-2">
                {ragReview.points_forts?.slice(0, 2).map((point, i) => (
                  <span key={`fort-${i}`} className="inline-flex items-center gap-1 px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded-sm">
                    <Target className="w-3 h-3" />
                    <span className="font-mono text-[10px]">{point}</span>
                  </span>
                ))}
                {ragReview.points_ameliorer?.slice(0, 1).map((point, i) => (
                  <span key={`ameliorer-${i}`} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-500/10 text-amber-400 rounded-sm">
                    <AlertTriangle className="w-3 h-3" />
                    <span className="font-mono text-[10px]">{point}</span>
                  </span>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* CARTE 6 - Question au Coach (Optionnel) */}
      <Button
        onClick={() => navigate("/coach")}
        variant="ghost"
        data-testid="ask-coach-btn"
        className="w-full bg-muted/50 hover:bg-muted text-muted-foreground hover:text-foreground border border-border/50 rounded-lg h-12 font-mono text-xs uppercase tracking-wider flex items-center justify-center gap-2"
      >
        <MessageCircle className="w-4 h-4" />
        <span>{t("digest.askCoach")}</span>
      </Button>
        </>
      )}
    </div>
  );
}

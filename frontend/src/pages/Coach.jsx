import { useState, useRef, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send, Loader2, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { useLanguage } from "@/context/LanguageContext";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

export default function Coach() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [historyLoadError, setHistoryLoadError] = useState(false);
  const [analyzingWorkout, setAnalyzingWorkout] = useState(null);
  const [activeWorkoutId, setActiveWorkoutId] = useState(null);
  const [activeWorkoutMetadata, setActiveWorkoutMetadata] = useState(null);
  const activeWorkoutRef = useRef(null);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const { t, lang } = useLanguage();
  const [searchParams, setSearchParams] = useSearchParams();
  const hasTriggeredAnalysis = useRef(false);

  // Load conversation history on mount
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const res = await axios.get(`${API}/coach/history?limit=50`);
        setHistoryLoadError(false);
        setMessages(res.data.map(msg => ({
          role: msg.role,
          content: msg.content,
          workout_id: msg.workout_id,
          timestamp: msg.timestamp
        })));
      } catch (error) {
        console.error("Failed to load history:", error);
        setHistoryLoadError(true);
      } finally {
        setInitialLoading(false);
      }
    };
    loadHistory();
  }, []);

  // Check for workout analysis param
  useEffect(() => {
    const workoutId = searchParams.get("analyze");
    if (workoutId && !hasTriggeredAnalysis.current && !initialLoading) {
      hasTriggeredAnalysis.current = true;
      triggerWorkoutAnalysis(workoutId);
      // Clear the param after triggering
      setSearchParams({});
    }
  }, [searchParams, initialLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current?.scrollTo) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  const triggerWorkoutAnalysis = async (workoutId) => {
    activeWorkoutRef.current = workoutId;
    setActiveWorkoutId(workoutId);
    setActiveWorkoutMetadata({});
    setAnalyzingWorkout(workoutId);
    setLoading(true);

    // Fetch workout details for display
    let workoutName = "";
    try {
      const workoutRes = await axios.get(`${API}/workouts/${workoutId}`);
      workoutName = workoutRes.data.name || workoutId;
      const { name, distance_km, date } = workoutRes.data;
      const metadata = {
        ...(typeof name === "string" && name.trim() ? { name } : {}),
        ...(Number.isFinite(distance_km) && distance_km >= 0 ? { distance_km } : {}),
        ...(typeof date === "string" && date.trim() && Number.isFinite(new Date(date).getTime()) ? { date } : {}),
      };
      setActiveWorkoutMetadata(current => current === null ? null : metadata);
    } catch (e) {
      workoutName = workoutId;
    }

    if (activeWorkoutRef.current !== workoutId) {
      setLoading(false);
      setAnalyzingWorkout(null);
      return;
    }

    const analysisMessage = t("coachExtended.analysisPrompt").replace("{name}", workoutName);

    setMessages(prev => [...prev, { role: "user", content: analysisMessage, workout_id: workoutId }]);

    try {
      const response = await axios.post(`${API}/coach/analyze`, {
        message: analysisMessage,
        workout_id: workoutId,
        language: lang
      });

      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: response.data.response,
        workout_id: workoutId
      }]);
    } catch (error) {
      console.error("Analysis error:", error);
      toast.error(t("coach.error"));
      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: t("coach.unavailable"),
        workout_id: workoutId,
      }]);
    } finally {
      setLoading(false);
      setAnalyzingWorkout(null);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    const workoutId = activeWorkoutId || undefined;
    setInput("");
    setMessages(prev => [...prev, {
      role: "user",
      content: userMessage,
      ...(workoutId ? { workout_id: workoutId } : {}),
    }]);
    setLoading(true);

    try {
      const response = await axios.post(`${API}/coach/analyze`, {
        message: userMessage,
        ...(workoutId ? { workout_id: workoutId } : {}),
        language: lang,
      });

      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: response.data.response,
        ...(workoutId ? { workout_id: workoutId } : {}),
      }]);
    } catch (error) {
      console.error("Coach error:", error);
      toast.error(t("coach.error"));
      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: t("coach.unavailable"),
        ...(workoutId ? { workout_id: workoutId } : {}),
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleClearHistory = async () => {
    try {
      await axios.delete(`${API}/coach/history`);
      setMessages([]);
      handleCloseContext();
      setHistoryLoadError(false);
      toast.success(t("coachExtended.historyCleared"));
    } catch (error) {
      toast.error(t("common.error"));
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleSuggestion = (key) => {
    fillComposer(t(`coach.prompts.${key}`));
  };

  const fillComposer = (text) => {
    setInput(text);
    inputRef.current?.focus();
  };

  const handleCloseContext = () => {
    activeWorkoutRef.current = null;
    setActiveWorkoutId(null);
    setActiveWorkoutMetadata(null);
  };

  const lastWorkoutReplyIndex = activeWorkoutId ? messages.reduce(
    (lastIndex, msg, idx) => msg.role === "assistant" && msg.workout_id === activeWorkoutId ? idx : lastIndex,
    -1,
  ) : -1;
  const workoutContextParts = [
    activeWorkoutMetadata?.name,
    activeWorkoutMetadata?.distance_km != null
      ? `${activeWorkoutMetadata.distance_km.toLocaleString(lang, { maximumFractionDigits: 2 })} km`
      : null,
    activeWorkoutMetadata?.date
      ? new Date(activeWorkoutMetadata.date).toLocaleDateString(lang, { timeZone: "UTC" })
      : null,
  ].filter(part => part != null);

  if (initialLoading) {
    return (
      <div className="flex min-w-0 flex-col h-[calc(100dvh-4.5rem-5.25rem-env(safe-area-inset-bottom))]" data-testid="coach-page">
        <div className="px-4 py-3 md:px-8 md:py-4 border-b border-border">
          <div className="h-8 w-32 bg-muted rounded animate-pulse" />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col h-[calc(100dvh-4.5rem-5.25rem-env(safe-area-inset-bottom))]" data-testid="coach-page">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 md:px-8 md:py-4 border-b border-border">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="font-heading text-xl sm:text-2xl uppercase tracking-tight font-bold mb-1 break-words">
              {t("coach.title")}
            </h1>
            <p className="font-sans text-sm text-muted-foreground">
              {t("coach.subtitle")}
            </p>
          </div>
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClearHistory}
              aria-label={t("coach.clearHistory")}
              data-testid="clear-history"
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>

      {activeWorkoutId && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2 md:px-8" data-testid="coach-workout-context">
          <p className="min-w-0 flex-1 break-words text-sm text-muted-foreground">
            {workoutContextParts.length ? workoutContextParts.join(" · ") : t("coach.activeWorkout")}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0 rounded-full"
            aria-label={t("coach.closeContext")}
            onClick={handleCloseContext}
            data-testid="close-workout-context"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
      )}

      {/* Messages Area */}
      <ScrollArea ref={scrollRef} className="min-h-0 flex-1 p-4 md:p-8">
        {historyLoadError && messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center py-12" data-testid="coach-history-load-error">
            <Card className="w-full max-w-xl border-border bg-card/80 text-left shadow-sm">
              <CardContent className="space-y-3 p-5 sm:p-6">
                <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-primary">
                  {t("coach.subtitle")}
                </p>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {t("coach.unavailable")}
                </p>
              </CardContent>
            </Card>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center py-12" data-testid="coach-empty-state">
            <h2 className="font-sans text-xl font-medium mb-6">
              {t("coach.emptyState")}
            </h2>
            <div className="grid w-full max-w-xl gap-2 sm:grid-cols-2">
              {["nextWorkout", "recentRuns", "progress", "recovery"].map((key) => (
                <SuggestionButton
                  key={key}
                  onClick={() => handleSuggestion(key)}
                  text={t(`coach.suggestions.${key}`)}
                  testId={`suggestion-${key}`}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-6 pb-4">
            {messages.map((msg, idx) => (
              <div 
                key={idx} 
                className={`animate-in ${msg.role === "user" ? "text-right" : ""}`}
                data-testid={`message-${idx}`}
                data-workout-id={msg.workout_id}
              >
                {msg.role === "user" ? (
                  <div className="inline-block text-left max-w-[85%] md:max-w-[70%]">
                    <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground mb-2">
                      {t("coach.you")}
                    </p>
                    <Card className="bg-muted border-border">
                      <CardContent className="p-4">
                        <p className="font-sans text-sm whitespace-pre-wrap break-words leading-relaxed">{msg.content}</p>
                      </CardContent>
                    </Card>
                  </div>
                ) : (
                  <div className="max-w-[85%] md:max-w-[70%]">
                    <p className="font-mono text-[11px] uppercase tracking-widest text-primary mb-2">
                      {t("coach.replyLabel")}
                    </p>
                    <div className="coach-message">
                      <p className="font-sans text-sm whitespace-pre-wrap break-words leading-relaxed">
                        {msg.content}
                      </p>
                    </div>
                    {idx === lastWorkoutReplyIndex && (
                      <div className="mt-3 flex flex-wrap gap-2" data-testid="coach-followup-chips">
                        {["compare", "takeaway"].map(key => (
                          <button
                            key={key}
                            type="button"
                            disabled={loading}
                            onClick={() => fillComposer(t(`coach.followups.${key}`))}
                            className="max-w-full rounded-full border border-border px-3 py-2 text-left text-sm text-secondary-foreground break-words hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                          >
                            {t(`coach.followups.${key}`)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="animate-in">
                <p className="font-mono text-[11px] uppercase tracking-widest text-primary mb-2">
                  {t("coach.replyLabel")}
                </p>
                <div className="coach-message flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                  <span className="font-mono text-xs text-muted-foreground">
                    {analyzingWorkout 
                      ? t("coachExtended.analyzing")
                      : t("coachExtended.thinking")
                    }
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </ScrollArea>

      {/* Input Area */}
      <div className="shrink-0 p-4 md:p-6 border-t border-border bg-background">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <Textarea
            ref={inputRef}
            data-testid="coach-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("coach.placeholder")}
            aria-label={t("coach.placeholder")}
            className="flex-1 min-w-0 min-h-[44px] max-h-[120px] resize-none bg-muted border-input focus:border-primary rounded-2xl font-sans text-sm"
            disabled={loading}
          />
          <Button
            type="submit"
            data-testid="coach-submit"
            aria-label={t("coach.send")}
            disabled={!input.trim() || loading}
            className="shrink-0 bg-primary text-primary-foreground hover:bg-primary/90 rounded-full uppercase font-bold tracking-wider text-xs h-11 px-4"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}

function SuggestionButton({ onClick, text, testId }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className="block w-full rounded-2xl p-3 text-left font-sans text-sm text-secondary-foreground border border-border hover:border-primary/30 hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {text}
    </button>
  );
}

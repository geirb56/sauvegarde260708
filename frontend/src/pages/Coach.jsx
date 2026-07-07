import { useState, useRef, useEffect } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send, Loader2, Trash2, Activity } from "lucide-react";
import { toast } from "sonner";
import { useLanguage } from "@/context/LanguageContext";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default"; // In production, this would be the authenticated user ID

export default function Coach() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [analyzingWorkout, setAnalyzingWorkout] = useState(null);
  const scrollRef = useRef(null);
  const { t, lang } = useLanguage();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const hasTriggeredAnalysis = useRef(false);

  // Load conversation history on mount
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const res = await axios.get(`${API}/coach/history?user_id=${USER_ID}&limit=50`);
        setMessages(res.data.map(msg => ({
          role: msg.role,
          content: msg.content,
          workout_id: msg.workout_id,
          timestamp: msg.timestamp
        })));
      } catch (error) {
        console.error("Failed to load history:", error);
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
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  const triggerWorkoutAnalysis = async (workoutId) => {
    setAnalyzingWorkout(workoutId);
    setLoading(true);

    // Fetch workout details for display
    let workoutName = "";
    try {
      const workoutRes = await axios.get(`${API}/workouts/${workoutId}`);
      workoutName = workoutRes.data.name || workoutId;
    } catch (e) {
      workoutName = workoutId;
    }

    const analysisMessage = t("coachExtended.analysisPrompt").replace("{name}", workoutName);

    setMessages(prev => [...prev, { role: "user", content: analysisMessage, workout_id: workoutId }]);

    try {
      const response = await axios.post(`${API}/coach/analyze`, {
        message: analysisMessage,
        workout_id: workoutId,
        language: lang,
        deep_analysis: true,
        user_id: USER_ID
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
        content: t("coach.unavailable")
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
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: userMessage }]);
    setLoading(true);

    try {
      const response = await axios.post(`${API}/coach/analyze`, {
        message: userMessage,
        language: lang,
        user_id: USER_ID
      });

      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: response.data.response 
      }]);
    } catch (error) {
      console.error("Coach error:", error);
      toast.error(t("coach.error"));
      setMessages(prev => [...prev, { 
        role: "assistant", 
        content: t("coach.unavailable")
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleClearHistory = async () => {
    try {
      await axios.delete(`${API}/coach/history?user_id=${USER_ID}`);
      setMessages([]);
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
    const suggestions = {
      trainingLoad: t("coachExtended.trainingLoadSuggestion"),
      heartRate: t("coachExtended.heartRateSuggestion"),
      paceConsistency: t("coachExtended.paceConsistencySuggestion")
    };
    setInput(suggestions[key]);
  };

  if (initialLoading) {
    return (
      <div className="flex flex-col h-[calc(100vh-60px)] md:h-screen" data-testid="coach-page">
        <div className="p-6 md:p-8 border-b border-border">
          <div className="h-8 w-32 bg-muted rounded animate-pulse" />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-60px)] md:h-screen" data-testid="coach-page">
      {/* Header */}
      <div className="p-6 md:p-8 border-b border-border">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-heading text-2xl md:text-3xl uppercase tracking-tight font-bold mb-1">
              {t("coach.title")}
            </h1>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              {t("coach.subtitle")}
            </p>
          </div>
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClearHistory}
              data-testid="clear-history"
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Messages Area */}
      <ScrollArea ref={scrollRef} className="flex-1 p-6 md:p-8">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center py-12">
            <div className="max-w-md">
              <p className="font-mono text-sm text-muted-foreground mb-4">
                {t("coach.emptyState")}
              </p>
              <div className="space-y-2">
                <SuggestionButton 
                  onClick={() => handleSuggestion("trainingLoad")}
                  text={t("coach.suggestions.trainingLoad")}
                  testId="suggestion-training-load"
                />
                <SuggestionButton 
                  onClick={() => handleSuggestion("heartRate")}
                  text={t("coach.suggestions.heartRate")}
                  testId="suggestion-heart-rate"
                />
                <SuggestionButton 
                  onClick={() => handleSuggestion("paceConsistency")}
                  text={t("coach.suggestions.paceConsistency")}
                  testId="suggestion-pace-consistency"
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-6 pb-4">
            {messages.map((msg, idx) => (
              <div 
                key={idx} 
                className={`animate-in ${msg.role === "user" ? "text-right" : ""}`}
                data-testid={`message-${idx}`}
              >
                {msg.role === "user" ? (
                  <div className="inline-block text-left max-w-[85%] md:max-w-[70%]">
                    <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
                      {t("coach.you")}
                    </p>
                    <Card className="bg-muted border-border">
                      <CardContent className="p-4">
                        <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                        {msg.workout_id && (
                          <div className="mt-2 flex items-center gap-1 text-primary">
                            <Activity className="w-3 h-3" />
                            <span className="font-mono text-[10px] uppercase">
                              {t("coachExtended.workoutAnalyzed")}
                            </span>
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                ) : (
                  <div className="max-w-[85%] md:max-w-[70%]">
                    <p className="font-mono text-[10px] uppercase tracking-widest text-primary mb-2">
                      CardioCoach
                    </p>
                    <div className="coach-message">
                      <p className="text-sm whitespace-pre-wrap leading-relaxed">
                        {msg.content}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="animate-in">
                <p className="font-mono text-[10px] uppercase tracking-widest text-primary mb-2">
                  CardioCoach
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
      <div className="p-4 md:p-6 border-t border-border bg-background">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <Textarea
            data-testid="coach-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("coach.placeholder")}
            className="flex-1 min-h-[44px] max-h-[120px] resize-none bg-muted border-transparent focus:border-primary rounded-none font-mono text-sm"
            disabled={loading}
          />
          <Button
            type="submit"
            data-testid="coach-submit"
            disabled={!input.trim() || loading}
            className="bg-primary text-white hover:bg-primary/90 rounded-none uppercase font-bold tracking-wider text-xs h-11 px-6"
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
      onClick={onClick}
      data-testid={testId}
      className="block w-full p-3 text-left font-mono text-xs uppercase tracking-wider text-muted-foreground border border-border hover:border-primary/30 hover:text-foreground transition-colors"
    >
      {text}
    </button>
  );
}

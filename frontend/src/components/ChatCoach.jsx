import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { 
  MessageCircle, 
  Send, 
  Crown, 
  Loader2, 
  X, 
  Trash2,
  Zap
} from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

/**
 * ChatCoach - 100% Python Backend + RAG
 * Pas de LLM (ni local, ni cloud)
 * Réponses rapides (<1s), déterministes, ultra-naturelles
 */
const ChatCoach = ({ isOpen, onClose, userId = "default" }) => {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [subscriptionStatus, setSubscriptionStatus] = useState(null);
  const [checkingStatus, setCheckingStatus] = useState(true);
  const [currentSuggestions, setCurrentSuggestions] = useState([]);
  
  const messagesEndRef = useRef(null);

  // Check subscription on open
  useEffect(() => {
    if (isOpen) {
      checkSubscription();
      loadHistory();
    }
  }, [isOpen, userId]); // eslint-disable-line react-hooks/exhaustive-deps

  const checkSubscription = async () => {
    try {
      const res = await axios.get(`${API}/subscription/status?user_id=${userId}`);
      setSubscriptionStatus(res.data);
    } catch (err) {
      console.error("Error checking subscription:", err);
      setSubscriptionStatus({ tier: "free", messages_limit: 10, messages_remaining: 10 });
    } finally {
      setCheckingStatus(false);
    }
  };

  const loadHistory = async () => {
    try {
      const res = await axios.get(`${API}/chat/history?user_id=${userId}&limit=30`);
      setMessages(res.data || []);
    } catch (err) {
      console.error("Error loading history:", err);
    }
  };

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    setInput("");
    setLoading(true);

    // Add user message optimistically
    const tempUserMsg = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: userMessage,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, tempUserMsg]);

    try {
      // Send to Python backend (100% local, no LLM)
      const res = await axios.post(`${API}/chat/send`, {
        message: userMessage,
        user_id: userId,
        use_local_llm: false,
        language: lang
      });

      // Add assistant response with suggestions
      const assistantMsg = {
        id: res.data.message_id,
        role: "assistant",
        content: res.data.response,
        suggestions: res.data.suggestions || [],
        timestamp: new Date().toISOString()
      };
      setMessages(prev => [...prev, assistantMsg]);
      
      // Store current suggestions for display
      setCurrentSuggestions(res.data.suggestions || []);

      // Update remaining messages
      setSubscriptionStatus(prev => ({
        ...prev,
        messages_remaining: res.data.messages_remaining,
        messages_used: (prev?.messages_used || 0) + 1
      }));

    } catch (err) {
      console.error("Error sending message:", err);
      const errorMsg = err.response?.data?.detail || t("chat.connectionError");
      
      const errorResponse = {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: `⚠️ ${errorMsg}`,
        timestamp: new Date().toISOString(),
        isError: true
      };
      setMessages(prev => [...prev, errorResponse]);
    } finally {
      setLoading(false);
    }
  };

  const handleSuggestionClick = (suggestion) => {
    setInput(suggestion);
    // Optionally auto-send
    // setInput(suggestion);
    // setTimeout(() => handleSend(), 100);
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const clearHistory = async () => {
    try {
      await axios.delete(`${API}/chat/history?user_id=${userId}`);
      setMessages([]);
      setCurrentSuggestions([]);
    } catch (err) {
      console.error("Error clearing history:", err);
    }
  };

  if (!isOpen) return null;

  const canSendMessages = subscriptionStatus && subscriptionStatus.messages_remaining > 0;
  const tier = subscriptionStatus?.tier || "free";
  const tierName = subscriptionStatus?.tier_name || t("subscription.free");
  const isUnlimited = subscriptionStatus?.is_unlimited || false;
  const isPremium = tier !== "free";

  return (
    <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm" data-testid="chat-overlay">
      <div className="fixed right-0 top-0 h-full w-full sm:w-[420px] bg-background border-l border-border shadow-xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
              <MessageCircle className="w-4 h-4 text-primary" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-semibold text-sm">{t("chat.title")}</h2>
                {isPremium && (
                  <Badge className="text-[8px] bg-amber-500">{tierName}</Badge>
                )}
              </div>
              <p className="text-[10px] text-muted-foreground">
                {isUnlimited 
                  ? t("chat.unlimited") 
                  : `${subscriptionStatus?.messages_remaining || 0}/${subscriptionStatus?.messages_limit || 10} messages`
                }
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Status indicator - instant responses */}
            <div 
              className="flex items-center gap-1 px-2 py-1 rounded-full bg-green-500/10" 
              title={t("chat.instantResponsesTitle")}
            >
              <Zap className="w-3 h-3 text-green-500" />
              <span className="text-[9px] text-green-500">Instant</span>
            </div>
            {messages.length > 0 && (
              <Button 
                variant="ghost" 
                size="icon" 
                onClick={clearHistory}
                className="h-8 w-8"
                title={t("chat.clearHistory")}
              >
                <Trash2 className="w-4 h-4 text-muted-foreground" />
              </Button>
            )}
            <Button 
              variant="ghost" 
              size="icon" 
              onClick={onClose}
              className="h-8 w-8"
              data-testid="close-chat"
            >
              <X className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* Content */}
        {checkingStatus ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.length === 0 ? (
                <div className="text-center text-muted-foreground text-sm py-8">
                  <MessageCircle className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p>{t("chat.firstQuestion")}</p>
                  <p className="text-xs mt-1 text-muted-foreground/70">
                    {t("chat.examplePrompt")}
                  </p>
                  <div className="mt-4 p-3 bg-muted/50 rounded-lg text-xs">
                    <p className="flex items-center justify-center gap-1">
                      <Zap className="w-3 h-3 text-green-500" />
                      {t("chat.personalizedResponses")}
                    </p>
                  </div>
                  {/* Initial suggestions */}
                  <div className="mt-4 space-y-2">
                    {[t("chat.suggestion1"), t("chat.suggestion2"), t("chat.suggestion3")].map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="block w-full text-left px-3 py-2 text-xs bg-primary/5 hover:bg-primary/10 rounded-lg border border-primary/20 text-primary transition-colors"
                      >
                        💡 {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <>
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                          msg.role === "user"
                            ? "bg-primary text-primary-foreground rounded-br-sm"
                            : msg.isError
                            ? "bg-destructive/10 text-destructive rounded-bl-sm"
                            : "bg-muted rounded-bl-sm"
                        }`}
                      >
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                      </div>
                    </div>
                  ))}
                  
                  {/* Suggestions after last assistant message */}
                  {!loading && currentSuggestions.length > 0 && messages.length > 0 && messages[messages.length - 1]?.role === "assistant" && (
                    <div className="mt-2 space-y-1.5" data-testid="chat-suggestions">
                      <p className="text-[10px] text-muted-foreground font-mono uppercase tracking-wider mb-2">
                        💡 Suggestions
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {currentSuggestions.map((suggestion, idx) => (
                          <button
                            key={idx}
                            onClick={() => handleSuggestionClick(suggestion)}
                            className="text-left px-2.5 py-1.5 text-[11px] bg-primary/5 hover:bg-primary/10 rounded-full border border-primary/20 text-primary/90 hover:text-primary transition-all hover:scale-[1.02]"
                            data-testid={`suggestion-${idx}`}
                          >
                            {suggestion}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-muted rounded-2xl rounded-bl-sm px-4 py-3">
                    <div className="flex items-center gap-1">
                      <div className="w-2 h-2 bg-muted-foreground/50 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                      <div className="w-2 h-2 bg-muted-foreground/50 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                      <div className="w-2 h-2 bg-muted-foreground/50 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-4 border-t border-border bg-card">
              {/* Low messages warning */}
              {!isUnlimited && subscriptionStatus?.messages_remaining <= 3 && subscriptionStatus?.messages_remaining > 0 && (
                <p className="text-xs text-amber-500 mb-2 text-center">
                  ⚠️ Plus que {subscriptionStatus.messages_remaining} messages ce mois
                </p>
              )}
              
              {/* Limit reached */}
              {!canSendMessages ? (
                <div className="text-center py-2">
                  <p className="text-xs text-destructive mb-2">
                    Tu as atteint ta limite de {subscriptionStatus?.messages_limit} messages ce mois-ci.
                  </p>
                  <Button 
                    size="sm" 
                    onClick={() => { onClose(); navigate("/subscription"); }}
                    className="bg-gradient-to-r from-amber-500 to-orange-500"
                  >
                    <Crown className="w-3.5 h-3.5 mr-1" />
                    Passer au niveau supérieur
                  </Button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder={t("chat.placeholder")}
                    className="flex-1"
                    disabled={loading}
                    data-testid="chat-input"
                  />
                  <Button 
                    onClick={handleSend} 
                    disabled={loading || !input.trim()}
                    size="icon"
                    data-testid="send-btn"
                  >
                    {loading ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Send className="w-4 h-4" />
                    )}
                  </Button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ChatCoach;

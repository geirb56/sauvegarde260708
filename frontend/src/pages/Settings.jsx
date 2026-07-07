import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { Globe, Info, Loader2, Check, Target, Calendar, Trash2, Clock, Route, Crown, Sparkles, Dumbbell } from "lucide-react";
import { toast } from "sonner";
import { TerraConnection } from "@/components/TerraConnection";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default";

const DISTANCE_OPTIONS = ["5k", "10k", "semi", "marathon", "ultra"];
const DISTANCE_KM = {
  "5k": 5,
  "10k": 10,
  "semi": 21.1,
  "marathon": 42.195,
  "ultra": 50
};

// Options pour le plan d'entraînement
const TRAINING_GOAL_OPTIONS = [
  { value: "5K", label: "5 km" },
  { value: "10K", label: "10 km" },
  { value: "SEMI", label: "Semi-Marathon" },
  { value: "MARATHON", label: "Marathon" },
  { value: "ULTRA", label: "Ultra-Trail" },
];
const SESSIONS_OPTIONS = [3, 4, 5, 6];

export default function Settings() {
  const { t, lang, setLang } = useLanguage();
  const { 
    subscription, 
    isTrial, 
    isEarlyAdopter, 
    isFree, 
    trialDaysRemaining,
    refreshSubscription 
  } = useSubscription();
  const { unitSystem, setUnitSystem } = useUnitSystem();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Premium state
  const [processingPayment, setProcessingPayment] = useState(false);
  
  // Goal state
  const [goal, setGoal] = useState(null);
  const [loadingGoal, setLoadingGoal] = useState(true);
  const [eventName, setEventName] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [distanceType, setDistanceType] = useState("marathon");
  const [targetHours, setTargetHours] = useState("");
  const [targetMinutes, setTargetMinutes] = useState("");
  const [savingGoal, setSavingGoal] = useState(false);

  // Training Plan state
  const [trainingGoal, setTrainingGoal] = useState(null);
  const [sessionsPerWeek, setSessionsPerWeek] = useState(null);
  const [loadingTrainingPlan, setLoadingTrainingPlan] = useState(true);
  const [updatingTrainingPlan, setUpdatingTrainingPlan] = useState(false);

  useEffect(() => {
    loadGoal();
    loadPremiumStatus();
    loadTrainingPlan();
    
    // Handle Stripe callback
    const sessionId = searchParams.get("session_id");
    const premiumParam = searchParams.get("premium");
    const subscriptionParam = searchParams.get("subscription");
    
    if (sessionId && premiumParam === "success") {
      handlePaymentSuccess(sessionId, "premium");
    } else if (sessionId && subscriptionParam === "early_adopter_success") {
      handlePaymentSuccess(sessionId, "early_adopter");
    } else if (premiumParam === "cancelled" || subscriptionParam === "cancelled") {
      toast.info(t("settingsExtended.paymentCancelled"));
      setSearchParams({});
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadPremiumStatus = async () => {
    try {
      await axios.get(`${API}/premium/status?user_id=${USER_ID}`);
    } catch (error) {
      console.error("Failed to load premium status:", error);
    }
  };

  const loadTrainingPlan = async () => {
    try {
      const res = await axios.get(`${API}/training/full-cycle`, { 
        headers: { "X-User-Id": USER_ID } 
      });
      if (res.data) {
        setTrainingGoal(res.data.goal || "SEMI");
        setSessionsPerWeek(res.data.sessions_per_week || 4);
      }
    } catch (error) {
      console.error("Failed to load training plan:", error);
      // Defaults
      setTrainingGoal("SEMI");
      setSessionsPerWeek(4);
    } finally {
      setLoadingTrainingPlan(false);
    }
  };

  const handleSetTrainingGoal = async (goal) => {
    setUpdatingTrainingPlan(true);
    try {
      await axios.post(`${API}/training/set-goal?goal=${goal}`, {}, {
        headers: { "X-User-Id": USER_ID }
      });
      setTrainingGoal(goal);
      toast.success(t("settingsExtended.goalSetWithName").replace("{goal}", goal));
    } catch (err) {
      toast.error(t("common.error"));
    } finally {
      setUpdatingTrainingPlan(false);
    }
  };

  const handleSetSessionsPerWeek = async (sessions) => {
    setUpdatingTrainingPlan(true);
    try {
      await axios.post(`${API}/training/refresh?sessions=${sessions}`, {}, {
        headers: { "X-User-Id": USER_ID }
      });
      setSessionsPerWeek(sessions);
      toast.success(`${sessions} ${t("settingsExtended.sessionsPerWeekSet")}`);
    } catch (err) {
      toast.error(t("common.error"));
    } finally {
      setUpdatingTrainingPlan(false);
    }
  };

  const handlePaymentSuccess = async (sessionId, planType = "premium") => {
    setProcessingPayment(true);
    try {
      // Déterminer l'endpoint selon le type de plan
      const endpoint = planType === "early_adopter" 
        ? `${API}/subscription/verify-checkout/${sessionId}?user_id=${USER_ID}`
        : `${API}/premium/checkout/status/${sessionId}?user_id=${USER_ID}`;
      
      // Poll for payment completion
      let attempts = 0;
      const maxAttempts = 10;
      
      while (attempts < maxAttempts) {
        const res = await axios.get(endpoint);
        
        if (res.data.success || res.data.status === "completed" || res.data.status === "early_adopter" || res.data.payment_status === "paid") {
          const successMsg = planType === "early_adopter"
            ? `🎉 ${t("settingsExtended.earlyAdopterActivated")}`
            : `🎉 ${t("settingsExtended.premiumActivated")}`;
          
          toast.success(successMsg);
          
          // Rafraîchir le statut de l'abonnement
          if (planType === "early_adopter") {
            refreshSubscription();
          } else {
            loadPremiumStatus();
          }
          
          setSearchParams({});
          break;
        } else if (res.data.status === "expired" || res.data.error) {
          toast.error(t("settingsExtended.sessionExpiredOrError"));
          setSearchParams({});
          break;
        }
        
        await new Promise(r => setTimeout(r, 2000));
        attempts++;
      }
    } catch (error) {
      console.error("Payment verification error:", error);
      toast.error(t("settingsExtended.verificationError"));
    } finally {
      setProcessingPayment(false);
      setSearchParams({});
    }
  };

  const handleSubscribe = async () => {
    try {
      const res = await axios.post(`${API}/premium/checkout`, {
        origin_url: window.location.origin
      }, {
        params: { user_id: USER_ID }
      });
      
      window.location.href = res.data.checkout_url;
    } catch (error) {
      console.error("Checkout error:", error);
      toast.error(t("settingsExtended.paymentError"));
    }
  };

  const loadGoal = async () => {
    try {
      const res = await axios.get(`${API}/user/goal?user_id=${USER_ID}`);
      if (res.data) {
        setGoal(res.data);
        setEventName(res.data.event_name);
        setEventDate(res.data.event_date);
        setDistanceType(res.data.distance_type || "marathon");
        if (res.data.target_time_minutes) {
          setTargetHours(Math.floor(res.data.target_time_minutes / 60).toString());
          setTargetMinutes((res.data.target_time_minutes % 60).toString().padStart(2, "0"));
        }
      }
    } catch (error) {
      console.error("Failed to load goal:", error);
    } finally {
      setLoadingGoal(false);
    }
  };

  const handleSaveGoal = async () => {
    if (!eventName.trim() || !eventDate || !distanceType) {
      toast.error(t("settingsExtended.fillRequiredFields"));
      return;
    }
    
    // Calculate target time in minutes
    let targetTimeMinutes = null;
    if (targetHours || targetMinutes) {
      const hours = parseInt(targetHours) || 0;
      const mins = parseInt(targetMinutes) || 0;
      if (hours > 0 || mins > 0) {
        targetTimeMinutes = hours * 60 + mins;
      }
    }
    
    setSavingGoal(true);
    try {
      const res = await axios.post(`${API}/user/goal?user_id=${USER_ID}`, {
        event_name: eventName.trim(),
        event_date: eventDate,
        distance_type: distanceType,
        target_time_minutes: targetTimeMinutes
      });
      setGoal(res.data.goal);
      toast.success(t("settings.goalSaved"));
    } catch (error) {
      console.error("Failed to save goal:", error);
      toast.error(t("common.error"));
    } finally {
      setSavingGoal(false);
    }
  };

  const handleDeleteGoal = async () => {
    try {
      await axios.delete(`${API}/user/goal?user_id=${USER_ID}`);
      setGoal(null);
      setEventName("");
      setEventDate("");
      setDistanceType("marathon");
      setTargetHours("");
      setTargetMinutes("");
      toast.success(t("settings.goalDeleted"));
    } catch (error) {
      console.error("Failed to delete goal:", error);
      toast.error(t("common.error"));
    }
  };

  const formatLastSync = (isoString) => {
    if (!isoString) return t("common.never");
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    const locale = lang === "fr" ? "fr-FR" : "en-US";
    if (diffMins < 1) return t("common.justNow");
    if (diffMins < 60) return t("common.timeAgoMins").replace("{n}", diffMins);
    if (diffHours < 24) return t("common.timeAgoHours").replace("{n}", diffHours);
    if (diffDays < 7) return t("common.timeAgoDays").replace("{n}", diffDays);
    return date.toLocaleDateString(locale, { day: "numeric", month: "short" });
  };

  const calculateDaysUntil = (dateStr) => {
    if (!dateStr) return null;
    const eventDate = new Date(dateStr);
    const today = new Date();
    const diffTime = eventDate - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays > 0 ? diffDays : null;
  };

  const formatTargetTime = (minutes) => {
    if (!minutes) return null;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h${mins.toString().padStart(2, "0")}`;
  };

  const daysUntil = goal ? calculateDaysUntil(goal.event_date) : null;

  return (
    <div className="p-6 md:p-8 pb-24 md:pb-8" data-testid="settings-page">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-heading text-2xl md:text-3xl uppercase tracking-tight font-bold mb-1">
          {t("settings.title")}
        </h1>
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {t("settings.subtitle")}
        </p>
      </div>

      <div className="space-y-6">
        {/* Units Section */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Route className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settingsExtended.units")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settingsExtended.unitSystemDesc")}
                </p>

                <div className="flex flex-col sm:flex-row gap-3">
                  <button
                    type="button"
                    onClick={() => setUnitSystem("metric")}
                    className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider text-left transition-colors ${
                      unitSystem === "metric"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                    data-testid="units-metric"
                  >
                    <span className="block text-xs mb-1">
                      {t("settingsExtended.metric")}
                    </span>
                    <span className="block text-lg mb-1">km, min/km</span>
                    <span className="block text-[10px] uppercase text-muted-foreground">
                      km, km/h, m
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setUnitSystem("imperial")}
                    className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider text-left transition-colors ${
                      unitSystem === "imperial"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                    data-testid="units-imperial"
                  >
                    <span className="block text-xs mb-1">
                      {t("settingsExtended.imperial")}
                    </span>
                    <span className="block text-lg mb-1">mi, min/mi</span>
                    <span className="block text-[10px] uppercase text-muted-foreground">
                      mi, mph, ft
                    </span>
                  </button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Training Goal Section */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Target className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settings.goal")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settings.goalDesc")}
                </p>
                
                {loadingGoal ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="font-mono text-xs">{t("common.loading")}</span>
                  </div>
                ) : goal && daysUntil ? (
                  <div className="space-y-4">
                    {/* Current Goal Display */}
                    <div className="p-4 bg-primary/5 border border-primary/20 rounded-lg">
                      <div className="flex items-center justify-between mb-3">
                        <span className="font-mono text-sm font-semibold text-primary">
                          {goal.event_name}
                        </span>
                        <Button
                          onClick={handleDeleteGoal}
                          variant="ghost"
                          size="sm"
                          className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                      
                      {/* Goal Details Grid */}
                      <div className="grid grid-cols-2 gap-3 mb-3">
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Route className="w-4 h-4" />
                          <span className="font-mono text-xs">
                            {t(`settings.distances.${goal.distance_type}`)} ({goal.distance_km}km)
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Calendar className="w-4 h-4" />
                          <span className="font-mono text-xs">
                            {new Date(goal.event_date).toLocaleDateString(
                              lang === "fr" ? "fr-FR" : "en-US",
                              { day: "numeric", month: "short", year: "numeric" }
                            )}
                          </span>
                        </div>
                        {goal.target_time_minutes && (
                          <div className="flex items-center gap-2 text-muted-foreground">
                            <Clock className="w-4 h-4" />
                            <span className="font-mono text-xs">
                              {t("settings.targetTime")}: {formatTargetTime(goal.target_time_minutes)}
                            </span>
                          </div>
                        )}
                        {goal.target_pace && (
                          <div className="flex items-center gap-2 text-primary">
                            <Target className="w-4 h-4" />
                            <span className="font-mono text-xs font-semibold">
                              {t("settings.targetPace")}: {goal.target_pace}/km
                            </span>
                          </div>
                        )}
                      </div>
                      
                      {/* Days Until */}
                      <div className="pt-3 border-t border-primary/20">
                        <p className="font-mono text-2xl font-bold text-primary">
                          {daysUntil} <span className="text-sm font-normal">{t("settings.daysUntil")}</span>
                        </p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {/* Goal Form */}
                    <div className="space-y-3">
                      {/* Event Name */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.eventName")} *
                        </label>
                        <Input
                          value={eventName}
                          onChange={(e) => setEventName(e.target.value)}
                          placeholder={t("settingsExtended.placeholderGoalExample")}
                          className="bg-muted border-border font-mono text-sm"
                          data-testid="goal-name-input"
                        />
                      </div>
                      
                      {/* Distance Type */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.distance")} *
                        </label>
                        <Select value={distanceType} onValueChange={setDistanceType}>
                          <SelectTrigger className="bg-muted border-border font-mono text-sm" data-testid="goal-distance-select">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {DISTANCE_OPTIONS.map((dist) => (
                              <SelectItem key={dist} value={dist} className="font-mono text-sm">
                                {t(`settings.distances.${dist}`)} ({DISTANCE_KM[dist]}km)
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      
                      {/* Event Date */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.eventDate")} *
                        </label>
                        <Input
                          type="date"
                          value={eventDate}
                          onChange={(e) => setEventDate(e.target.value)}
                          min={new Date().toISOString().split('T')[0]}
                          className="bg-muted border-border font-mono text-sm"
                          data-testid="goal-date-input"
                        />
                      </div>
                      
                      {/* Target Time */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.targetTime")}
                        </label>
                        <p className="font-mono text-[9px] text-muted-foreground mb-2">
                          {t("settings.targetTimeDesc")}
                        </p>
                        <div className="flex items-center gap-2">
                          <Input
                            type="number"
                            min="0"
                            max="24"
                            value={targetHours}
                            onChange={(e) => setTargetHours(e.target.value)}
                            placeholder="0"
                            className="bg-muted border-border font-mono text-sm w-20 text-center"
                            data-testid="goal-hours-input"
                          />
                          <span className="font-mono text-sm text-muted-foreground">h</span>
                          <Input
                            type="number"
                            min="0"
                            max="59"
                            value={targetMinutes}
                            onChange={(e) => setTargetMinutes(e.target.value)}
                            placeholder="00"
                            className="bg-muted border-border font-mono text-sm w-20 text-center"
                            data-testid="goal-minutes-input"
                          />
                          <span className="font-mono text-sm text-muted-foreground">min</span>
                        </div>
                      </div>
                    </div>
                    
                    <Button
                      onClick={handleSaveGoal}
                      disabled={savingGoal || !eventName.trim() || !eventDate || !distanceType}
                      data-testid="save-goal"
                      className="bg-primary text-white hover:bg-primary/90 rounded-none uppercase font-bold tracking-wider text-xs h-9 px-4 flex items-center gap-2"
                    >
                      {savingGoal ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Check className="w-4 h-4" />
                      )}
                      {t("settings.saveGoal")}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Training Plan Section - Objectif & Séances/semaine */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Dumbbell className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settingsExtended.trainingPlan")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settingsExtended.trainingPlanDesc")}
                </p>
                <Button
                  variant="outline"
                  className="mb-4 uppercase text-xs tracking-wider"
                  onClick={() => navigate("/onboarding")}
                  data-testid="start-onboarding"
                >
                  Start onboarding
                </Button>
                
                {loadingTrainingPlan ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="font-mono text-xs">{t("common.loading")}</span>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {/* Objectif de distance */}
                    <div>
                      <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-2 block">
                        {t("settingsExtended.distanceGoal")}
                      </label>
                      <div className="flex flex-wrap gap-2">
                        {TRAINING_GOAL_OPTIONS.map((opt) => (
                          <button
                            key={opt.value}
                            onClick={() => handleSetTrainingGoal(opt.value)}
                            disabled={updatingTrainingPlan}
                            className={`px-3 py-2 rounded-lg text-xs font-bold transition-all ${
                              trainingGoal === opt.value 
                                ? "text-white" 
                                : "text-muted-foreground hover:text-foreground"
                            }`}
                            style={{
                              background: trainingGoal === opt.value 
                                ? "linear-gradient(135deg, #8b5cf6 0%, #a855f7 100%)" 
                                : "var(--muted)",
                              border: `1px solid ${trainingGoal === opt.value ? "#8b5cf6" : "var(--border)"}`
                            }}
                            data-testid={`training-goal-btn-${opt.value}`}
                          >
                            {updatingTrainingPlan && trainingGoal !== opt.value ? (
                              <span className="flex items-center gap-1">
                                {opt.label}
                              </span>
                            ) : (
                              opt.label
                            )}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Séances par semaine */}
                    <div>
                      <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-2 block">
                        {t("settingsExtended.sessionsPerWeekLabel")}
                      </label>
                      <div className="flex gap-2">
                        {SESSIONS_OPTIONS.map((num) => (
                          <button
                            key={num}
                            onClick={() => handleSetSessionsPerWeek(num)}
                            disabled={updatingTrainingPlan}
                            className={`w-12 h-12 rounded-lg text-sm font-bold transition-all ${
                              sessionsPerWeek === num 
                                ? "text-white" 
                                : "text-muted-foreground hover:text-foreground"
                            }`}
                            style={{
                              background: sessionsPerWeek === num 
                                ? "linear-gradient(135deg, #22c55e 0%, #16a34a 100%)" 
                                : "var(--muted)",
                              border: `1px solid ${sessionsPerWeek === num ? "#22c55e" : "var(--border)"}`
                            }}
                            data-testid={`sessions-per-week-btn-${num}`}
                          >
                            {num}
                          </button>
                        ))}
                      </div>
                      <p className="font-mono text-[10px] text-muted-foreground mt-2">
                        {t("settingsExtended.planRegenerated")}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
        {/* Terra Wearables Integration */}
        <TerraConnection lang={lang} t={t} />

        {/* Language Setting */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Globe className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settings.language")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settings.languageDesc")}
                </p>
                
                <div className="flex gap-3">
                  <button
                    onClick={() => setLang("en")}
                    data-testid="lang-en"
                    className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors ${
                      lang === "en"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    <span className="block text-lg mb-1">EN</span>
                    <span className="block text-xs">{t("settings.english")}</span>
                  </button>
                  
                  <button
                    onClick={() => setLang("fr")}
                    data-testid="lang-fr"
                    className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors ${
                      lang === "fr"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    <span className="block text-lg mb-1">FR</span>
                    <span className="block text-xs">{t("settings.french")}</span>
                  </button>

                  <button
                    onClick={() => setLang("es")}
                    data-testid="lang-es"
                    className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors ${
                      lang === "es"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    <span className="block text-lg mb-1">ES</span>
                    <span className="block text-xs">{t("settings.spanish")}</span>
                  </button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Subscription Status - Early Adopter System */}
        <Card className={`border-border ${
          isEarlyAdopter 
            ? "bg-gradient-to-br from-amber-500/10 to-orange-500/10 border-amber-500/30" 
            : isTrial 
              ? "bg-gradient-to-br from-blue-500/10 to-violet-500/10 border-blue-500/30"
              : "bg-card"
        }`}>
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className={`w-10 h-10 flex items-center justify-center flex-shrink-0 rounded-lg ${
                isEarlyAdopter 
                  ? "bg-gradient-to-br from-amber-500 to-orange-500" 
                  : isTrial
                    ? "bg-gradient-to-br from-blue-500 to-violet-500"
                    : "bg-muted border border-border"
              }`}>
                <Crown className={`w-5 h-5 ${(isEarlyAdopter || isTrial) ? "text-white" : "text-muted-foreground"}`} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h2 className="font-heading text-lg uppercase tracking-tight font-semibold">
                    {t("settingsExtended.subscription")}
                  </h2>
                  {isEarlyAdopter && (
                    <Badge className="bg-amber-500 text-white text-[9px]">{t("settingsExtended.earlyAdopterBadge")}</Badge>
                  )}
                  {isTrial && (
                    <Badge className="bg-blue-500 text-white text-[9px]">{t("settingsExtended.trialBadge")}</Badge>
                  )}
                  {isFree && (
                    <Badge className="bg-gray-500 text-white text-[9px]">{t("settingsExtended.limitedBadge")}</Badge>
                  )}
                </div>
                
                {/* Status Display */}
                <p className="font-mono text-sm text-foreground mb-1">
                  {isEarlyAdopter && t("settingsExtended.earlyAdopterPrice")}
                  {isTrial && t("settingsExtended.freeTrialActive")}
                  {isFree && t("settingsExtended.limitedAccess")}
                </p>
                
                {/* Trial countdown */}
                {isTrial && trialDaysRemaining !== null && (
                  <div className="mt-3 mb-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-mono text-xs text-muted-foreground">
                        {t("settingsExtended.timeRemaining")}
                      </span>
                      <span className="font-mono text-xs font-bold text-blue-400">
                        {trialDaysRemaining} {t("settingsExtended.days")}
                      </span>
                    </div>
                    <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-blue-500 to-violet-500 transition-all"
                        style={{ width: `${(trialDaysRemaining / 7) * 100}%` }}
                      />
                    </div>
                  </div>
                )}
                
                {/* Early Adopter benefits */}
                {isEarlyAdopter && (
                  <div className="mt-4 space-y-2">
                    <p className="font-mono text-xs text-muted-foreground mb-2">
                      {t("settingsExtended.featuresIncluded")}
                    </p>
                    <ul className="space-y-1.5">
                      {[
                        t("settingsExtended.personalizedPlan"),
                        t("settingsExtended.featureConversationalCoach"),
                        t("settingsExtended.smartAnalysis"),
                        t("settingsExtended.racePredictions")
                      ].map((feature, idx) => (
                        <li key={idx} className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Check className="w-3 h-3 text-amber-500" />
                          {feature}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                
                {/* Subscribe CTA for trial/free users */}
                {(isTrial || isFree) && (
                  <div className="mt-4 space-y-4">
                    <div className="p-4 rounded-lg" style={{ background: "rgba(251,191,36,0.1)", border: "1px solid rgba(251,191,36,0.2)" }}>
                      <div className="flex items-center gap-2 mb-2">
                        <Sparkles className="w-4 h-4 text-amber-400" />
                        <span className="font-bold text-amber-400">
                          {t("settingsExtended.earlyAdopterOffer")}
                        </span>
                      </div>
                      <p className="text-2xl font-bold text-white mb-1">4,99 € <span className="text-sm font-normal text-muted-foreground">/ {t("subscription.perMonth")}</span></p>
                      <p className="text-xs text-amber-300">{t("settingsExtended.priceGuaranteed")}</p>
                    </div>
                    
                    <ul className="space-y-2">
                      {[
                        t("settingsExtended.personalizedPlan"),
                        t("settingsExtended.unlimitedCoach"),
                        t("settingsExtended.smartAnalysis"),
                        t("settingsExtended.watchSync"),
                        t("settingsExtended.racePredictions")
                      ].map((feature, idx) => (
                        <li key={idx} className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Sparkles className="w-3 h-3 text-amber-500" />
                          {feature}
                        </li>
                      ))}
                    </ul>
                    
                    <Button
                      onClick={async () => {
                        setProcessingPayment(true);
                        try {
                          // Créer une session Stripe Checkout
                          const res = await axios.post(
                            `${API}/subscription/early-adopter/checkout?user_id=${USER_ID}&origin_url=${encodeURIComponent(window.location.origin)}`
                          );
                          
                          if (res.data?.checkout_url) {
                            // Rediriger vers Stripe Checkout
                            window.location.href = res.data.checkout_url;
                          } else {
                            toast.error(t("settingsExtended.paymentError"));
                            setProcessingPayment(false);
                          }
                        } catch (err) {
                          console.error("Checkout error:", err);
                          toast.error(t("settingsExtended.paymentError"));
                          setProcessingPayment(false);
                        }
                        // Note: pas de finally car on redirige vers Stripe
                      }}
                      disabled={processingPayment}
                      data-testid="subscribe-early-adopter"
                      className="w-full bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white rounded-lg uppercase font-bold tracking-wider text-sm h-12 flex items-center justify-center gap-2"
                    >
                      {processingPayment ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          {t("settingsExtended.redirecting")}
                        </>
                      ) : (
                        <>
                          <Crown className="w-4 h-4" />
                          {t("settingsExtended.activateCoach")}
                        </>
                      )}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* About */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Info className="w-5 h-5 text-muted-foreground" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settings.about")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settings.aboutDesc")}
                </p>
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  {t("settings.version")} 1.4.0
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

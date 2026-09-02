import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/context/AuthContext";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { useGarminSyncProgress } from "@/hooks/useGarminSyncProgress";
import { API_BASE_URL } from "@/config";
import { CheckCircle2, Crown, Dumbbell, Globe, Loader2, Mail, Route, ShieldCheck, Watch } from "lucide-react";
import { toast } from "sonner";

const API = API_BASE_URL;

const GOAL_OPTIONS = [
  { value: "5K", translationKey: "onboarding.goalLabels.5K", cycleValue: "5k", distanceType: "5k", hasRaceSettings: true },
  { value: "10K", translationKey: "onboarding.goalLabels.10K", cycleValue: "10k", distanceType: "10k", hasRaceSettings: true },
  { value: "SEMI", translationKey: "onboarding.goalLabels.SEMI", cycleValue: "half_marathon", distanceType: "semi", hasRaceSettings: true },
  { value: "MARATHON", translationKey: "onboarding.goalLabels.MARATHON", cycleValue: "marathon", distanceType: "marathon", hasRaceSettings: true },
  { value: "ULTRA", translationKey: "onboarding.goalLabels.ULTRA", cycleValue: "ultra", distanceType: "ultra", hasRaceSettings: true },
  { value: "MAINTENANCE", translationKey: "onboarding.goalLabels.MAINTENANCE", cycleValue: "maintenance", distanceType: null, hasRaceSettings: false },
];

const SUPPORTED_SESSION_VALUES = [3, 4, 5, 6];
const TERMINAL_SYNC_STATUSES = new Set(["complete", "partial_success", "failed"]);
const SUPPORTED_CYCLE_STATUSES = new Set(["active", "upcoming", "completed"]);

function normalizeCycleGoalToUi(goalType) {
  if (!goalType || typeof goalType !== "string") return null;
  const normalized = goalType.trim().toLowerCase();
  return GOAL_OPTIONS.find((option) => option.cycleValue === normalized)?.value || null;
}

function getGoalOption(goalValue) {
  return GOAL_OPTIONS.find((option) => option.value === goalValue) || null;
}

function parseDateInput(value) {
  if (!value || typeof value !== "string") return "";
  return value.split("T")[0];
}

function formatIsoDate(value, locale) {
  if (!value || typeof value !== "string") return null;
  const [year, month, day] = value.split("T")[0].split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}

function formatTargetTime(minutes) {
  if (!Number.isFinite(Number(minutes)) || Number(minutes) <= 0) return null;
  const totalMinutes = Number(minutes);
  const hours = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;
  if (hours <= 0) return `${mins} min`;
  return `${hours}h${String(mins).padStart(2, "0")}`;
}

function getTargetTimeParts(minutes) {
  if (!Number.isFinite(Number(minutes)) || Number(minutes) <= 0) {
    return { hours: "", minutes: "" };
  }
  const totalMinutes = Number(minutes);
  return {
    hours: String(Math.floor(totalMinutes / 60)),
    minutes: String(totalMinutes % 60).padStart(2, "0"),
  };
}

function getSubscriptionCode({ subscription, isTrial, isPremium }) {
  const raw = String(subscription?.status || "").trim().toLowerCase();
  if (raw === "premium") return "PREMIUM";
  if (raw === "trial") return "TRIAL";
  if (raw === "free") return "FREE";
  if (isPremium) return "PREMIUM";
  if (isTrial) return "TRIAL";
  return "FREE";
}

function getSubscriptionBadgeClass(code) {
  if (code === "PREMIUM") return "bg-amber-500 text-black";
  if (code === "TRIAL") return "bg-blue-500 text-white";
  return "bg-muted text-foreground";
}

function StatusMessage({ status, message, testId }) {
  if (!message) return null;

  const colorClass = status === "error"
    ? "text-destructive"
    : status === "saved"
      ? "text-emerald-400"
      : "text-muted-foreground";

  return (
    <p className={`text-xs ${colorClass}`} data-testid={testId}>
      {message}
    </p>
  );
}

function SectionCard({ icon: Icon, title, description, children, testId }) {
  return (
    <Card className="border-border bg-card" data-testid={testId}>
      <CardContent className="p-5 space-y-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-muted shrink-0">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-foreground">{title}</h2>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

function SettingRow({ label, value, helper, action, testId }) {
  return (
    <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid={testId}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
          <p className="mt-1 text-sm font-medium text-foreground break-words">{value}</p>
          {helper ? <p className="mt-1 text-xs text-muted-foreground">{helper}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </div>
  );
}

function getGarminSyncHelper(t, syncStatus) {
  if (!syncStatus || typeof syncStatus !== "object") return null;
  const status = typeof syncStatus.status === "string" ? syncStatus.status.trim() : "";
  const errorCode = syncStatus.error_code || syncStatus.error || null;
  const fetchStatus = syncStatus.daily_metrics_fetch_status || null;
  const metricsStatus = syncStatus.daily_metrics_status || null;

  if (status && !TERMINAL_SYNC_STATUSES.has(status)) {
    return t("settingsV2.garmin.syncInProgress");
  }
  if (errorCode === "session_unavailable") {
    return t("settingsV2.garmin.reconnectRequired");
  }
  if (errorCode === "daily_metrics_fetch_failed" || errorCode === "daily_metrics_7d_failed" || errorCode === "daily_metrics_enrichment_failed") {
    return t("settingsV2.garmin.dailyMetricsFetchError");
  }
  if (status === "complete" && fetchStatus === "partial_success") {
    return t("settingsV2.garmin.partialData");
  }
  if (metricsStatus === "no_usable_data" || fetchStatus === "success_no_data") {
    return t("settingsV2.garmin.noDataAvailableYet");
  }
  return null;
}

export default function Settings() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t, lang, setLang } = useLanguage();
  const {
    subscription,
    isTrial,
    isPremium,
    trialDaysRemaining,
    loading: subscriptionLoading,
    statusLabel,
    refreshSubscription,
  } = useSubscription();
  const { unitSystem, setUnitSystem } = useUnitSystem();

  const [planLoading, setPlanLoading] = useState(true);
  const [planError, setPlanError] = useState("");
  const [trainingGoal, setTrainingGoal] = useState(null);
  const [sessionsPerWeek, setSessionsPerWeek] = useState(null);
  const [planStartDate, setPlanStartDate] = useState(null);
  const [planStartDateDraft, setPlanStartDateDraft] = useState("");
  const [cycleStatus, setCycleStatus] = useState(null);
  const [userGoal, setUserGoal] = useState(null);
  const [goalForm, setGoalForm] = useState({ eventName: "", eventDate: "", targetHours: "", targetMinutes: "", ultraDistanceKm: "" });
  const [planAction, setPlanAction] = useState({ status: "idle", message: "" });
  // PR226: pending ultra distance — shown when ULTRA is the current or pending goal
  const [pendingUltraDistance, setPendingUltraDistance] = useState("");
  // PR226: shown when user clicks the ULTRA button so they can enter distance first
  const [showUltraDistanceInput, setShowUltraDistanceInput] = useState(false);

  const [garminLoading, setGarminLoading] = useState(true);
  const [garminError, setGarminError] = useState("");
  const [garminStatus, setGarminStatus] = useState(null);
  const [garminAction, setGarminAction] = useState({ status: "idle", message: "" });
  const [showReconnectForm, setShowReconnectForm] = useState(false);
  const [garminUsername, setGarminUsername] = useState("");
  const [garminPassword, setGarminPassword] = useState("");
  const [garminBusyAction, setGarminBusyAction] = useState("");

  const garminSyncStatusCode = typeof garminStatus?.sync_status?.status === "string"
    ? garminStatus.sync_status.status.trim()
    : "";
  const shouldStreamGarminProgress = Boolean(
    garminStatus?.connected
    && garminStatus?.sync_status
    && garminSyncStatusCode
    && !TERMINAL_SYNC_STATUSES.has(garminSyncStatusCode)
  );
  const { progress: garminProgress } = useGarminSyncProgress({ enabled: shouldStreamGarminProgress });

  const locale = lang === "fr" ? "fr-FR" : lang === "es" ? "es-ES" : "en-US";
  const selectedGoalOption = useMemo(() => getGoalOption(trainingGoal), [trainingGoal]);
  const effectiveGarminStatus = garminProgress || garminStatus?.sync_status || null;
  const garminSyncHelper = useMemo(
    () => getGarminSyncHelper(t, effectiveGarminStatus),
    [t, effectiveGarminStatus]
  );
  const subscriptionCode = getSubscriptionCode({ subscription, isTrial, isPremium });

  const loadPlanSettings = useCallback(async () => {
    setPlanLoading(true);
    setPlanError("");
    const [cycleV2Result, weekV2Result, userGoalResult] = await Promise.allSettled([
      axios.get(`${API}/training/v2/cycle`),
      axios.get(`${API}/training/v2/week`),
      axios.get(`${API}/user/goal`),
    ]);

    const nextError = cycleV2Result.status === "rejected" || weekV2Result.status === "rejected"
      ? "settingsV2.plan.loadError"
      : "";

    if (cycleV2Result.status === "fulfilled") {
      const cycleData = cycleV2Result.value.data;
      setTrainingGoal(normalizeCycleGoalToUi(cycleData?.goal?.goal_type));
      setPlanStartDate(cycleData?.cycle?.start_date || null);
      setPlanStartDateDraft(parseDateInput(cycleData?.cycle?.start_date || ""));
      setCycleStatus(cycleData?.cycle?.status || null);
    } else {
      setTrainingGoal(null);
      setPlanStartDate(null);
      setPlanStartDateDraft("");
      setCycleStatus(null);
    }

    if (weekV2Result.status === "fulfilled") {
      const sessionCount = weekV2Result.value.data?.weekly_target?.session_count;
      setSessionsPerWeek(SUPPORTED_SESSION_VALUES.includes(sessionCount) ? sessionCount : null);
    } else {
      setSessionsPerWeek(null);
    }

    if (userGoalResult.status === "fulfilled" && userGoalResult.value.data) {
      const loadedGoal = userGoalResult.value.data;
      const { hours, minutes } = getTargetTimeParts(loadedGoal.target_time_minutes);
      setUserGoal(loadedGoal);
      setGoalForm({
        eventName: loadedGoal.event_name || "",
        eventDate: parseDateInput(loadedGoal.event_date),
        targetHours: hours,
        targetMinutes: minutes,
        ultraDistanceKm: loadedGoal.distance_type === "ultra" ? String(loadedGoal.distance_km || "") : "",
      });
    } else {
      setUserGoal(null);
      setGoalForm({
        eventName: "",
        eventDate: "",
        targetHours: "",
        targetMinutes: "",
        ultraDistanceKm: "",
      });
    }

    setPlanError(nextError);
    setPlanLoading(false);
    return nextError === "";
  }, []);

  const loadGarminStatus = useCallback(async () => {
    setGarminLoading(true);
    setGarminError("");
    try {
      const res = await axios.get(`${API}/garmin/status`);
      setGarminStatus(res.data || null);
    } catch (error) {
      console.error("Failed to load Garmin status:", error);
      setGarminStatus(null);
      setGarminError("settingsV2.garmin.loadError");
    } finally {
      setGarminLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPlanSettings();
    loadGarminStatus();
  }, [loadGarminStatus, loadPlanSettings]);

  const handleSetTrainingGoal = async (goalValue) => {
    // PR226: ULTRA must have distance_km > 42.195 before calling set-goal.
    if (goalValue === "ULTRA") {
      const km = parseFloat(pendingUltraDistance);
      if (!(km > 42.195)) {
        // Reveal the distance input and show an inline prompt — do NOT call the API.
        setShowUltraDistanceInput(true);
        setPlanAction({ status: "error", message: t("settingsV2.plan.ultraDistanceError") });
        return;
      }
    } else {
      // Switching away from ULTRA: hide the distance input.
      setShowUltraDistanceInput(false);
    }

    setPlanAction({ status: "saving", message: t("settingsV2.common.saving") });
    try {
      const url =
        goalValue === "ULTRA"
          ? `${API}/training/set-goal?goal=${encodeURIComponent(goalValue)}&distance_km=${encodeURIComponent(pendingUltraDistance)}`
          : `${API}/training/set-goal?goal=${encodeURIComponent(goalValue)}`;
      await axios.post(url, {});
      if (goalValue === "ULTRA") setPendingUltraDistance("");
      const reloadSucceeded = await loadPlanSettings();
      if (!reloadSucceeded) {
        setPlanAction({ status: "error", message: t("settingsV2.plan.loadError") });
        toast.error(t("settingsV2.plan.loadError"));
        return;
      }
      setPlanAction({
        status: "saved",
        message: t("settingsV2.plan.goalUpdated").replace("{goal}", t(getGoalOption(goalValue)?.translationKey || "trainingV2.unknownGoal")),
      });
      toast.success(t("settingsV2.plan.goalUpdated").replace("{goal}", t(getGoalOption(goalValue)?.translationKey || "trainingV2.unknownGoal")));
    } catch (error) {
      console.error("Failed to update training goal:", error);
      setPlanAction({ status: "error", message: t("settingsV2.plan.goalUpdateError") });
      toast.error(t("settingsV2.plan.goalUpdateError"));
    }
  };

  const handleSetSessions = async (value) => {
    setPlanAction({ status: "saving", message: t("settingsV2.common.saving") });
    try {
      await axios.post(`${API}/training/refresh?sessions=${encodeURIComponent(value)}`, {});
      const reloadSucceeded = await loadPlanSettings();
      if (!reloadSucceeded) {
        setPlanAction({ status: "error", message: t("settingsV2.plan.loadError") });
        toast.error(t("settingsV2.plan.loadError"));
        return;
      }
      setPlanAction({
        status: "saved",
        message: t("settingsV2.plan.sessionsUpdated").replace("{count}", String(value)),
      });
      toast.success(t("settingsV2.plan.sessionsUpdated").replace("{count}", String(value)));
    } catch (error) {
      console.error("Failed to update sessions per week:", error);
      setPlanAction({ status: "error", message: t("settingsV2.plan.sessionsUpdateError") });
      toast.error(t("settingsV2.plan.sessionsUpdateError"));
    }
  };

  const handleSetPlanStartDate = async () => {
    if (!planStartDateDraft) {
      setPlanAction({ status: "error", message: t("settingsV2.plan.startDateRequired") });
      toast.error(t("settingsV2.plan.startDateRequired"));
      return;
    }

    setPlanAction({ status: "saving", message: t("settingsV2.common.saving") });
    try {
      await axios.post(`${API}/training/v2/cycle/start-date`, {
        start_date: planStartDateDraft,
      });
      const reloadSucceeded = await loadPlanSettings();
      if (!reloadSucceeded) {
        setPlanAction({ status: "error", message: t("settingsV2.plan.loadError") });
        toast.error(t("settingsV2.plan.loadError"));
        return;
      }
      setPlanAction({ status: "saved", message: t("settingsV2.plan.startDateUpdated") });
      toast.success(t("settingsV2.plan.startDateUpdated"));
    } catch (error) {
      console.error("Failed to update plan start date:", error);
      setPlanAction({ status: "error", message: t("settingsV2.plan.startDateUpdateError") });
      toast.error(t("settingsV2.plan.startDateUpdateError"));
    }
  };

  const handleGoalFormChange = (key, value) => {
    if (planAction.status !== "idle") {
      setPlanAction({ status: "idle", message: "" });
    }
    setGoalForm((current) => ({ ...current, [key]: value }));
  };

  const handleSaveRaceSettings = async () => {
    if (!selectedGoalOption?.hasRaceSettings) return;

    // PR226: ULTRA requires a valid distance > 42.195 km.
    if (selectedGoalOption.value === "ULTRA") {
      const ultraKm = parseFloat(goalForm.ultraDistanceKm);
      if (!(ultraKm > 42.195)) {
        setPlanAction({ status: "error", message: t("settingsV2.plan.ultraDistanceError") });
        toast.error(t("settingsV2.plan.ultraDistanceError"));
        return;
      }
    }

    const hours = parseInt(goalForm.targetHours || "0", 10) || 0;
    const minutes = parseInt(goalForm.targetMinutes || "0", 10) || 0;
    const totalMinutes = hours > 0 || minutes > 0 ? (hours * 60) + minutes : null;

    const payload = {
      event_name: goalForm.eventName.trim() || null,
      event_date: goalForm.eventDate || null,
      distance_type: selectedGoalOption.distanceType,
      target_time_minutes: totalMinutes,
    };
    if (selectedGoalOption.value === "ULTRA") {
      payload.distance_km = parseFloat(goalForm.ultraDistanceKm);
    }

    setPlanAction({ status: "saving", message: t("settingsV2.common.saving") });
    try {
      await axios.post(`${API}/user/goal`, payload);
      const reloadSucceeded = await loadPlanSettings();
      if (!reloadSucceeded) {
        setPlanAction({ status: "error", message: t("settingsV2.plan.loadError") });
        toast.error(t("settingsV2.plan.loadError"));
        return;
      }
      setPlanAction({ status: "saved", message: t("settingsV2.plan.raceSaved") });
      toast.success(t("settingsV2.plan.raceSaved"));
    } catch (error) {
      console.error("Failed to save race settings:", error);
      setPlanAction({ status: "error", message: t("settingsV2.plan.raceSaveError") });
      toast.error(t("settingsV2.plan.raceSaveError"));
    }
  };

  const handleConnectGarmin = async (event) => {
    event.preventDefault();

    if (!garminUsername.trim() || !garminPassword) {
      setGarminAction({ status: "error", message: t("onboarding.garminCredsRequired") });
      toast.error(t("onboarding.garminCredsRequired"));
      return;
    }

    setGarminBusyAction("connect");
    setGarminAction({ status: "saving", message: t("settingsV2.common.saving") });
    try {
      const res = await axios.post(`${API}/garmin/connect`, {
        garmin_username: garminUsername.trim(),
        garmin_password: garminPassword,
      });

      if (res.data?.status === "connected") {
        setGarminPassword("");
        setShowReconnectForm(false);
        await loadGarminStatus();
        await refreshSubscription();
        setGarminAction({ status: "saved", message: t("onboarding.garminConnected") });
        toast.success(t("onboarding.garminConnected"));
        return;
      }

      if (res.data?.status === "mfa_required") {
        setGarminPassword("");
        setGarminAction({ status: "error", message: t("onboarding.garminMfa") });
        toast.error(t("onboarding.garminMfa"));
        return;
      }

      setGarminAction({ status: "error", message: t("onboarding.garminFailed") });
      toast.error(t("onboarding.garminFailed"));
    } catch (error) {
      console.error("Failed to connect Garmin:", error);
      setGarminAction({ status: "error", message: t("onboarding.garminFailed") });
      toast.error(t("onboarding.garminFailed"));
    } finally {
      setGarminBusyAction("");
    }
  };

  const handleSyncGarmin = async () => {
    setGarminBusyAction("sync");
    setGarminAction({ status: "saving", message: t("settingsV2.garmin.syncing") });
    try {
      const res = await axios.post(`${API}/garmin/sync`, {});
      if (res.data?.status === "unavailable") {
        throw new Error(res.data?.detail || "sync unavailable");
      }
      await loadGarminStatus();
      setGarminAction({ status: "saved", message: t("settingsV2.garmin.syncQueued") });
      toast.success(t("settingsV2.garmin.syncQueued"));
    } catch (error) {
      console.error("Failed to start Garmin sync:", error);
      setGarminAction({ status: "error", message: t("onboarding.garminSyncFailed") });
      toast.error(t("onboarding.garminSyncFailed"));
    } finally {
      setGarminBusyAction("");
    }
  };

  const handleDisconnectGarmin = async () => {
    setGarminBusyAction("disconnect");
    setGarminAction({ status: "saving", message: t("settingsV2.common.saving") });
    try {
      await axios.post(`${API}/garmin/disconnect`, {});
      setGarminPassword("");
      setShowReconnectForm(false);
      await loadGarminStatus();
      setGarminAction({ status: "saved", message: t("settingsV2.garmin.disconnected") });
      toast.success(t("settingsV2.garmin.disconnected"));
    } catch (error) {
      console.error("Failed to disconnect Garmin:", error);
      setGarminAction({ status: "error", message: t("settingsV2.garmin.disconnectError") });
      toast.error(t("settingsV2.garmin.disconnectError"));
    } finally {
      setGarminBusyAction("");
    }
  };

  const currentGoalLabel = selectedGoalOption
    ? t(selectedGoalOption.translationKey)
    : t("settingsV2.common.missing");
  const currentSessionsLabel = sessionsPerWeek
    ? t("settingsV2.plan.sessionsValue").replace("{count}", String(sessionsPerWeek))
    : t("settingsV2.common.missing");
  const planStartLabel = planStartDate
    ? formatIsoDate(planStartDate, locale)
    : t("settingsV2.common.missing");
  const raceDateLabel = userGoal?.event_date
    ? formatIsoDate(userGoal.event_date, locale)
    : t("settingsV2.common.missing");
  const targetTimeLabel = userGoal?.target_time_minutes
    ? formatTargetTime(userGoal.target_time_minutes)
    : t("settingsV2.common.optional");
  const garminConnected = Boolean(garminStatus?.connected);
  const garminLastSyncLabel = garminStatus?.last_sync
    ? formatIsoDate(garminStatus.last_sync, locale)
    : t("settingsV2.garmin.never");
  const garminActivityCount = Number.isFinite(Number(garminStatus?.activity_count))
    ? String(garminStatus.activity_count)
    : "0";
  const showRaceForm = Boolean(selectedGoalOption?.hasRaceSettings);

  return (
    <div className="p-4 pb-24 md:p-6 md:pb-8" data-testid="settings-page">
      <div className="mx-auto max-w-4xl space-y-4">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">{t("settings.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("settingsV2.subtitle")}</p>
        </div>

        <SectionCard
          icon={Dumbbell}
          title={t("settingsV2.plan.title")}
          description={t("settingsV2.plan.description")}
          testId="settings-plan-section"
        >
          {planLoading ? (
            <div className="space-y-3" data-testid="settings-plan-loading">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </div>
          ) : planError ? (
            <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive" data-testid="settings-plan-error">
              {t(planError)}
            </div>
          ) : (
            <div className="space-y-4">
              <SettingRow
                label={t("settingsV2.plan.currentGoal")}
                value={currentGoalLabel}
                helper={cycleStatus && SUPPORTED_CYCLE_STATUSES.has(cycleStatus) ? t(`settingsV2.plan.statusValues.${cycleStatus}`) : null}
                testId="settings-current-goal"
              />

              <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid="settings-goal-options">
                <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{t("settingsV2.plan.changeGoal")}</p>
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {GOAL_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`rounded-xl border px-3 py-3 text-sm font-medium transition-colors ${
                        trainingGoal === option.value
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-card text-foreground hover:border-primary/40"
                      }`}
                      data-testid={`training-goal-btn-${option.value}`}
                      disabled={planAction.status === "saving"}
                      onClick={() => handleSetTrainingGoal(option.value)}
                    >
                      {t(option.translationKey)}
                    </button>
                  ))}
                </div>
                {/* PR226: ULTRA distance input — shown only when ULTRA is active or being selected */}
                {(trainingGoal === "ULTRA" || showUltraDistanceInput) && (
                <div className="mt-3 space-y-1" data-testid="settings-ultra-distance-block">
                  <label className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                    {t("settingsV2.plan.ultraDistanceLabel")}
                  </label>
                  <Input
                    type="number"
                    min="42.196"
                    step="0.1"
                    value={pendingUltraDistance}
                    onChange={(e) => { setPendingUltraDistance(e.target.value); if (planAction.status === "error") setPlanAction({ status: "idle", message: "" }); }}
                    placeholder={t("settingsV2.plan.ultraDistancePlaceholder")}
                    data-testid="settings-ultra-distance-pending-input"
                  />
                  <p className="text-xs text-muted-foreground">{t("settingsV2.plan.ultraDistanceHint")}</p>
                  {pendingUltraDistance && !(parseFloat(pendingUltraDistance) > 42.195) && (
                    <p className="text-xs text-destructive" data-testid="settings-ultra-distance-pending-error">
                      {t("settingsV2.plan.ultraDistanceError")}
                    </p>
                  )}
                </div>
                )}
              </div>

              <SettingRow
                label={t("settingsV2.plan.sessions")}
                value={currentSessionsLabel}
                helper={t("settingsV2.plan.sessionsHelp")}
                testId="settings-sessions-current"
              />

              <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid="settings-sessions-options">
                <div className="grid grid-cols-4 gap-2">
                  {SUPPORTED_SESSION_VALUES.map((value) => (
                    <button
                      key={value}
                      type="button"
                      className={`rounded-xl border px-3 py-3 text-sm font-semibold transition-colors ${
                        sessionsPerWeek === value
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-card text-foreground hover:border-primary/40"
                      }`}
                      data-testid={`sessions-per-week-btn-${value}`}
                      disabled={planAction.status === "saving"}
                      onClick={() => handleSetSessions(value)}
                    >
                      {value}
                    </button>
                  ))}
                </div>
              </div>

              <SettingRow
                label={t("settingsV2.plan.startDate")}
                value={planStartLabel}
                helper={t("settingsV2.plan.startDateHelp")}
                testId="settings-plan-start-date"
              />

              <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid="settings-plan-start-date-editor">
                <label
                  htmlFor="settings-plan-start-date-input"
                  className="mb-2 block text-xs uppercase tracking-[0.18em] text-muted-foreground"
                >
                  {t("settingsV2.plan.startDateLabel")}
                </label>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <Input
                    id="settings-plan-start-date-input"
                    type="date"
                    value={planStartDateDraft}
                    onChange={(event) => setPlanStartDateDraft(event.target.value)}
                    disabled={planAction.status === "saving"}
                    data-testid="plan-start-date-input"
                    className="sm:max-w-xs"
                  />
                  <Button
                    type="button"
                    disabled={planAction.status === "saving"}
                    onClick={handleSetPlanStartDate}
                    data-testid="save-plan-start-date"
                    className="w-full sm:w-auto"
                  >
                    {planAction.status === "saving" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    {t("settingsV2.plan.saveStartDate")}
                  </Button>
                </div>
              </div>

              {showRaceForm ? (
                <div className="space-y-4 rounded-xl border border-border bg-muted/30 p-4" data-testid="settings-race-fields">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{t("settingsV2.plan.raceSection")}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{t("settingsV2.plan.raceSectionHelp")}</p>
                  </div>

                  <SettingRow
                    label={t("settingsV2.plan.currentRaceDate")}
                    value={raceDateLabel}
                    helper={userGoal?.event_name || t("settingsV2.plan.raceDetailsMissing")}
                    testId="settings-race-date-current"
                  />

                  <div className="space-y-3">
                    <div>
                      <label htmlFor="settings-race-name" className="mb-1 block text-xs uppercase tracking-[0.18em] text-muted-foreground">
                        {t("settingsV2.plan.raceName")}
                      </label>
                      <Input
                        id="settings-race-name"
                        value={goalForm.eventName}
                        onChange={(event) => handleGoalFormChange("eventName", event.target.value)}
                        placeholder={t("settingsV2.plan.raceNamePlaceholder")}
                        data-testid="goal-name-input"
                      />
                    </div>

                    <div>
                      <label htmlFor="settings-race-date" className="mb-1 block text-xs uppercase tracking-[0.18em] text-muted-foreground">
                        {t("settingsV2.plan.raceDate")}
                      </label>
                      <Input
                        id="settings-race-date"
                        type="date"
                        value={goalForm.eventDate}
                        onChange={(event) => handleGoalFormChange("eventDate", event.target.value)}
                        data-testid="goal-date-input"
                      />
                    </div>

                    {selectedGoalOption?.value === "ULTRA" && (
                      <div>
                        <label htmlFor="settings-ultra-distance" className="mb-1 block text-xs uppercase tracking-[0.18em] text-muted-foreground">
                          {t("settingsV2.plan.ultraDistanceLabel")}
                        </label>
                        <Input
                          id="settings-ultra-distance"
                          type="number"
                          min="42.196"
                          step="0.1"
                          value={goalForm.ultraDistanceKm}
                          onChange={(event) => handleGoalFormChange("ultraDistanceKm", event.target.value)}
                          placeholder={t("settingsV2.plan.ultraDistancePlaceholder")}
                          data-testid="goal-ultra-distance-input"
                        />
                        {goalForm.ultraDistanceKm && !(parseFloat(goalForm.ultraDistanceKm) > 42.195) && (
                          <p className="mt-1 text-xs text-destructive" data-testid="goal-ultra-distance-error">
                            {t("settingsV2.plan.ultraDistanceError")}
                          </p>
                        )}
                      </div>
                    )}

                    <div>
                      <p className="mb-1 block text-xs uppercase tracking-[0.18em] text-muted-foreground">
                        {t("settingsV2.plan.targetTime")}
                      </p>
                      <p className="mb-2 text-xs text-muted-foreground">{t("settingsV2.plan.targetTimeHelp")}</p>
                      <div className="flex flex-wrap items-center gap-2">
                        <Input
                          type="number"
                          min="0"
                          max="24"
                          value={goalForm.targetHours}
                          onChange={(event) => handleGoalFormChange("targetHours", event.target.value)}
                          placeholder="0"
                          className="w-20"
                          data-testid="goal-hours-input"
                        />
                        <span className="text-sm text-muted-foreground">{t("settingsV2.plan.hoursShort")}</span>
                        <Input
                          type="number"
                          min="0"
                          max="59"
                          value={goalForm.targetMinutes}
                          onChange={(event) => handleGoalFormChange("targetMinutes", event.target.value)}
                          placeholder="00"
                          className="w-20"
                          data-testid="goal-minutes-input"
                        />
                        <span className="text-sm text-muted-foreground">{t("settingsV2.plan.minutesShort")}</span>
                      </div>
                      <p className="mt-2 text-sm font-medium text-foreground" data-testid="settings-current-target-time">
                        {t("settingsV2.plan.currentTargetTime")}: {targetTimeLabel}
                      </p>
                    </div>
                  </div>

                  <Button
                    type="button"
                    disabled={planAction.status === "saving"}
                    onClick={handleSaveRaceSettings}
                    data-testid="save-goal"
                    className="w-full sm:w-auto"
                  >
                    {planAction.status === "saving" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    {t("settingsV2.plan.saveRace")}
                  </Button>
                </div>
              ) : (
                <SettingRow
                  label={t("settingsV2.plan.raceSection")}
                  value={t("settingsV2.plan.maintenanceMode")}
                  helper={t("settingsV2.plan.maintenanceHelp")}
                  testId="settings-maintenance-note"
                />
              )}

              <StatusMessage
                status={planAction.status}
                message={planAction.message}
                testId="settings-plan-feedback"
              />
            </div>
          )}
        </SectionCard>

        <SectionCard
          icon={Watch}
          title={t("settingsV2.garmin.title")}
          description={t("settingsV2.garmin.description")}
          testId="settings-garmin-section"
        >
          {garminLoading ? (
            <div className="space-y-3" data-testid="settings-garmin-loading">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : garminError ? (
            <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive" data-testid="settings-garmin-error">
              {t(garminError)}
            </div>
          ) : (
            <div className="space-y-4">
              <SettingRow
                label={t("settingsV2.garmin.connection")}
                value={garminConnected ? t("settings.connected") : t("settings.notConnected")}
                helper={garminSyncHelper}
                testId="settings-garmin-status"
              />

              <div className="grid gap-3 sm:grid-cols-2">
                <SettingRow
                  label={t("settingsV2.garmin.lastSync")}
                  value={garminLastSyncLabel}
                  testId="settings-garmin-last-sync"
                />
                <SettingRow
                  label={t("settingsV2.garmin.activities")}
                  value={t("settingsV2.garmin.activitiesValue").replace("{count}", garminActivityCount)}
                  helper={effectiveGarminStatus?.activities_count !== undefined
                    ? t("settingsV2.garmin.syncedValue").replace("{count}", String(effectiveGarminStatus.activities_count))
                    : null}
                  testId="settings-garmin-activities"
                />
              </div>

              <div className="flex flex-col gap-2 sm:flex-row">
                {garminConnected ? (
                  <>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleSyncGarmin}
                      disabled={garminBusyAction !== ""}
                      data-testid="settings-garmin-sync"
                    >
                      {garminBusyAction === "sync" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                      {t("settingsV2.garmin.sync")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setShowReconnectForm((current) => !current)}
                      disabled={garminBusyAction !== ""}
                      data-testid="settings-garmin-reconnect-toggle"
                    >
                      {t("settingsV2.garmin.reconnect")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleDisconnectGarmin}
                      disabled={garminBusyAction !== ""}
                      data-testid="settings-garmin-disconnect"
                    >
                      {garminBusyAction === "disconnect" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                      {t("settings.disconnect")}
                    </Button>
                  </>
                ) : null}
              </div>

              {(!garminConnected || showReconnectForm) && (
                <form className="space-y-3 rounded-xl border border-border bg-muted/30 p-4" onSubmit={handleConnectGarmin} data-testid="settings-garmin-form">
                  <div>
                    <label htmlFor="settings-garmin-email" className="mb-1 block text-xs uppercase tracking-[0.18em] text-muted-foreground">
                      {t("settingsV2.garmin.email")}
                    </label>
                    <Input
                      id="settings-garmin-email"
                      type="email"
                      name="username"
                      autoComplete="section-garmin username"
                      value={garminUsername}
                      onChange={(event) => setGarminUsername(event.target.value)}
                      placeholder={t("onboarding.garminEmailPlaceholder")}
                      data-testid="garmin-email-input"
                    />
                  </div>

                  <div>
                    <label htmlFor="settings-garmin-password" className="mb-1 block text-xs uppercase tracking-[0.18em] text-muted-foreground">
                      {t("settingsV2.garmin.password")}
                    </label>
                    <Input
                      id="settings-garmin-password"
                      type="password"
                      name="password"
                      autoComplete="section-garmin current-password"
                      value={garminPassword}
                      onChange={(event) => setGarminPassword(event.target.value)}
                      placeholder={t("onboarding.garminPasswordPlaceholder")}
                      data-testid="garmin-password-input"
                    />
                  </div>

                  <Button
                    type="submit"
                    disabled={garminBusyAction !== ""}
                    data-testid="garmin-connect"
                    className="w-full sm:w-auto"
                  >
                    {garminBusyAction === "connect" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    {garminConnected ? t("settingsV2.garmin.reconnect") : t("settings.connect")}
                  </Button>
                </form>
              )}

              <StatusMessage
                status={garminAction.status}
                message={garminAction.message}
                testId="settings-garmin-feedback"
              />
            </div>
          )}
        </SectionCard>

        <SectionCard
          icon={Globe}
          title={t("settingsV2.preferences.title")}
          description={t("settingsV2.preferences.description")}
          testId="settings-preferences-section"
        >
          <SettingRow
            label={t("settings.language")}
            value={lang.toUpperCase()}
            helper={t("settingsV2.preferences.languageHelp")}
            testId="settings-language-current"
          />
          <div className="grid grid-cols-3 gap-2" data-testid="settings-language-options">
            {["en", "fr", "es"].map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setLang(value)}
                data-testid={`lang-${value}`}
                className={`rounded-xl border px-3 py-3 text-sm font-medium transition-colors ${
                  lang === value
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-foreground hover:border-primary/40"
                }`}
              >
                {value.toUpperCase()}
              </button>
            ))}
          </div>

          <SettingRow
            label={t("settingsV2.preferences.units")}
            value={unitSystem === "imperial" ? t("settingsExtended.imperial") : t("settingsExtended.metric")}
            helper={t("settingsExtended.unitSystemDesc")}
            testId="settings-units-current"
          />
          <div className="grid grid-cols-2 gap-2" data-testid="settings-units-options">
            {["metric", "imperial"].map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setUnitSystem(value)}
                data-testid={`units-${value}`}
                className={`rounded-xl border px-3 py-3 text-sm font-medium transition-colors ${
                  unitSystem === value
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-foreground hover:border-primary/40"
                }`}
              >
                {value === "imperial" ? t("settingsExtended.imperial") : t("settingsExtended.metric")}
              </button>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          icon={Crown}
          title={t("settingsV2.account.title")}
          description={t("settingsV2.account.description")}
          testId="settings-account-section"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <SettingRow
              label={t("settingsV2.account.email")}
              value={user?.email || t("settingsV2.common.missing")}
              action={<Mail className="h-4 w-4 text-muted-foreground" />}
              testId="settings-account-email"
            />
            <SettingRow
              label={t("settingsV2.account.subscription")}
              value={subscriptionLoading ? t("common.loading") : subscriptionCode}
              helper={statusLabel || null}
              action={subscriptionLoading ? null : <Badge className={getSubscriptionBadgeClass(subscriptionCode)} data-testid="settings-subscription-badge">{subscriptionCode}</Badge>}
              testId="settings-subscription-status"
            />
          </div>

          {subscriptionCode === "TRIAL" && trialDaysRemaining !== null ? (
            <SettingRow
              label={t("settingsV2.account.trial")}
              value={t("settingsV2.account.trialDays").replace("{count}", String(trialDaysRemaining))}
              testId="settings-subscription-trial"
            />
          ) : null}

          <SettingRow
            label={t("settingsV2.account.verification")}
            value={user?.is_email_verified ? t("settingsV2.account.verified") : t("settingsV2.account.unverified")}
            action={<ShieldCheck className="h-4 w-4 text-muted-foreground" />}
            testId="settings-account-verification"
          />

          <div className="flex flex-col gap-2 sm:flex-row">
            <Button type="button" onClick={() => navigate("/subscription")} data-testid="settings-manage-subscription">
              {t("settingsV2.account.manageSubscription")}
            </Button>
            <Button type="button" variant="outline" onClick={() => navigate("/training")} data-testid="settings-open-training">
              {t("settingsV2.account.openTraining")}
            </Button>
          </div>
        </SectionCard>

        <SectionCard
          icon={Route}
          title={t("settings.about")}
          description={t("settings.aboutDesc")}
          testId="settings-about-section"
        >
          <SettingRow
            label={t("settings.version")}
            value="1.4.0"
            testId="settings-version"
          />
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 p-4 text-sm text-emerald-300" data-testid="settings-no-password-note">
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{t("settingsV2.garmin.passwordSafety")}</span>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

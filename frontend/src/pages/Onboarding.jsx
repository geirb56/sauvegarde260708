import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, Check, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { API_BASE_URL } from "@/config";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useGarminSyncProgress } from "@/hooks/useGarminSyncProgress";

const API = API_BASE_URL;
const DONE_STEP_KEY = "done";

function SelectGrid({ options, value, onSelect, testIdPrefix }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {options.map((option) => {
        const isSelected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onSelect(option.value)}
            className={`rounded-xl border px-4 py-3 text-left transition-all min-h-[52px] ${
              isSelected
                ? "border-primary bg-primary/10 text-primary"
                : "border-border bg-card text-foreground"
            }`}
            data-testid={`${testIdPrefix}-${String(option.value).toLowerCase()}`}
          >
            <span className="font-semibold text-sm">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export default function Onboarding() {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const { refreshSubscription } = useSubscription();

  const [stepIndex, setStepIndex] = useState(0);
  const [goal, setGoal] = useState("");
  const [ultraDistanceKm, setUltraDistanceKm] = useState("");
  const [sessionsPerWeek, setSessionsPerWeek] = useState(null);
  const [savingPlan, setSavingPlan] = useState(false);
  const [planError, setPlanError] = useState("");

  const [garminStatus, setGarminStatus] = useState("idle"); // idle | connecting | connected | mfa_required | error
  const [garminUsername, setGarminUsername] = useState("");
  const [garminPassword, setGarminPassword] = useState("");
  const [garminCount, setGarminCount] = useState(0);
  const [garminSyncEnabled, setGarminSyncEnabled] = useState(false);

  const { progress: syncProgress, isStreaming: isSyncStreaming, error: syncError } = useGarminSyncProgress({
    enabled: garminSyncEnabled,
  });

  const steps = useMemo(
    () => [
      { key: "welcome", title: t("onboarding.steps.welcome") },
      { key: "garmin", title: t("onboarding.steps.garmin") },
      { key: "sync", title: t("onboarding.steps.sync") },
      { key: "firstValue", title: t("onboarding.steps.firstValue") },
      { key: "goal", title: t("onboarding.steps.goal") },
      { key: "sessions", title: t("onboarding.steps.sessions") },
      { key: DONE_STEP_KEY, title: t("onboarding.steps.done") },
    ],
    [t]
  );

  const goalOptions = useMemo(
    () => [
      { value: "5K", label: t("onboarding.goalLabels.5K") },
      { value: "10K", label: t("onboarding.goalLabels.10K") },
      { value: "SEMI", label: t("onboarding.goalLabels.SEMI") },
      { value: "MARATHON", label: t("onboarding.goalLabels.MARATHON") },
      { value: "ULTRA", label: t("onboarding.goalLabels.ULTRA") },
      { value: "MAINTENANCE", label: t("onboarding.goalLabels.MAINTENANCE") },
    ],
    [t]
  );

  const sessionOptions = useMemo(
    () => [3, 4, 5, 6].map((value) => ({ value, label: t("onboarding.sessionsOption").replace("{count}", value) })),
    [t]
  );

  const stepKey = steps[stepIndex]?.key;
  const isGarminConnected = garminStatus === "connected";

  const runIndexReady =
    syncProgress?.run_index_status === "ready" &&
    syncProgress?.run_index !== undefined &&
    syncProgress?.run_index !== null;
  const readinessReady =
    syncProgress?.readiness_status === "ready" &&
    syncProgress?.readiness !== undefined &&
    syncProgress?.readiness !== null;

  const terminalSync = syncProgress && ["complete", "partial_success", "failed"].includes(syncProgress.status);
  const insufficientData =
    syncProgress?.run_index_status === "insufficient_data" || (terminalSync && !runIndexReady && !syncError);
  const terminalError = Boolean(syncError) && !isSyncStreaming;
  const syncOutcomeKnown = runIndexReady || insufficientData || terminalError;
  const syncedCount = syncProgress?.activities_count ?? garminCount;

  const canContinue = useMemo(() => {
    if (stepKey === "welcome") return true;
    if (stepKey === "garmin") return isGarminConnected;
    if (stepKey === "sync") return syncOutcomeKnown;
    if (stepKey === "firstValue") return syncOutcomeKnown;
    if (stepKey === "goal") return Boolean(goal) && (goal !== "ULTRA" || (parseFloat(ultraDistanceKm) > 42.195));
    if (stepKey === "sessions") return Boolean(sessionsPerWeek) && !savingPlan;
    return false;
  }, [stepKey, isGarminConnected, syncOutcomeKnown, goal, ultraDistanceKm, sessionsPerWeek, savingPlan]);

  const connectGarmin = async () => {
    if (!garminUsername.trim() || !garminPassword) {
      setGarminStatus("error");
      toast.error(t("onboarding.garminCredsRequired"));
      return;
    }

    setGarminStatus("connecting");
    try {
      const res = await axios.post(`${API}/garmin/connect`, {
        garmin_username: garminUsername.trim(),
        garmin_password: garminPassword,
      });

      if (res.data?.status === "connected") {
        setGarminPassword("");
        await refreshSubscription();
        try {
          const syncRes = await axios.post(`${API}/garmin/sync`, {});
          setGarminCount(syncRes.data?.synced_count || 0);
        } catch {
          setGarminCount(0);
        }
        setGarminStatus("connected");
        setGarminSyncEnabled(true);
        toast.success(t("onboarding.garminConnected"));
        return;
      }

      if (res.data?.status === "mfa_required") {
        setGarminStatus("mfa_required");
        return;
      }

      setGarminStatus("error");
    } catch {
      setGarminStatus("error");
    }
  };

  const goNext = () => {
    if (stepIndex < steps.length - 1) setStepIndex((current) => current + 1);
  };

  const goBack = () => {
    if (stepIndex > 0) setStepIndex((current) => current - 1);
  };

  const createPlan = async () => {
    if (!goal || !sessionsPerWeek) return;
    if (goal === "ULTRA" && !(parseFloat(ultraDistanceKm) > 42.195)) return;

    setPlanError("");
    setSavingPlan(true);
    try {
      const setGoalUrl =
        goal === "ULTRA"
          ? `${API}/training/set-goal?goal=${encodeURIComponent(goal)}&distance_km=${encodeURIComponent(ultraDistanceKm)}`
          : `${API}/training/set-goal?goal=${encodeURIComponent(goal)}`;
      await axios.post(setGoalUrl, {});
      await axios.post(`${API}/training/refresh?sessions=${sessionsPerWeek}`, {});
      setStepIndex(steps.findIndex((s) => s.key === DONE_STEP_KEY));
    } catch {
      setPlanError(t("onboarding.planError"));
    } finally {
      setSavingPlan(false);
    }
  };

  const onContinue = () => {
    if (stepKey === "sessions") {
      createPlan();
      return;
    }
    goNext();
  };

  return (
    <div className="p-4 pb-24" data-testid="onboarding-page">
      <Card className="border-border bg-card">
        <CardContent className="p-5 space-y-5">
          <div className="flex items-center justify-between gap-3">
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              {t("onboarding.stepLabel").replace("{current}", stepIndex + 1).replace("{total}", steps.length)}
            </p>
            <p className="font-mono text-xs text-muted-foreground">{steps[stepIndex].title}</p>
          </div>

          {stepKey === "welcome" && (
            <div className="space-y-5 text-center" data-testid="onboarding-step-welcome">
              <img src="/runindex-logo.png" alt="RunIndex" className="h-12 w-auto mx-auto" data-testid="onboarding-logo" />
              <div className="space-y-1">
                <h1 className="text-3xl font-black tracking-tight">{t("onboarding.heroLine1")}</h1>
                <p className="text-lg font-semibold">{t("onboarding.heroLine2")}</p>
              </div>
              <Button onClick={goNext} className="w-full h-11" data-testid="onboarding-start">
                {t("onboarding.connectGarminCta")}
              </Button>
            </div>
          )}

          {stepKey === "garmin" && (
            <div className="space-y-4" data-testid="onboarding-step-garmin">
              <h2 className="text-lg font-semibold">{t("onboarding.connectGarminTitle")}</h2>
              <p className="text-sm text-muted-foreground">{t("onboarding.connectGarminHint")}</p>

              {isGarminConnected ? (
                <div className="rounded-xl border border-border bg-muted/20 p-4 space-y-2" data-testid="garmin-connected">
                  <div className="flex items-center gap-2 text-chart-2">
                    <Check className="w-4 h-4" />
                    <span className="font-semibold">{t("onboarding.garminConnected")}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">{t("onboarding.continueToSync")}</p>
                </div>
              ) : (
                <form
                  className="space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    connectGarmin();
                  }}
                >
                  <label htmlFor="garmin-connect-email" className="sr-only">
                    {t("onboarding.garminEmailPlaceholder")}
                  </label>
                  <Input
                    id="garmin-connect-email"
                    type="email"
                    name="username"
                    autoComplete="section-garmin username"
                    value={garminUsername}
                    onChange={(e) => setGarminUsername(e.target.value)}
                    placeholder={t("onboarding.garminEmailPlaceholder")}
                    data-testid="garmin-email-input"
                  />

                  <label htmlFor="garmin-connect-password" className="sr-only">
                    {t("onboarding.garminPasswordPlaceholder")}
                  </label>
                  <Input
                    id="garmin-connect-password"
                    type="password"
                    name="password"
                    autoComplete="section-garmin current-password"
                    value={garminPassword}
                    onChange={(e) => setGarminPassword(e.target.value)}
                    placeholder={t("onboarding.garminPasswordPlaceholder")}
                    data-testid="garmin-password-input"
                  />

                  <Button
                    type="submit"
                    className="w-full h-11"
                    disabled={garminStatus === "connecting"}
                    data-testid="garmin-connect"
                  >
                    {garminStatus === "connecting" ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                    {garminStatus === "connecting" ? t("onboarding.garminConnecting") : t("onboarding.connectGarminCta")}
                  </Button>
                </form>
              )}

              {garminStatus === "mfa_required" && (
                <div className="flex items-start gap-2 text-amber-500" data-testid="garmin-mfa">
                  <ShieldAlert className="w-4 h-4 mt-0.5" />
                  <p className="text-xs">{t("onboarding.garminMfa")}</p>
                </div>
              )}

              {garminStatus === "error" && (
                <p className="text-xs text-destructive" data-testid="garmin-error">
                  {t("onboarding.garminFailed")}
                </p>
              )}
            </div>
          )}

          {stepKey === "sync" && (
            <div className="space-y-4" data-testid="onboarding-step-sync">
              <h2 className="text-lg font-semibold">{t("onboarding.syncTitle")}</h2>

              <div className="rounded-xl border border-border bg-muted/20 p-4 space-y-2">
                <div className="flex items-center gap-2 text-chart-2" data-testid="sync-garmin-connected-row">
                  <Check className="w-4 h-4" />
                  <span>{t("onboarding.syncConnected")}</span>
                </div>

                {syncedCount > 0 && (
                  <p className="text-sm text-muted-foreground" data-testid="sync-activity-count">
                    {t("onboarding.syncActivitiesImported").replace("{count}", syncedCount)}
                  </p>
                )}

                {isSyncStreaming && (
                  <>
                    <p className="text-sm text-muted-foreground" data-testid="sync-analyzing-history">
                      {t("onboarding.syncAnalyzingHistory")}
                    </p>
                    <p className="text-sm text-muted-foreground" data-testid="sync-computing-runindex">
                      {t("onboarding.syncComputingRunIndex")}
                    </p>
                  </>
                )}

                {!isSyncStreaming && !syncError && !runIndexReady && (
                  <p className="text-sm text-muted-foreground" data-testid="sync-background-note">
                    {t("onboarding.syncBackground")}
                  </p>
                )}

                {syncError && (
                  <p className="text-sm text-destructive" data-testid="sync-error">
                    {t("onboarding.garminSyncFailed")}
                  </p>
                )}
              </div>
            </div>
          )}

          {stepKey === "firstValue" && (
            <div className="space-y-4" data-testid="onboarding-step-first-value">
              <h2 className="text-lg font-semibold">{t("onboarding.firstValueTitle")}</h2>

              {runIndexReady ? (
                <div className="rounded-xl border border-border bg-muted/20 p-5 text-center space-y-2" data-testid="runindex-first-value">
                  <p className="font-mono uppercase tracking-wider text-xs text-muted-foreground">{t("onboarding.runIndexLabel")}</p>
                  <p className="text-4xl font-black leading-none" data-testid="runindex-value">
                    {syncProgress.run_index} <span className="text-lg font-semibold text-muted-foreground">/ 1000</span>
                  </p>
                  <p className="text-sm text-muted-foreground">{t("onboarding.runIndexExplanation")}</p>
                </div>
              ) : terminalError ? (
                <div className="rounded-xl border border-border bg-muted/20 p-4" data-testid="runindex-terminal-error">
                  <p className="text-sm text-destructive">{t("onboarding.garminSyncFailed")}</p>
                </div>
              ) : insufficientData ? (
                <div className="rounded-xl border border-border bg-muted/20 p-4" data-testid="runindex-insufficient-data">
                  <p className="text-sm text-muted-foreground">{t("onboarding.insufficientData")}</p>
                </div>
              ) : (
                <div className="rounded-xl border border-border bg-muted/20 p-4" data-testid="runindex-pending">
                  <p className="text-sm text-muted-foreground">{t("onboarding.syncComputingRunIndex")}</p>
                </div>
              )}

              {readinessReady && (
                <div className="rounded-xl border border-border bg-muted/20 p-4" data-testid="readiness-optional">
                  <div className="flex items-center justify-between">
                    <p className="font-semibold">{t("onboarding.readinessTitle")}</p>
                    <p className="text-xl font-black">{syncProgress.readiness}</p>
                  </div>
                  <p className="text-sm text-muted-foreground">{t("onboarding.readinessOptional")}</p>
                </div>
              )}
            </div>
          )}

          {stepKey === "goal" && (
            <div className="space-y-3" data-testid="onboarding-step-goal">
              <h2 className="text-lg font-semibold">{t("onboarding.goalTitle")}</h2>
              <SelectGrid options={goalOptions} value={goal} onSelect={(v) => { setGoal(v); setUltraDistanceKm(""); }} testIdPrefix="onboarding-goal" />
              {goal === "ULTRA" && (
                <div className="space-y-1" data-testid="onboarding-ultra-distance-field">
                  <label className="text-sm font-medium">{t("onboarding.ultraDistanceLabel")}</label>
                  <input
                    type="number"
                    min="42.196"
                    step="0.1"
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                    placeholder={t("onboarding.ultraDistancePlaceholder")}
                    value={ultraDistanceKm}
                    onChange={(e) => setUltraDistanceKm(e.target.value)}
                    data-testid="onboarding-ultra-distance-input"
                  />
                  {ultraDistanceKm && !(parseFloat(ultraDistanceKm) > 42.195) && (
                    <p className="text-xs text-destructive" data-testid="onboarding-ultra-distance-error">
                      {t("onboarding.ultraDistanceError")}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {stepKey === "sessions" && (
            <div className="space-y-3" data-testid="onboarding-step-sessions">
              <h2 className="text-lg font-semibold">{t("onboarding.sessionsTitle")}</h2>
              <SelectGrid
                options={sessionOptions}
                value={sessionsPerWeek}
                onSelect={setSessionsPerWeek}
                testIdPrefix="onboarding-sessions"
              />

              {planError && <p className="text-sm text-destructive" data-testid="onboarding-plan-error">{planError}</p>}
            </div>
          )}

          {stepKey === DONE_STEP_KEY && (
            <div className="space-y-4 text-center" data-testid="onboarding-step-done">
              <h2 className="text-2xl font-black">{t("onboarding.doneTitle")}</h2>
              <p className="text-sm text-muted-foreground">{t("onboarding.doneSubtitle")}</p>
              <Button className="w-full h-11" onClick={() => navigate("/")} data-testid="onboarding-dashboard-cta">
                {t("onboarding.dashboardCta")}
              </Button>
            </div>
          )}

          {stepKey !== "welcome" && stepKey !== DONE_STEP_KEY && (
            <div className="flex items-center gap-2 pt-2">
              <Button variant="outline" onClick={goBack}>
                {t("onboarding.back")}
              </Button>
              <Button onClick={onContinue} disabled={!canContinue} className="ml-auto" data-testid="onboarding-continue">
                {stepKey === "sessions"
                  ? savingPlan
                    ? t("onboarding.creatingPlan")
                    : t("onboarding.createPlan")
                  : t("onboarding.continue")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, Check, ShieldAlert, Activity } from "lucide-react";
import { toast } from "sonner";

import { API_BASE_URL } from "@/config";
import { useLanguage } from "@/context/LanguageContext";
import { useGarminSyncProgress } from "@/hooks/useGarminSyncProgress";
const API = API_BASE_URL;

function OptionGrid({ options, value, onSelect, testIdPrefix }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {options.map((option) => (
        <button
          key={option}
          onClick={() => onSelect(option)}
          className={`text-left px-4 py-3 rounded-lg border transition-all font-mono text-sm ${
            value === option
              ? "border-primary bg-primary/10 text-primary"
              : "border-border bg-card text-foreground hover:border-primary/40"
          }`}
          data-testid={`${testIdPrefix}-${option.replace(/\s+/g, "-").toLowerCase()}`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

export default function Onboarding() {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [stepIndex, setStepIndex] = useState(0);
  const [fitnessLevel, setFitnessLevel] = useState("");
  const [goal, setGoal] = useState("");
  const [frequency, setFrequency] = useState("");
  const [device, setDevice] = useState("");
  const [target, setTarget] = useState("");
  const [physioData, setPhysioData] = useState(null);
  const [loadingPhysio, setLoadingPhysio] = useState(true);
  const [saving, setSaving] = useState(false);
  // Garmin connection — each user connects THEIR OWN Garmin account.
  // Credentials are sent once for the login, never stored client-side.
  const [garminStatus, setGarminStatus] = useState("idle"); // idle | connecting | connected | mfa_required | error
  const [garminCount, setGarminCount] = useState(0);
  const [garminEmail, setGarminEmail] = useState("");
  const [garminPassword, setGarminPassword] = useState("");
  const [garminSyncEnabled, setGarminSyncEnabled] = useState(false);

  const { progress: syncProgress, isStreaming: isSyncStreaming, error: syncError } = useGarminSyncProgress({ enabled: garminSyncEnabled });

  const runIndexReady = syncProgress?.run_index_status === "ready";
  const readinessReady = syncProgress?.readiness_status === "ready";
  const syncedCount = syncProgress?.synced_count ?? garminCount;

  const STEPS = useMemo(() => [
    { key: "welcome", title: t("onboarding.welcome") },
    { key: "fitness", title: t("onboarding.fitnessLevel") },
    { key: "goal", title: t("onboarding.goal") },
    { key: "frequency", title: t("onboarding.frequency") },
    { key: "device", title: t("onboarding.device") },
    { key: "target", title: t("onboarding.target") },
  ], [t]);

  const FITNESS_OPTIONS = [
    t("onboarding.fitnessOptions.beginner"),
    t("onboarding.fitnessOptions.intermediate"),
    t("onboarding.fitnessOptions.advanced"),
  ];
  const GOAL_OPTIONS = [
    t("onboarding.goalOptions.performance"),
    t("onboarding.goalOptions.fitness"),
    t("onboarding.goalOptions.weight"),
    t("onboarding.goalOptions.stress"),
  ];
  const FREQUENCY_OPTIONS = [
    t("onboarding.frequencyOptions.low"),
    t("onboarding.frequencyOptions.medium"),
    t("onboarding.frequencyOptions.high"),
  ];
  const DEVICE_OPTIONS = [
    t("onboarding.deviceOptions.appleHealth"),
    t("onboarding.deviceOptions.garmin"),
    t("onboarding.deviceOptions.whoop"),
    t("onboarding.deviceOptions.fitbit"),
  ];
  const TARGET_OPTIONS = ["5km", "10km", "semi", "marathon", "ultra trail"];

  const connectGarmin = async () => {
    if (!garminEmail.trim() || !garminPassword) {
      toast.error(t("onboarding.garminCredsRequired"));
      setGarminStatus("error");
      return;
    }
    setGarminStatus("connecting");
    try {
      const res = await axios.post(`${API}/garmin/connect`, {
        garmin_username: garminEmail.trim(),
        garmin_password: garminPassword,
      });
      if (res.data?.status === "connected") {
        // Clear the password from memory as soon as the login succeeds.
        setGarminPassword("");
        try {
          const sync = await axios.post(`${API}/garmin/sync`, {});
          setGarminCount(sync.data?.synced_count || 0);
        } catch (syncErr) {
          // connected but sync failed — still mark connected
          setGarminCount(0);
        }
        setGarminStatus("connected");
        setGarminSyncEnabled(true);
        toast.success(t("onboarding.garminConnectedToast"));
      } else if (res.data?.status === "mfa_required") {
        setGarminStatus("mfa_required");
      } else {
        setGarminStatus("error");
      }
    } catch (err) {
      setGarminStatus("error");
    }
  };

  useEffect(() => {
    const loadPhysio = async () => {
      setLoadingPhysio(true);
      try {
        const res = await axios.get(`${API}/run-index`);
        setPhysioData(res.data?.metrics || null);
      } catch (err) {
        setPhysioData(null);
      } finally {
        setLoadingPhysio(false);
      }
    };
    loadPhysio();
  }, []);

  const canContinue = useMemo(() => {
    const key = STEPS[stepIndex]?.key;
    if (key === "welcome") return true;
    if (key === "fitness") return Boolean(fitnessLevel);
    if (key === "goal") return Boolean(goal);
    if (key === "frequency") return Boolean(frequency);
    if (key === "device") return Boolean(device);
    if (key === "target") return Boolean(target);
    return false;
  }, [stepIndex, fitnessLevel, goal, frequency, device, target, STEPS]);

  const recommendation = useMemo(() => {
    if (!target || !fitnessLevel || !goal || !frequency) return null;

    const fatigueRatio = physioData?.fatigue_ratio ?? 1.0;
    const sleepHours = physioData?.sleep_hours;
    const intensity =
      fatigueRatio > 1.5 ? "recovery-focused intensity"
      : fatigueRatio > 1.2 ? "moderate intensity"
      : "performance intensity";

    return {
      title: `${fitnessLevel} plan for ${target}`,
      summary: `Based on your goal (${goal}) and frequency (${frequency}), start with ${intensity}.`,
      detail: `Physiology signal: fatigue ratio ${fatigueRatio}${sleepHours ? `, sleep ${sleepHours}h` : ""}.`,
    };
  }, [target, fitnessLevel, goal, frequency, physioData]);

  const handleNext = () => {
    if (stepIndex < STEPS.length - 1) {
      setStepIndex((prev) => prev + 1);
    }
  };

  const handleBack = () => {
    if (stepIndex > 0) {
      setStepIndex((prev) => prev - 1);
    }
  };

  const handleApplyPlan = async () => {
    if (!target || !frequency) return;
    const targetMap = {
      "5km": "5K",
      "10km": "10K",
      semi: "SEMI",
      marathon: "MARATHON",
      "ultra trail": "ULTRA",
    };
    const sessionsMap = {
      [t("onboarding.frequencyOptions.low")]: 2,
      [t("onboarding.frequencyOptions.medium")]: 4,
      [t("onboarding.frequencyOptions.high")]: 6,
    };

    setSaving(true);
    try {
      await axios.post(`${API}/training/set-goal?goal=${targetMap[target]}`, {});
      await axios.post(`${API}/training/refresh?sessions=${sessionsMap[frequency] || 4}`, {});
      toast.success(t("onboarding.planUpdated"));
      navigate("/training");
    } catch (err) {
      toast.error(t("onboarding.planError"));
    } finally {
      setSaving(false);
    }
  };

  const stepKey = STEPS[stepIndex].key;

  return (
    <div className="p-4 pb-24 space-y-4" data-testid="onboarding-page">
      <Card className="bg-card border-border">
        <CardContent className="p-6 space-y-5">
          <div className="flex items-center justify-between">
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              {t("onboarding.stepLabel").replace("{current}", stepIndex + 1).replace("{total}", STEPS.length)}
            </p>
            <p className="font-mono text-xs text-muted-foreground">{STEPS[stepIndex].title}</p>
          </div>

          {stepKey === "welcome" && (
            <div className="flex flex-col items-center text-center space-y-5">
              <img
                src="/runindex-logo.png"
                alt="RunIndex"
                className="h-12 w-auto"
                data-testid="onboarding-logo"
              />
              <h1 className="text-3xl font-black tracking-tight">{t("onboarding.tagline")}</h1>
              <Button
                onClick={handleNext}
                className="w-full bg-primary text-white font-bold uppercase tracking-wider"
                data-testid="onboarding-start"
              >
                {t("onboarding.startButton")}
              </Button>
            </div>
          )}

          {stepKey === "fitness" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">{t("onboarding.selectFitness")}</h2>
              <OptionGrid options={FITNESS_OPTIONS} value={fitnessLevel} onSelect={setFitnessLevel} testIdPrefix="fitness-option" />
            </div>
          )}

          {stepKey === "goal" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">{t("onboarding.selectGoal")}</h2>
              <OptionGrid options={GOAL_OPTIONS} value={goal} onSelect={setGoal} testIdPrefix="goal-option" />
            </div>
          )}

          {stepKey === "frequency" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">{t("onboarding.selectFrequency")}</h2>
              <OptionGrid options={FREQUENCY_OPTIONS} value={frequency} onSelect={setFrequency} testIdPrefix="frequency-option" />
            </div>
          )}

          {stepKey === "device" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">{t("onboarding.connectDevice")}</h2>
              <OptionGrid options={DEVICE_OPTIONS} value={device} onSelect={setDevice} testIdPrefix="device-option" />

              {device === t("onboarding.deviceOptions.garmin") && (
                <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3" data-testid="garmin-connect-panel">
                  {garminStatus === "connected" ? (
                    <div className="space-y-3" data-testid="garmin-sync-panel">
                      <div className="flex items-center gap-2 text-chart-2" data-testid="garmin-connected">
                        <Check className="w-4 h-4 flex-shrink-0" />
                        <span className="font-mono text-xs uppercase tracking-wider">
                          {t("onboarding.garminConnectedToast")}
                        </span>
                      </div>

                      {/* Phase 1: streaming, no RunIndex yet */}
                      {isSyncStreaming && !runIndexReady && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="garmin-syncing">
                          <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />
                          <span>{t("onboarding.garminSyncing")}</span>
                        </div>
                      )}

                      {/* Activity count once available */}
                      {syncedCount > 0 && (
                        <p className="font-mono text-xs text-muted-foreground" data-testid="garmin-activity-count">
                          {t("onboarding.garminActivitiesImported").replace("{count}", syncedCount)}
                        </p>
                      )}

                      {/* Phase 2: RunIndex ready */}
                      {runIndexReady && (
                        <div className="space-y-2" data-testid="garmin-runindex-panel">
                          <div className="flex items-center justify-between py-1 border-b border-border">
                            <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">RunIndex</span>
                            <span className="font-black text-lg" data-testid="garmin-runindex-value">{syncProgress.run_index ?? "—"}</span>
                          </div>

                          {/* Phase 3: Readiness ready */}
                          {readinessReady && (
                            <div className="flex items-center justify-between py-1 border-b border-border" data-testid="garmin-readiness-panel">
                              <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">Readiness</span>
                              <span className="font-black text-lg" data-testid="garmin-readiness-value">{syncProgress.readiness ?? "—"}</span>
                            </div>
                          )}

                          <Button
                            onClick={() => navigate("/dashboard")}
                            className="w-full bg-primary text-white font-bold uppercase tracking-wider text-xs h-9 mt-2"
                            data-testid="garmin-see-dashboard"
                          >
                            {t("onboarding.garminSeeDashboard")}
                          </Button>
                          <div className="text-center">
                            <a
                              href="/training"
                              className="font-mono text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                              data-testid="garmin-adjust-goal"
                            >
                              {t("onboarding.garminAdjustGoal")}
                            </a>
                          </div>
                        </div>
                      )}

                      {/* No usable data */}
                      {!isSyncStreaming && !runIndexReady && !syncError && syncProgress && (
                        <p className="font-mono text-xs text-muted-foreground" data-testid="garmin-no-data">
                          {t("onboarding.garminNoData")}
                        </p>
                      )}

                      {/* Sync error (auth errors are handled by the hook internally) */}
                      {syncError && !isSyncStreaming && (
                        <p className="font-mono text-xs text-destructive" data-testid="garmin-sync-error">
                          {t("onboarding.garminSyncFailed")}
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <p className="font-mono text-[11px] text-muted-foreground">
                        {t("onboarding.garminCredsHint")}
                      </p>
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
                          type="email"
                          name="username"
                          id="garmin-connect-email"
                          autoComplete="section-garmin username"
                          placeholder={t("onboarding.garminEmailPlaceholder")}
                          value={garminEmail}
                          onChange={(e) => setGarminEmail(e.target.value)}
                          data-testid="garmin-email-input"
                        />
                        <label htmlFor="garmin-connect-password" className="sr-only">
                          {t("onboarding.garminPasswordPlaceholder")}
                        </label>
                        <Input
                          type="password"
                          name="password"
                          id="garmin-connect-password"
                          autoComplete="section-garmin current-password"
                          placeholder={t("onboarding.garminPasswordPlaceholder")}
                          value={garminPassword}
                          onChange={(e) => setGarminPassword(e.target.value)}
                          data-testid="garmin-password-input"
                        />
                        <Button
                          type="submit"
                          disabled={garminStatus === "connecting"}
                          className="w-full bg-primary text-white font-bold uppercase tracking-wider text-xs h-9"
                          data-testid="garmin-connect"
                        >
                          {garminStatus === "connecting" ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Activity className="w-4 h-4" />
                          )}
                          {garminStatus === "connecting" ? t("onboarding.garminConnecting") : t("onboarding.garminConnect")}
                        </Button>
                      </form>
                      {garminStatus === "mfa_required" && (
                        <div className="flex items-start gap-2 text-amber-400" data-testid="garmin-mfa">
                          <ShieldAlert className="w-4 h-4 flex-shrink-0 mt-0.5" />
                          <span className="font-mono text-xs">{t("onboarding.garminMfa")}</span>
                        </div>
                      )}
                      {garminStatus === "error" && (
                        <p className="font-mono text-xs text-destructive" data-testid="garmin-error">
                          {t("onboarding.garminFailed")}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {stepKey === "target" && (
            <div className="space-y-4">
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">{t("onboarding.selectTarget")}</h2>
                <OptionGrid options={TARGET_OPTIONS} value={target} onSelect={setTarget} testIdPrefix="target-option" />
              </div>

              <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-2" data-testid="onboarding-recommendation">
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{t("onboarding.personalizedRec")}</p>
                {loadingPhysio ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t("onboarding.loadingPhysio")}
                  </div>
                ) : recommendation ? (
                  <>
                    <p className="font-semibold">{recommendation.title}</p>
                    <p className="text-sm text-muted-foreground">{recommendation.summary}</p>
                    <p className="text-xs text-muted-foreground">{recommendation.detail}</p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">{t("onboarding.completeSelections")}</p>
                )}
              </div>
            </div>
          )}

          {stepKey !== "welcome" && (
            <div className="flex items-center gap-2 pt-2">
              <Button variant="outline" onClick={handleBack} disabled={stepIndex === 0}>
                {t("onboarding.back")}
              </Button>
              {stepKey !== "target" ? (
                <Button onClick={handleNext} disabled={!canContinue} className="ml-auto">
                  {t("onboarding.continue")}
                </Button>
              ) : (
                <Button onClick={handleApplyPlan} disabled={!canContinue || saving} className="ml-auto" data-testid="apply-onboarding-plan">
                  {saving ? t("onboarding.saving") : t("onboarding.applyPlan")}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

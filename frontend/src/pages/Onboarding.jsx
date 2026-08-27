import { useState } from "react";
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

/**
 * PR203 — Onboarding UX V2
 *
 * New flow: welcome → garmin → sync → firstvalue → goal → params → done
 *
 * Goal business values are kept independent of the display language.
 * The set-goal endpoint accepts: 5K | 10K | SEMI | MARATHON | ULTRA
 *
 * NOTE — MAINTENANCE backend blocker (C203):
 *   /training/set-goal currently rejects "MAINTENANCE" (not in allowlist).
 *   MAINTENANCE is supported by the Training Engine V2 (GoalType.maintenance exists)
 *   but the allowlist in server.py:3453 must be extended. Until then, MAINTENANCE
 *   is not shown in the onboarding.
 *   See docs/reports/PR203_ONBOARDING_UX_V2.md §BLOCKERS.
 *
 * NOTE — Dates (C203):
 *   No dates are collected in onboarding. plan_start_date = TODAY (backend default).
 *   Race date and plan start date will be editable in Settings.
 */

// Stable backend values — NEVER translated.
// MAINTENANCE is intentionally absent until the backend allowlist is extended.
const GOAL_VALUES = ["5K", "10K", "SEMI", "MARATHON", "ULTRA"];
const STEPS = ["welcome", "garmin", "sync", "firstvalue", "goal", "params", "done"];

export default function Onboarding() {
  const { t } = useLanguage();
  const navigate = useNavigate();

  const [stepIndex, setStepIndex] = useState(0);
  const stepKey = STEPS[stepIndex];

  // Garmin connection state.
  // Each user connects THEIR OWN Garmin account.
  // Credentials are sent once to the backend and immediately cleared client-side.
  const [garminStatus, setGarminStatus] = useState("idle"); // idle | connecting | connected | mfa_required | error
  const [garminEmail, setGarminEmail] = useState("");
  const [garminPassword, setGarminPassword] = useState("");
  const [garminSyncEnabled, setGarminSyncEnabled] = useState(false);

  const { progress: syncProgress, isStreaming: isSyncStreaming, error: syncError } = useGarminSyncProgress({ enabled: garminSyncEnabled });

  const runIndexReady = syncProgress?.run_index_status === "ready";
  const readinessReady = syncProgress?.readiness_status === "ready";
  const syncedCount = syncProgress?.activities_count ?? 0;

  // Goal & plan params
  // Dates are NOT collected in onboarding. plan_start_date = TODAY (backend default).
  const [trainingGoal, setTrainingGoal] = useState("");
  const [sessionsPerWeek, setSessionsPerWeek] = useState(4);
  const [saving, setSaving] = useState(false);

  const goToStep = (key) => setStepIndex(STEPS.indexOf(key));

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
          await axios.post(`${API}/garmin/sync`, {});
        } catch (_) {
          // connected but sync failed — still proceed to sync step
        }
        setGarminStatus("connected");
        setGarminSyncEnabled(true);
        toast.success(t("onboarding.garminConnectedToast"));
        goToStep("sync");
      } else if (res.data?.status === "mfa_required") {
        setGarminStatus("mfa_required");
      } else {
        setGarminStatus("error");
      }
    } catch (_) {
      setGarminStatus("error");
    }
  };

  const handleCreatePlan = async () => {
    if (!trainingGoal) return;
    setSaving(true);
    try {
      await axios.post(`${API}/training/set-goal?goal=${trainingGoal}`, {});
      await axios.post(`${API}/training/refresh?sessions=${sessionsPerWeek}`, {});
      toast.success(t("onboarding.planUpdated"));
      goToStep("done");
    } catch (_) {
      toast.error(t("onboarding.planError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 pb-24 space-y-4" data-testid="onboarding-page">
      <Card className="bg-card border-border">
        <CardContent className="p-6 space-y-5">

          {/* ── WELCOME ── */}
          {stepKey === "welcome" && (
            <div className="flex flex-col items-center text-center space-y-5">
              <img
                src="/runindex-logo.png"
                alt="RunIndex"
                className="h-12 w-auto"
                data-testid="onboarding-logo"
              />
              <h1 className="text-3xl font-black tracking-tight whitespace-pre-line">
                {t("onboarding.tagline")}
              </h1>
              <Button
                onClick={() => goToStep("garmin")}
                className="w-full bg-primary text-white font-bold uppercase tracking-wider"
                data-testid="onboarding-start"
              >
                {t("onboarding.connectGarminCta")}
              </Button>
            </div>
          )}

          {/* ── GARMIN CONNECT ── */}
          {stepKey === "garmin" && (
            <div className="space-y-4" data-testid="garmin-connect-panel">
              <h2 className="text-lg font-semibold">{t("onboarding.garminConnect")}</h2>
              <p className="font-mono text-[11px] text-muted-foreground">
                {t("onboarding.garminCredsHint")}
              </p>
              <form
                className="space-y-3"
                onSubmit={(e) => { e.preventDefault(); connectGarmin(); }}
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
                  {garminStatus === "connecting"
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <Activity className="w-4 h-4" />}
                  {garminStatus === "connecting"
                    ? t("onboarding.garminConnecting")
                    : t("onboarding.garminConnect")}
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

          {/* ── SYNC / ANALYSIS ── */}
          {stepKey === "sync" && (
            <div className="space-y-4" data-testid="garmin-sync-panel">
              <div className="flex items-center gap-2 text-chart-2" data-testid="garmin-connected">
                <Check className="w-4 h-4 flex-shrink-0" />
                <span className="font-mono text-xs uppercase tracking-wider">
                  {t("onboarding.garminConnectedToast")}
                </span>
              </div>

              {isSyncStreaming && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="garmin-syncing">
                    <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />
                    <span>{t("onboarding.garminSyncing")}</span>
                  </div>
                  {!runIndexReady && (
                    <p className="font-mono text-xs text-muted-foreground">
                      {t("onboarding.syncComputingRunIndex")}
                    </p>
                  )}
                  {runIndexReady && !readinessReady && (
                    <p className="font-mono text-xs text-muted-foreground">
                      {t("onboarding.syncComputingReadiness")}
                    </p>
                  )}
                </div>
              )}

              {syncedCount > 0 && (
                <p className="font-mono text-xs text-muted-foreground" data-testid="garmin-activity-count">
                  {t("onboarding.garminActivitiesImported").replace("{count}", syncedCount)}
                </p>
              )}

              {syncError && !isSyncStreaming && (
                <p className="font-mono text-xs text-destructive" data-testid="garmin-sync-error">
                  {t("onboarding.garminSyncFailed")}
                </p>
              )}

              {/* Show Continue once sync has produced any result or errored */}
              {(runIndexReady || (!isSyncStreaming && syncProgress) || syncError) && (
                <Button
                  onClick={() => goToStep("firstvalue")}
                  className="w-full bg-primary text-white font-bold uppercase tracking-wider text-xs h-9"
                  data-testid="sync-continue"
                >
                  {t("onboarding.continue")}
                </Button>
              )}
            </div>
          )}

          {/* ── FIRST VALUE ── */}
          {stepKey === "firstvalue" && (
            <div className="space-y-4" data-testid="first-value-panel">
              {runIndexReady ? (
                <div className="space-y-3">
                  <div
                    className="flex items-center justify-between py-2 border-b border-border"
                    data-testid="garmin-runindex-panel"
                  >
                    <div>
                      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                        RunIndex
                      </p>
                      <p className="font-mono text-[10px] text-muted-foreground">
                        {t("onboarding.runIndexDescription")}
                      </p>
                    </div>
                    <span className="font-black text-2xl" data-testid="garmin-runindex-value">
                      {syncProgress.run_index ?? "—"}
                    </span>
                  </div>
                  {readinessReady && (
                    <div
                      className="flex items-center justify-between py-2 border-b border-border"
                      data-testid="garmin-readiness-panel"
                    >
                      <div>
                        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                          Readiness
                        </p>
                        <p className="font-mono text-[10px] text-muted-foreground">
                          {t("onboarding.readinessDescription")}
                        </p>
                      </div>
                      <span className="font-black text-2xl" data-testid="garmin-readiness-value">
                        {syncProgress.readiness ?? "—"}
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                <p className="font-mono text-xs text-muted-foreground" data-testid="garmin-no-data">
                  {t("onboarding.garminNoData")}
                </p>
              )}
              <Button
                onClick={() => goToStep("goal")}
                className="w-full bg-primary text-white font-bold uppercase tracking-wider text-xs h-9"
                data-testid="firstvalue-continue"
              >
                {t("onboarding.continue")}
              </Button>
            </div>
          )}

          {/* ── GOAL ── */}
          {stepKey === "goal" && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">{t("onboarding.goalTitle")}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {GOAL_VALUES.map((val) => (
                  <button
                    key={val}
                    onClick={() => setTrainingGoal(val)}
                    className={`text-left px-4 py-3 rounded-lg border transition-all font-mono text-sm ${
                      trainingGoal === val
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-card text-foreground hover:border-primary/40"
                    }`}
                    data-testid={`goal-option-${val.toLowerCase()}`}
                  >
                    {t(`onboarding.goalOptions.${val}`)}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2 pt-2">
                <Button variant="outline" onClick={() => goToStep("firstvalue")}>
                  {t("onboarding.back")}
                </Button>
                <Button
                  onClick={() => goToStep("params")}
                  disabled={!trainingGoal}
                  className="ml-auto"
                  data-testid="goal-continue"
                >
                  {t("onboarding.continue")}
                </Button>
              </div>
            </div>
          )}

          {/* ── PLAN PARAMETERS ── */}
          {stepKey === "params" && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">{t("onboarding.paramsTitle")}</h2>

              {/* Sessions per week */}
              <div className="space-y-2">
                <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {t("onboarding.sessionsPerWeek")}
                </p>
                <div className="flex gap-2">
                  {[3, 4, 5, 6].map((n) => (
                    <button
                      key={n}
                      onClick={() => setSessionsPerWeek(n)}
                      className={`flex-1 py-2 rounded-lg border font-mono text-sm transition-all ${
                        sessionsPerWeek === n
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-card text-foreground hover:border-primary/40"
                      }`}
                      data-testid={`sessions-option-${n}`}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>

              {/* Race date */}
              <div className="space-y-2">
                <label
                  htmlFor="onboarding-race-date"
                  className="font-mono text-xs uppercase tracking-wider text-muted-foreground"
                >
                  {t("onboarding.raceDate")}
                </label>
                <Input
                  type="date"
                  id="onboarding-race-date"
                  value={raceDate}
                  onChange={(e) => setRaceDate(e.target.value)}
                  data-testid="race-date-input"
                />
              </div>

              {/* Plan start date */}
              <div className="space-y-2">
                <label
                  htmlFor="onboarding-plan-start"
                  className="font-mono text-xs uppercase tracking-wider text-muted-foreground"
                >
                  {t("onboarding.planStartDate")}
                </label>
                <Input
                  type="date"
                  id="onboarding-plan-start"
                  value={planStartDate}
                  onChange={(e) => setPlanStartDate(e.target.value)}
                  data-testid="plan-start-date-input"
                />
              </div>

              <div className="flex items-center gap-2 pt-2">
                <Button variant="outline" onClick={() => goToStep("goal")}>
                  {t("onboarding.back")}
                </Button>
                <Button
                  onClick={handleCreatePlan}
                  disabled={saving}
                  className="ml-auto"
                  data-testid="apply-onboarding-plan"
                >
                  {saving ? t("onboarding.saving") : t("onboarding.createPlan")}
                </Button>
              </div>
            </div>
          )}

          {/* ── DONE ── */}
          {stepKey === "done" && (
            <div
              className="flex flex-col items-center text-center space-y-5"
              data-testid="onboarding-done"
            >
              <Check className="w-12 h-12 text-chart-2" />
              <p className="font-semibold">{t("onboarding.planUpdated")}</p>
              <Button
                onClick={() => navigate("/dashboard")}
                className="w-full bg-primary text-white font-bold uppercase tracking-wider"
                data-testid="garmin-see-dashboard"
              >
                {t("onboarding.garminSeeDashboard")}
              </Button>
            </div>
          )}

        </CardContent>
      </Card>
    </div>
  );
}

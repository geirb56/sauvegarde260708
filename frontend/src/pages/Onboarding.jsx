import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Check, ShieldAlert, Activity } from "lucide-react";
import { toast } from "sonner";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default";

const STEPS = [
  { key: "welcome", title: "Welcome" },
  { key: "fitness", title: "Fitness level" },
  { key: "goal", title: "Goal" },
  { key: "frequency", title: "Training frequency" },
  { key: "device", title: "Device connection" },
  { key: "target", title: "Training plan target" },
];

const FITNESS_OPTIONS = ["Beginner", "Intermediate", "Advanced"];
const GOAL_OPTIONS = [
  "Improve performance",
  "Get fitter / healthier",
  "Lose weight",
  "Reduce stress",
];
const FREQUENCY_OPTIONS = ["1–2 times/week", "3–4 times/week", "5+ times/week"];
const DEVICE_OPTIONS = ["Apple Health", "Garmin", "Whoop", "Fitbit"];
const TARGET_OPTIONS = ["5km", "10km", "semi", "marathon", "ultra trail"];

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
  // Garmin connection (invisible, OAuth-like — no password ever collected)
  const [garminStatus, setGarminStatus] = useState("idle"); // idle | connecting | connected | mfa_required | error
  const [garminCount, setGarminCount] = useState(0);

  const connectGarmin = async () => {
    setGarminStatus("connecting");
    try {
      const res = await axios.post(`${API}/garmin/connect?user_id=${USER_ID}`, {});
      if (res.data?.status === "connected") {
        try {
          const sync = await axios.post(`${API}/garmin/sync?user_id=${USER_ID}`, {});
          setGarminCount(sync.data?.synced_count || 0);
        } catch (syncErr) {
          // connected but sync failed — still mark connected
          setGarminCount(0);
        }
        setGarminStatus("connected");
        toast.success("Garmin connected");
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
        const res = await axios.get(`${API}/cardio-coach?user_id=${USER_ID}`);
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
  }, [stepIndex, fitnessLevel, goal, frequency, device, target]);

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
      "1–2 times/week": 2,
      "3–4 times/week": 4,
      "5+ times/week": 6,
    };

    setSaving(true);
    try {
      await axios.post(`${API}/training/set-goal?goal=${targetMap[target]}`, {}, {
        headers: { "X-User-Id": USER_ID },
      });
      await axios.post(`${API}/training/refresh?sessions=${sessionsMap[frequency]}`, {}, {
        headers: { "X-User-Id": USER_ID },
      });
      toast.success("Personalized plan updated");
      navigate("/training");
    } catch (err) {
      toast.error("Unable to save onboarding choices");
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
              Step {stepIndex + 1} / {STEPS.length}
            </p>
            <p className="font-mono text-xs text-muted-foreground">{STEPS[stepIndex].title}</p>
          </div>

          {stepKey === "welcome" && (
            <div className="space-y-4">
              <h1 className="text-3xl font-black tracking-tight">Turn your data into performance</h1>
              <Button
                onClick={handleNext}
                className="w-full bg-primary text-white font-bold uppercase tracking-wider"
                data-testid="onboarding-start"
              >
                Start my optimization
              </Button>
            </div>
          )}

          {stepKey === "fitness" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">Select your fitness level</h2>
              <OptionGrid options={FITNESS_OPTIONS} value={fitnessLevel} onSelect={setFitnessLevel} testIdPrefix="fitness-option" />
            </div>
          )}

          {stepKey === "goal" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">What's your primary goal?</h2>
              <OptionGrid options={GOAL_OPTIONS} value={goal} onSelect={setGoal} testIdPrefix="goal-option" />
            </div>
          )}

          {stepKey === "frequency" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">How often do you want to train?</h2>
              <OptionGrid options={FREQUENCY_OPTIONS} value={frequency} onSelect={setFrequency} testIdPrefix="frequency-option" />
            </div>
          )}

          {stepKey === "device" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">Connect your device</h2>
              <OptionGrid options={DEVICE_OPTIONS} value={device} onSelect={setDevice} testIdPrefix="device-option" />

              {device === "Garmin" && (
                <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3" data-testid="garmin-connect-panel">
                  {garminStatus === "connected" ? (
                    <div className="flex items-center gap-2 text-chart-2" data-testid="garmin-connected">
                      <Check className="w-4 h-4 flex-shrink-0" />
                      <span className="font-mono text-xs uppercase tracking-wider">
                        Garmin connected · {garminCount} activities synced
                      </span>
                    </div>
                  ) : garminStatus === "mfa_required" ? (
                    <div className="space-y-3" data-testid="garmin-mfa">
                      <div className="flex items-start gap-2 text-amber-400">
                        <ShieldAlert className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <span className="font-mono text-xs">
                          Additional verification was requested by Garmin. Please retry the connection.
                        </span>
                      </div>
                      <Button
                        onClick={connectGarmin}
                        className="w-full bg-primary text-white font-bold uppercase tracking-wider text-xs h-9"
                        data-testid="garmin-retry"
                      >
                        Retry connection
                      </Button>
                    </div>
                  ) : garminStatus === "error" ? (
                    <div className="space-y-3" data-testid="garmin-error">
                      <p className="font-mono text-xs text-destructive">
                        Garmin connection failed. Please try again.
                      </p>
                      <Button
                        onClick={connectGarmin}
                        className="w-full bg-primary text-white font-bold uppercase tracking-wider text-xs h-9"
                        data-testid="garmin-retry"
                      >
                        Try again
                      </Button>
                    </div>
                  ) : (
                    <Button
                      onClick={connectGarmin}
                      disabled={garminStatus === "connecting"}
                      className="w-full bg-primary text-white font-bold uppercase tracking-wider text-xs h-9"
                      data-testid="garmin-connect"
                    >
                      {garminStatus === "connecting" ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Activity className="w-4 h-4" />
                      )}
                      Connect Garmin
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}

          {stepKey === "target" && (
            <div className="space-y-4">
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">Select your training plan target</h2>
                <OptionGrid options={TARGET_OPTIONS} value={target} onSelect={setTarget} testIdPrefix="target-option" />
              </div>

              <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-2" data-testid="onboarding-recommendation">
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Personalized recommendation</p>
                {loadingPhysio ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading physiological data...
                  </div>
                ) : recommendation ? (
                  <>
                    <p className="font-semibold">{recommendation.title}</p>
                    <p className="text-sm text-muted-foreground">{recommendation.summary}</p>
                    <p className="text-xs text-muted-foreground">{recommendation.detail}</p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Complete selections to generate your recommendation.</p>
                )}
              </div>
            </div>
          )}

          {stepKey !== "welcome" && (
            <div className="flex items-center gap-2 pt-2">
              <Button variant="outline" onClick={handleBack} disabled={stepIndex === 0}>
                Back
              </Button>
              {stepKey !== "target" ? (
                <Button onClick={handleNext} disabled={!canContinue} className="ml-auto">
                  Continue
                </Button>
              ) : (
                <Button onClick={handleApplyPlan} disabled={!canContinue || saving} className="ml-auto" data-testid="apply-onboarding-plan">
                  {saving ? "Saving..." : "Apply my plan"}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

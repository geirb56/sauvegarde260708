import { formatPace } from "@/utils/units";

const isKnownNumber = (value) => typeof value === "number" && Number.isFinite(value);

export const formatStructuredDistance = (distanceM, unitSystem) => {
  if (!isKnownNumber(distanceM) || distanceM < 0) return null;
  if (unitSystem === "imperial") {
    const miles = distanceM / 1609.34;
    return miles < 0.5 ? `${Math.round(distanceM * 1.09361)} yd` : `${miles.toFixed(miles >= 10 ? 1 : 2)} mi`;
  }
  return distanceM < 1000 ? `${Math.round(distanceM)} m` : `${(distanceM / 1000).toFixed(distanceM >= 10000 ? 1 : 2)} km`;
};

export const formatStructuredDuration = (durationSeconds) => {
  if (!isKnownNumber(durationSeconds) || durationSeconds < 0) return null;
  const exactSeconds = Math.round(durationSeconds);
  if (exactSeconds < 60) return `${exactSeconds} s`;

  const hours = Math.floor(exactSeconds / 3600);
  const remainder = exactSeconds % 3600;
  const minutes = Math.floor(remainder / 60);
  const seconds = remainder % 60;

  if (hours > 0) {
    const minutePart = minutes > 0 ? ` ${String(minutes).padStart(2, "0")}` : "";
    const secondPart = seconds > 0 ? `:${String(seconds).padStart(2, "0")}` : "";
    return `${hours} h${minutePart}${secondPart}`;
  }
  if (seconds === 0) return `${minutes} min`;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
};

export const formatStructuredPace = (step, unitSystem) => {
  if (!step || typeof step !== "object") return null;
  const single = step.pace_min_per_km;
  if (isKnownNumber(single) && single > 0) return formatPace(single * 60, { unitSystem });

  const minimum = step.pace_min_per_km_min;
  const maximum = step.pace_min_per_km_max;
  if (isKnownNumber(minimum) && minimum > 0 && isKnownNumber(maximum) && maximum > 0) {
    const first = formatPace(minimum * 60, { unitSystem });
    const second = formatPace(maximum * 60, { unitSystem });
    const suffix = unitSystem === "imperial" ? "/mi" : "/km";
    return `${first.replace(` ${suffix}`, "")}–${second.replace(` ${suffix}`, "")} ${suffix}`;
  }
  return null;
};

const stepValue = (step, unitSystem) =>
  formatStructuredDistance(step?.distance_m, unitSystem)
  || formatStructuredDuration(step?.duration_seconds);

const recoveryValue = (recovery, unitSystem) =>
  isKnownNumber(recovery?.count) && recovery.count > 0
    ? formatStructuredDistance(recovery?.distance_m, unitSystem)
      || formatStructuredDuration(recovery?.duration_seconds)
    : null;

export const getPrimaryStructuredPace = (structured, unitSystem) => {
  const steps = Array.isArray(structured?.steps) ? structured.steps : [];
  const work = steps.find((step) => step?.step_type === "work")
    || steps.find((step) => step?.step_type === "continuous");
  return formatStructuredPace(work, unitSystem);
};

export const getStructuredSummary = (structured, unitSystem, t) => {
  const steps = Array.isArray(structured?.steps) ? structured.steps : [];
  const work = steps.find((step) => step?.step_type === "work");
  if (!work) return null;

  const parts = [];
  const value = stepValue(work, unitSystem);
  if (isKnownNumber(work.repetitions) && work.repetitions > 1) parts.push(`${work.repetitions} ×`);
  if (value) parts.push(value);

  const recovery = recoveryValue(work.recovery, unitSystem);
  if (recovery) {
    const count = isKnownNumber(work.recovery?.count) && work.recovery.count > 1
      ? `${work.recovery.count} × `
      : "";
    parts.push(`· ${count}${t("trainingV2.structured.recoveryShort")} ${recovery}`);
  }
  return parts.length ? parts.join(" ") : null;
};

export default function StructuredWorkoutView({ structured, unitSystem, t, compact = false }) {
  const steps = Array.isArray(structured?.steps) ? structured.steps : [];
  if (!structured || steps.length === 0) return null;

  if (compact) {
    const summary = getStructuredSummary(structured, unitSystem, t);
    return summary ? (
      <p className="text-xs leading-relaxed text-muted-foreground" data-testid="structured-workout-summary">
        {summary}
      </p>
    ) : null;
  }

  return (
    <div className="space-y-2" data-testid="structured-workout-view">
      {steps.map((step, index) => {
        const value = stepValue(step, unitSystem);
        const pace = formatStructuredPace(step, unitSystem);
        const repetitions = isKnownNumber(step?.repetitions) && step.repetitions > 1
          ? `${step.repetitions} × `
          : "";
        const recovery = recoveryValue(step?.recovery, unitSystem);
        const recoveryCount = isKnownNumber(step?.recovery?.count) && step.recovery.count > 1
          ? `${step.recovery.count} × `
          : "";
        const label = t(`trainingV2.structured.steps.${step?.step_type}`);

        return (
          <div
            key={`${step?.step_type || "step"}-${index}`}
            className="border-l-2 border-primary/40 pl-3"
            data-testid={`structured-step-${step?.step_type || "unknown"}`}
          >
            <p className="text-sm leading-relaxed">
              <span className="font-medium">{label}</span>
              {(value || pace) && <span className="text-muted-foreground"> · </span>}
              {value && <span>{repetitions}{value}</span>}
              {pace && <span className="text-muted-foreground">{value ? " · " : repetitions}{pace}</span>}
            </p>
            {recovery && (
              <p className="text-xs text-muted-foreground" data-testid="structured-recovery">
                {recoveryCount}{t("trainingV2.structured.recovery")} · {recovery}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

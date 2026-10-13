import { formatPace, formatSpeed } from "@/utils/units";

const WorkoutKilometerSplits = ({ splits, workoutType, unitSystem, t }) => {
  if (!Array.isArray(splits)) return null;
  const validSplits = splits.filter((split) =>
    Number.isFinite(split?.km)
    && split.km > 0
    && Number.isFinite(split?.pace_min_km)
    && split.pace_min_km > 0);
  if (validSplits.length === 0) return null;

  const cycling = ["cycle", "cycling", "ride"].includes(workoutType);

  return (
    <details className="min-w-0 rounded-xl border border-border bg-card/30 p-3" data-testid="kilometer-splits">
      <summary className="min-h-11 cursor-pointer text-sm font-medium">
        {t("workoutDetailExtended.recordedSplits")} · {validSplits.length}
      </summary>
      <ol className="mt-2 divide-y divide-border/50" aria-label={t("workoutDetailExtended.pacePerKm")}>
        {validSplits.map((split, index) => {
          const pace = cycling
            ? formatSpeed(60 / split.pace_min_km, { unitSystem })
            : formatPace(split.pace_min_km * 60, { unitSystem });
          return (
            <li
              className="flex min-h-10 min-w-0 items-center justify-between gap-3 py-1 text-sm"
              key={`${split.km}-${index}`}
              data-testid="kilometer-split-row"
            >
              <span>{t("workoutDetailExtended.kilometerNumber").replace("{number}", String(split.km))}</span>
              <span className="shrink-0 font-mono">{pace}</span>
              {Number.isFinite(split.avg_hr) && split.avg_hr > 0 && (
                <span className="shrink-0 text-muted-foreground">{Math.round(split.avg_hr)} bpm</span>
              )}
            </li>
          );
        })}
      </ol>
    </details>
  );
};

export default WorkoutKilometerSplits;

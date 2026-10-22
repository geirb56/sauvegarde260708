import { Card, CardContent } from "@/components/ui/card";
import { formatPaceDisplay, getRenderableAnalysisPhases } from "@/lib/workoutAnalysis";
import { formatAnalysisNumber } from "@/lib/analysisFormat";

const formatDuration = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const rounded = Math.round(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainingSeconds = rounded % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`
    : `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
};

const formatNumber = formatAnalysisNumber;

const sortPhases = (phases) => (Array.isArray(phases) ? phases : [])
  .map((phase, index) => ({ phase, index }))
  .sort((left, right) => {
    const leftOrder = Number.isFinite(left.phase?.order) ? left.phase.order : left.index;
    const rightOrder = Number.isFinite(right.phase?.order) ? right.phase.order : right.index;
    return leftOrder - rightOrder || left.index - right.index;
  })
  .map(({ phase }) => phase);

const getPhaseMetrics = (phase, t) => [
  Number.isFinite(phase?.duration_s) && phase.duration_s >= 0
    ? formatDuration(phase.duration_s)
    : null,
  Number.isFinite(phase?.pace_sec_per_km) && phase.pace_sec_per_km > 0
    ? formatPaceDisplay(phase.pace_sec_per_km / 60)
    : null,
  Number.isFinite(phase?.average_hr) && phase.average_hr > 0
    ? `${Math.round(phase.average_hr)} bpm`
    : null,
].filter(Boolean);

const WorkoutPhaseAnalysis = ({ phaseAnalysis, t, lang }) => {
  if (phaseAnalysis?.available !== true) return null;

  const phases = sortPhases(getRenderableAnalysisPhases(phaseAnalysis));
  if (phases.length === 0) return null;

  const efforts = phases.filter((phase) => phase?.phase_type === "effort");
  const recoveries = phases.filter((phase) => phase?.phase_type === "recovery");
  const statistics = phaseAnalysis.effort_statistics || {};
  const regularity = phaseAnalysis.effort_regularity || {};
  const rows = [];
  let effortNumber = 0;
  let recoveryNumber = 0;

  for (let index = 0; index < phases.length; index += 1) {
    const phase = phases[index];
    if (phase?.phase_type === "effort") {
      effortNumber += 1;
      const next = phases[index + 1];
      const followingRecovery = next?.phase_type === "recovery" ? next : null;
      if (followingRecovery) recoveryNumber += 1;
      rows.push({
        kind: "effort",
        phase,
        number: phase.effort_number ?? effortNumber,
        recovery: followingRecovery,
        recoveryNumber: followingRecovery?.recovery_number ?? recoveryNumber,
      });
      if (followingRecovery) index += 1;
    } else if (phase?.phase_type === "recovery") {
      recoveryNumber += 1;
      rows.push({
        kind: "recovery",
        phase,
        number: phase.recovery_number ?? recoveryNumber,
      });
    } else {
      rows.push({ kind: "other", phase });
    }
  }

  const hasStandardDeviation = Number.isFinite(regularity.pace_dispersion_sec_per_km)
    && regularity.pace_dispersion_sec_per_km >= 0;
  const regularityValue = hasStandardDeviation
    ? `${formatNumber(regularity.pace_dispersion_sec_per_km, lang)} s/km`
    : Number.isFinite(regularity.first_to_last_pace_change_sec_per_km)
      ? `${regularity.first_to_last_pace_change_sec_per_km > 0 ? "+" : ""}${formatNumber(regularity.first_to_last_pace_change_sec_per_km, lang)} s/km`
      : null;

  const renderRecovery = (phase, number) => {
    const duration = Number.isFinite(phase?.duration_s) && phase.duration_s >= 0
      ? formatDuration(phase.duration_s)
      : null;
    const metrics = getPhaseMetrics(phase, t).slice(duration === null ? 0 : 1);
    return (
      <details className="mt-1 rounded-md bg-muted/20 px-3 py-1" data-testid="phase-recovery-row">
        <summary className="min-h-9 cursor-pointer text-sm">
          {t("workoutDetailExtended.phaseRecoveryNumber").replace("{number}", String(number))}
          {duration ? ` · ${duration}` : ""}
        </summary>
        {metrics.length > 0 && <p className="pb-2 text-xs text-muted-foreground">{metrics.join(" · ")}</p>}
      </details>
    );
  };

  return (
    <section aria-labelledby="structured-phases-title" data-testid="structured-phase-analysis">
      <h2 id="structured-phases-title" className="mb-2 text-base font-semibold">
        {t("workoutDetailExtended.structuredPhases")}
      </h2>
      <Card className="border-border bg-card">
        <CardContent className="min-w-0 space-y-3 p-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm" data-testid="phase-summary">
            <span>{t("workoutDetailExtended.effortCount")}: {efforts.length}</span>
            <span>{t("workoutDetailExtended.recoveryCount")}: {recoveries.length}</span>
            {Number.isFinite(statistics.average_pace_sec_per_km) && statistics.average_pace_sec_per_km > 0 && (
              <span>{t("workoutDetailExtended.averageEffortPace")}: {formatPaceDisplay(statistics.average_pace_sec_per_km / 60)}</span>
            )}
            {regularity.available === true && regularityValue && (
              <span data-testid="effort-regularity">
                {t(hasStandardDeviation ? "workoutDetailExtended.paceDispersion" : "workoutDetailExtended.firstToLastPace")}: {regularityValue}
                {Number.isInteger(regularity.pace_sample_count) && regularity.pace_sample_count > 0
                  && Number.isInteger(regularity.effort_count) && regularity.effort_count >= regularity.pace_sample_count
                  && ` · ${regularity.pace_sample_count}/${regularity.effort_count} ${t("workoutNarrative.efforts")}`}
                {regularity.partial_comparison === true && ` · ${t("workoutDetailExtended.partialEffortComparison")}`}
              </span>
            )}
          </div>
          <ol className="min-w-0 space-y-1" data-testid="phase-rows">
            {rows.map((row, index) => {
              if (row.kind === "effort") {
                const metrics = getPhaseMetrics(row.phase, t);
                return (
                  <li key={`effort-${row.phase.order ?? index}`} className="border-b border-border/50 py-2 last:border-0" data-testid="phase-effort-row">
                    <p className="text-sm font-semibold">
                      {t("workoutDetailExtended.effortNumber").replace("{number}", String(row.number))}
                      {metrics.length > 0 && <span className="ml-2 font-normal text-muted-foreground">{metrics.join(" · ")}</span>}
                    </p>
                    {row.recovery && renderRecovery(row.recovery, row.recoveryNumber)}
                  </li>
                );
              }
              if (row.kind === "recovery") {
                return <li key={`recovery-${row.phase.order ?? index}`}>{renderRecovery(row.phase, row.number)}</li>;
              }
              const phaseLabel = row.phase?.phase_type === "warmup"
                ? t("workoutDetailExtended.phaseWarmup")
                : row.phase?.phase_type === "cooldown"
                  ? t("workoutDetailExtended.phaseCooldown")
                  : t("workoutDetailExtended.phaseOther");
              const metrics = getPhaseMetrics(row.phase, t);
              return (
                <li key={`phase-${row.phase?.order ?? index}`} className="py-1 text-sm" data-testid="phase-additional-row">
                  {phaseLabel}{metrics.length > 0 && <span className="ml-2 text-muted-foreground">{metrics.join(" · ")}</span>}
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>
    </section>
  );
};

export default WorkoutPhaseAnalysis;

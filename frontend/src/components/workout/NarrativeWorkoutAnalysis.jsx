import { formatAnalysisNumber, formatAnalysisDelta } from "@/lib/analysisFormat";

const hasText = (value) => typeof value === "string" && value.trim().length > 0;

export const getWorkoutNarrative = (data, lang) => {
  const narrative = data?.narrative_coach_v3;
  return narrative?.language === lang
    && ["deterministic_fallback", "llm_validated"].includes(narrative.generation_mode)
    && ["headline", "analysis", "interpretation"].every((field) => hasText(narrative[field]))
    ? narrative : null;
};

const classificationTypes = [
  "intervals", "easy_run_probable", "steady_run_probable",
  "tempo_probable", "long_run_probable", "unknown",
];
const reliable = (confidence) => ["high", "medium"].includes(confidence);

export default function NarrativeWorkoutAnalysis({ data, analysis, lang, t, children, detailsAvailable = true }) {
  const narrative = getWorkoutNarrative(data, lang);
  if (!narrative) return null;

  const facts = data?.workout_intelligence_v3?.version === "v3" ? data.workout_intelligence_v3 : null;
  const classification = facts?.session_classification;
  const intensity = facts?.intensity_assessment;
  const history = facts?.historical_comparison;
  const trend = facts?.performance_trend;
  const relative = classification?.relative_effort;
  const regularity = analysis?.phase_analysis?.available === true
    ? analysis.phase_analysis.effort_regularity : null;
  const text = (key) => t(`workoutNarrative.${key}`);
  const number = (value, precision = 1) => formatAnalysisNumber(value, lang, precision);
  const evidence = [];
  if (classificationTypes.includes(classification?.type)) {
    evidence.push(["type", text(classification.type)]);
  }
  const counts = classification?.evidence;
  if (classification?.type === "intervals"
    && Number.isInteger(counts?.effort_count) && counts.effort_count > 0
    && Number.isInteger(counts?.recovery_count) && counts.recovery_count >= 0) {
    evidence.push(["structure", `${number(counts.effort_count, 0)} ${text("efforts")} · ${number(counts.recovery_count, 0)} ${text("recoveries")}`]);
  }
  if (reliable(intensity?.confidence)
    && ["below_LT1", "between_LT1_LT2", "above_LT2"].includes(intensity.position)) {
    evidence.push(["intensity", text(intensity.position)]);
  }
  if (relative?.status === "used" && Number.isInteger(relative.reference_count) && relative.reference_count > 0) {
    evidence.push(["relativeHistory", `${number(relative.reference_count, 0)} ${text("referenceSessions")}`]);
  }
  if (history?.status === "available" && ["strong", "moderate"].includes(history.comparability)
    && Number.isInteger(history.reference_count) && history.reference_count > 0) {
    evidence.push(["history", `${number(history.reference_count, 0)} ${text("comparableSessions")}`]);
  } else if (history?.status === "insufficient") {
    evidence.push(["history", text("insufficientHistory")]);
  }
  if (reliable(trend?.confidence)
    && ["probable_improvement", "stable", "possible_decline"].includes(trend.status)) {
    evidence.push(["trend", text(trend.status)]);
  }
  if (classification?.type === "intervals" && regularity?.available === true
    && Number.isFinite(regularity.pace_dispersion_sec_per_km) && regularity.pace_dispersion_sec_per_km >= 0) {
    const sample = regularity.pace_sample_count;
    const total = regularity.effort_count;
    const cohort = Number.isInteger(sample) && Number.isInteger(total) && sample > 0 && total >= sample
      ? ` · ${number(sample, 0)}/${number(total, 0)} ${text("efforts")}` : "";
    evidence.push(["regularity", `${number(regularity.pace_dispersion_sec_per_km)} s/km${cohort}${regularity.partial_comparison === true ? ` · ${text("partialComparison")}` : ""}`]);
  }
  const limitations = [...new Set((Array.isArray(narrative.limitations) ? narrative.limitations : [])
    .filter(hasText))];
  const comparisonRows = [];
  if (history?.status === "available" && ["strong", "moderate"].includes(history.comparability)) {
    const pace = history.pace_at_comparable_hr;
    const hr = history.hr_at_comparable_pace;
    if (pace?.reference_count > 0 && Number.isFinite(pace.pace_difference_sec_per_km)) {
      comparisonRows.push(["paceAtHr", formatAnalysisDelta(pace.pace_difference_sec_per_km, lang, "s/km")]);
    }
    if (hr?.reference_count > 0 && Number.isFinite(hr.hr_difference_bpm)) {
      comparisonRows.push(["hrAtPace", formatAnalysisDelta(hr.hr_difference_bpm, lang, "bpm")]);
    }
  }

  return (
    <div className="min-w-0 space-y-4 break-words">
      <section className="space-y-3 rounded-xl border border-border bg-card p-4" data-testid="narrative-coach" aria-labelledby="narrative-coach-title">
        <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">{text("coach")}</p>
        <h2 id="narrative-coach-title" className="font-heading text-xl font-semibold leading-tight">{narrative.headline}</h2>
        <p className="text-sm leading-relaxed">{narrative.analysis}</p>
        <p className="text-sm leading-relaxed">{narrative.interpretation}</p>
        {hasText(narrative.recommendation) && <p className="text-sm leading-relaxed" data-testid="narrative-recommendation">{narrative.recommendation}</p>}
        {limitations.length > 0 && <p className="text-sm leading-relaxed text-muted-foreground" data-testid="narrative-limitation">{limitations[0]}</p>}
      </section>
      {evidence.length > 0 && <section aria-labelledby="workout-evidence-title" data-testid="workout-evidence">
        <h2 id="workout-evidence-title" className="mb-2 text-base font-semibold">{text("evidence")}</h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 border-y border-border py-3 sm:grid-cols-2">
          {evidence.map(([key, value]) => <div key={key} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{text(key)}</dt>
            <dd className="text-sm font-medium">{value}</dd>
          </div>)}
        </dl>
      </section>}
      {(detailsAvailable || comparisonRows.length > 0 || limitations.length > 1) && <details className="min-w-0 rounded-xl border border-border p-3" data-testid="workout-analysis-details">
        <summary className="min-h-11 cursor-pointer text-sm font-medium">{text("details")}</summary>
        <div className="space-y-4 pt-2">
          {children}
          {comparisonRows.length > 0 && <section data-testid="narrative-comparisons">
            <h3 className="mb-2 text-sm font-semibold">{text("history")}</h3>
            <dl className="space-y-2 text-sm">{comparisonRows.map(([key, value]) =>
              <div key={key}><dt className="text-muted-foreground">{text(key)}</dt><dd>{value}</dd></div>)}</dl>
          </section>}
          {limitations.length > 1 && <ul className="space-y-2 text-sm text-muted-foreground">
            {limitations.slice(1).map((item) => <li key={item}>{item}</li>)}
          </ul>}
        </div>
      </details>}
    </div>
  );
}

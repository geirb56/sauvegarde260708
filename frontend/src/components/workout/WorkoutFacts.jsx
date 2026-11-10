import { formatAnalysisNumber, formatAnalysisDelta } from "@/lib/analysisFormat";
import { mergeWorkoutLimitations, splitWorkoutLimitations } from "@/lib/workoutLimitations";

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

export const getWorkoutFacts = (data) =>
  (data?.workout_intelligence_v3?.version === "v3" ? data.workout_intelligence_v3 : null);


// C416: factual presentation only. The narrative prose (headline, analysis, interpretation,
// recommendation) and the coach comment stay in the backend contracts and are interpreted in the Coach chat.
// C417: compact "markers" (max 3), one essential limitation, the Coach action, then a details section.
// `synthesis` carries the already validated V2 items/limitations; it is never recomputed here.
export default function WorkoutFacts({ data, lang, t, children, detailsAvailable = true, synthesis = null, action = null }) {
  const narrative = getWorkoutNarrative(data, lang);
  const facts = getWorkoutFacts(data);
  const synthesisItems = Array.isArray(synthesis?.items) ? synthesis.items : [];
  const synthesisLimitations = Array.isArray(synthesis?.limitations) ? synthesis.limitations : [];
  if (!facts && !narrative && synthesisItems.length === 0 && synthesisLimitations.length === 0) return null;

  const classification = facts?.session_classification;
  const intensity = facts?.intensity_assessment;
  const history = facts?.historical_comparison;
  const relative = classification?.relative_effort;
  const text = (key) => t(`workoutNarrative.${key}`);
  const number = (value, precision = 1) => formatAnalysisNumber(value, lang, precision);
  const markers = [];
  const counts = classification?.evidence;
  if (classification?.type === "intervals"
    && Number.isInteger(counts?.effort_count) && counts.effort_count > 0
    && Number.isInteger(counts?.recovery_count) && counts.recovery_count >= 0) {
    markers.push(["structure", text("structure"), `${number(counts.effort_count, 0)} ${text("efforts")} · ${number(counts.recovery_count, 0)} ${text("recoveries")}`]);
  } else if (classificationTypes.includes(classification?.type) && classification.type !== "unknown") {
    markers.push(["type", text("type"), text(classification.type)]);
  }
  synthesisItems.forEach((item) => markers.push([`synthesis:${item.code}`, null, item.text]));
  if (reliable(intensity?.confidence)
    && ["below_LT1", "between_LT1_LT2", "above_LT2"].includes(intensity.position)) {
    markers.push(["intensity", text("intensity"), text(intensity.position)]);
  }
  // An undetermined type is only worth a line when nothing else is known.
  if (markers.length === 0 && classification?.type === "unknown") {
    markers.push(["type", text("type"), text("unknown")]);
  }
  const shownMarkers = markers.slice(0, 3);
  const otherMarkers = markers.slice(3);

  // Each reference population keeps its own method; counts are never merged or compared.
  const referenceRows = [];
  if (relative?.status === "used" && Number.isInteger(relative.reference_count) && relative.reference_count > 0) {
    referenceRows.push(["relativeHistory", text("relativeHistory"), `${number(relative.reference_count, 0)} ${text("referenceSessions")}`]);
  }
  if (history?.status === "available" && ["strong", "moderate"].includes(history.comparability)
    && Number.isInteger(history.reference_count) && history.reference_count > 0) {
    referenceRows.push(["history", text("history"), `${number(history.reference_count, 0)} ${text("comparableSessions")}`]);
  } else if (history?.status === "insufficient") {
    referenceRows.push(["history", text("history"), text("insufficientHistory")]);
  }
  synthesisItems.forEach((item) => {
    const paceCount = item.code === "coach.history.pace" ? item.evidence?.pace_sample_count : null;
    const hrCount = item.code === "coach.history.hr" ? item.evidence?.hr_sample_count : null;
    if (Number.isInteger(paceCount) && paceCount > 0) {
      referenceRows.push(["pace", text("paceReference"), `${number(paceCount, 0)} ${text("earlierSessions")}`]);
    }
    if (Number.isInteger(hrCount) && hrCount > 0) {
      referenceRows.push(["hr", text("hrReference"), `${number(hrCount, 0)} ${text("earlierSessions")}`]);
    }
  });

  const limitations = mergeWorkoutLimitations({
    synthesis: synthesisLimitations,
    narrative: Array.isArray(narrative?.limitations) ? narrative.limitations : [],
  });
  const { essential, rest } = splitWorkoutLimitations(limitations);
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
  // "Insufficient history" alone is a state, not a reason to offer an otherwise empty disclosure.
  const hasDetails = detailsAvailable || comparisonRows.length > 0
    || referenceRows.some(([key]) => key !== "history" || history?.status === "available")
    || rest.length > 0 || otherMarkers.length > 0;

  return (
    <div className="min-w-0 space-y-4 break-words" data-testid="workout-facts">
      {shownMarkers.length > 0 && <section aria-labelledby="workout-evidence-title" data-testid="workout-evidence">
        <h2 id="workout-evidence-title" className="mb-2 text-base font-semibold">{text("markers")}</h2>
        <ul className="space-y-2 border-y border-border py-3">
          {shownMarkers.map(([key, label, value]) => <li key={key} className="min-w-0 text-sm" data-testid="session-marker">
            {label && <span className="block text-xs text-muted-foreground">{label}</span>}
            <span className="font-medium">{value}</span>
          </li>)}
        </ul>
      </section>}
      {essential && <p className="text-sm text-muted-foreground" data-testid="workout-limitations">{essential.text}</p>}
      {action}
      {hasDetails && <details className="min-w-0 rounded-xl border border-border p-3" data-testid="workout-analysis-details">
        <summary className="min-h-11 cursor-pointer text-sm font-medium">{text("details")}</summary>
        <div className="space-y-4 pt-2">
          {otherMarkers.length > 0 && <ul className="space-y-2 text-sm" data-testid="other-markers">
            {otherMarkers.map(([key, label, value]) => <li key={key}>
              {label && <span className="block text-xs text-muted-foreground">{label}</span>}{value}
            </li>)}
          </ul>}
          {children}
          {comparisonRows.length > 0 && <section data-testid="narrative-comparisons">
            <h3 className="mb-2 text-sm font-semibold">{text("history")}</h3>
            <dl className="space-y-2 text-sm">{comparisonRows.map(([key, value]) =>
              <div key={key}><dt className="text-muted-foreground">{text(key)}</dt><dd>{value}</dd></div>)}</dl>
          </section>}
          {referenceRows.length > 0 && <section data-testid="reference-populations">
            <h3 className="mb-1 text-sm font-semibold">{text("references")}</h3>
            <p className="mb-2 text-xs text-muted-foreground">{text("referencesNote")}</p>
            <dl className="space-y-2 text-sm">{referenceRows.map(([key, label, value]) =>
              <div key={key}><dt className="text-muted-foreground">{label}</dt><dd>{value}</dd></div>)}</dl>
          </section>}
          {rest.length > 0 && <section data-testid="workout-limitations-details">
            <h3 className="mb-2 text-sm font-semibold">{text("methodLimits")}</h3>
            <ul className="space-y-2 text-sm text-muted-foreground">
              {rest.map((item) => <li key={item.key} data-sources={item.sources.join(",")}>{item.text}</li>)}
            </ul>
          </section>}
        </div>
      </details>}
    </div>
  );
}

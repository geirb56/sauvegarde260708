import { formatAnalysisNumber, formatAnalysisDelta } from "@/lib/analysisFormat";
import { Activity, ArrowLeftRight, ChevronDown, Gauge, Info, Repeat, Tag } from "lucide-react";
import { describeMarker, projectSynthesisMarker } from "@/lib/workoutMarkers";
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

// Native <details>: keyboard, mouse and touch accessible, closed by default.
export function DetailsDisclosure({ title, children }) {
  return (
    <details className="group min-w-0 rounded-2xl border border-border/60 bg-card" data-testid="workout-analysis-details">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-4 py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">{title}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="min-w-0 space-y-4 px-4 pb-4 pt-1">{children}</div>
    </details>
  );
}

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
  const structuredCodes = new Set();
  const observationTexts = [];
  // V2 primary marker first, then structure/type, then intensity.
  synthesisItems.forEach((item) => {
    const projected = projectSynthesisMarker(item);
    if (projected.kind === "text") {
      markers.push({ key: `synthesis:${item.code}`, Icon: Activity, value: item.text });
      return;
    }
    structuredCodes.add(item.code);
    observationTexts.push([item.code, item.text]);
    markers.push({ key: `synthesis:${item.code}`, Icon: ArrowLeftRight, structured: describeMarker(projected, lang, text) });
  });
  const counts = classification?.evidence;
  if (classification?.type === "intervals"
    && Number.isInteger(counts?.effort_count) && counts.effort_count > 0
    && Number.isInteger(counts?.recovery_count) && counts.recovery_count >= 0) {
    markers.push({ key: "structure", Icon: Repeat, label: text("structure"), value: `${number(counts.effort_count, 0)} ${text("efforts")} · ${number(counts.recovery_count, 0)} ${text("recoveries")}` });
  } else if (classificationTypes.includes(classification?.type) && classification.type !== "unknown") {
    markers.push({ key: "type", Icon: Tag, label: text("type"), value: text(classification.type) });
  }
  if (reliable(intensity?.confidence)
    && ["below_LT1", "between_LT1_LT2", "above_LT2"].includes(intensity.position)) {
    markers.push({ key: "intensity", Icon: Gauge, label: text("intensity"), value: text(intensity.position) });
  }
  // An undetermined type is only worth a line when nothing else is known.
  if (markers.length === 0 && classification?.type === "unknown") {
    markers.push({ key: "type", Icon: Tag, label: text("type"), value: text("unknown") });
  }
  const shownMarkers = markers.slice(0, 3);
  const otherMarkers = markers.slice(3);
  const hasStructured = shownMarkers.some((marker) => marker.structured);

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
    // The count of a structured marker is already labelled on the marker itself.
    if (structuredCodes.has(item.code)) return;
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

  return (
    <div className="min-w-0 space-y-4 break-words" data-testid="workout-facts">
      {shownMarkers.length > 0 && <section aria-labelledby="workout-evidence-title" data-testid="workout-evidence"
        className="min-w-0 rounded-2xl border border-border/60 bg-card p-4">
        <h2 id="workout-evidence-title" className="mb-3 text-base font-semibold">{text("markers")}</h2>
        <ul className="space-y-3">
          {shownMarkers.map((marker, index) => {
            const { key, Icon, label, value, structured } = marker;
            return <li key={key} className={`flex min-w-0 items-start gap-3 ${index > 0 ? "border-t border-border/60 pt-3" : ""}`} data-testid="session-marker">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary" aria-hidden="true">
                <Icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                {structured ? <>
                  <p className="text-xs text-muted-foreground">{structured.label}</p>
                  <p className={`${index === 0 ? "text-lg" : "text-base"} font-semibold leading-snug`} data-testid="marker-headline">{structured.headline}</p>
                  <p className="text-sm text-muted-foreground" data-testid="marker-detail">{structured.detail}</p>
                </> : <>
                  {label && <p className="text-xs text-muted-foreground">{label}</p>}
                  <p className="text-sm font-medium">{value}</p>
                </>}
              </div>
            </li>;
          })}
        </ul>
        {hasStructured && <p className="mt-3 text-xs text-muted-foreground" data-testid="comparable-note">{text("comparableNote")}</p>}
      </section>}
      {essential && <p className="flex items-start gap-2 text-sm text-muted-foreground" data-testid="workout-limitations">
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0">{essential.text}</span>
      </p>}
      {action}
    </div>
  );
}

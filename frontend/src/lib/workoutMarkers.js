import { formatAnalysisNumber } from "@/lib/analysisFormat";
import { formatPaceDisplay } from "@/lib/workoutAnalysis";

const isCount = (value) => Number.isInteger(value) && value > 0;
const direction = (difference) => (difference < 0 ? "lower" : difference > 0 ? "higher" : "same");

// Pure UI projection of an already validated V2 session_synthesis item.
// Only the structured evidence fields are read (never the localized sentence);
// the engine's differential is displayed as provided, never recomputed from rounded values.
// Items without a complete numeric evidence set stay textual.
export const projectSynthesisMarker = (item) => {
  const evidence = item?.evidence;
  if (item?.code === "coach.history.pace"
    && isCount(evidence?.pace_sample_count)
    && Number.isFinite(evidence.pace_difference_sec_per_km)
    && evidence.current_pace_min_km > 0 && evidence.baseline_pace_min_km > 0) {
    return {
      kind: "pace",
      count: evidence.pace_sample_count,
      difference: evidence.pace_difference_sec_per_km,
      direction: direction(evidence.pace_difference_sec_per_km),
      current: evidence.current_pace_min_km,
      baseline: evidence.baseline_pace_min_km,
    };
  }
  if (item?.code === "coach.history.hr"
    && isCount(evidence?.hr_sample_count)
    && Number.isFinite(evidence.heart_rate_difference_bpm)
    && evidence.current_heart_rate_bpm > 0 && evidence.baseline_heart_rate_bpm > 0) {
    return {
      kind: "hr",
      count: evidence.hr_sample_count,
      difference: evidence.heart_rate_difference_bpm,
      direction: direction(evidence.heart_rate_difference_bpm),
      current: evidence.current_heart_rate_bpm,
      baseline: evidence.baseline_heart_rate_bpm,
    };
  }
  return { kind: "text" };
};

// Localized strings for a projected marker. `text` is the workoutNarrative i18n lookup.
export const describeMarker = (marker, lang, text) => {
  const count = formatAnalysisNumber(marker.count, lang, 0);
  const amount = formatAnalysisNumber(Math.abs(marker.difference), lang, 2);
  if (marker.kind === "pace") {
    return {
      label: text("paceMarkerLabel").replace("{count}", count),
      headline: marker.direction === "same"
        ? text("paceSame")
        : text(marker.direction === "lower" ? "paceFaster" : "paceSlower").replace("{value}", amount),
      detail: text("compareLine").replace("{current}", formatPaceDisplay(marker.current)).replace("{baseline}", formatPaceDisplay(marker.baseline)),
    };
  }
  const bpm = (value) => `${formatAnalysisNumber(value, lang, 0)} bpm`;
  return {
    label: text("hrMarkerLabel").replace("{count}", count),
    headline: marker.direction === "same"
      ? text("hrSame")
      : text(marker.direction === "lower" ? "hrLower" : "hrHigher").replace("{value}", amount),
    detail: text("compareLine").replace("{current}", bpm(marker.current)).replace("{baseline}", bpm(marker.baseline)),
  };
};

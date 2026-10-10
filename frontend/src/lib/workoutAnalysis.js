export const formatPaceDisplay = (pace) => {
  if (pace == null || !Number.isFinite(pace)) return "--";
  const seconds = Math.round(pace * 60);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}/km`;
};

export const formatPaceDelta = (difference) => {
  if (difference == null || !Number.isFinite(difference)) return "--";
  const seconds = Math.round(Math.abs(difference) * 60);
  if (seconds === 0) return "0:00/km";
  const sign = difference < 0 ? "-" : difference > 0 ? "+" : "";
  return `${sign}${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}/km`;
};

export const hasCoachObservation = (analysis) =>
  analysis?.advice?.available === true
  && typeof analysis.advice.text === "string"
  && analysis.advice.text.trim().length > 0;

export const getAnalysisLimitations = (analysis, t) => {
  const items = Array.isArray(analysis?.limitations) ? [...analysis.limitations] : [];
  const intensity = analysis?.signals?.intensity;
  if (intensity?.available === false && intensity.reason_unavailable) {
    items.push({ code: "limitations.intensity", text: intensity.reason_unavailable });
  }
  const legacyLabels = {
    session_nature_unknown: "unknownSessionNature",
    sample_too_small: "smallSample",
    pace_sample_too_small: "smallPaceSample",
    hr_sample_too_small: "smallHrSample",
    no_comparable_reference: "similarUnavailable",
  };
  const similar = analysis?.comparison?.similar;
  if (Array.isArray(similar?.limitations)) {
    similar.limitations.forEach((code) => {
      if (legacyLabels[code]) {
        items.push({ code: `limitations.${code}`, text: t(`workoutDetailExtended.${legacyLabels[code]}`) });
      }
    });
  }
  const codes = new Set();
  const texts = new Set();
  return items.filter((item) => {
    if (typeof item?.code !== "string" || typeof item.text !== "string" || !item.text.trim()) return false;
    if (codes.has(item.code) || texts.has(item.text)) return false;
    codes.add(item.code);
    texts.add(item.text);
    return true;
  });
};

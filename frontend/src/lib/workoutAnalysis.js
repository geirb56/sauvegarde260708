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

export const getSessionClassification = (analysis, t) => {
  const structure = analysis?.signals?.session_structure;
  if (structure?.available === true && ["intervals", "continuous"].includes(structure.code)) {
    return {
      label: t("workoutDetailExtended.structure"),
      text: t(`workoutDetailExtended.structure${structure.code === "intervals" ? "Intervals" : "Continuous"}`),
    };
  }
  const type = analysis?.signals?.session_type;
  return type?.available === true && type.code !== "standard" && type.text
    ? { label: t("analysis.type"), text: type.text }
    : null;
};

export const getAnalysisObservations = (analysis) => {
  const facts = analysis?.meaning?.factual_observations;
  if (Array.isArray(facts)) {
    const codes = new Set();
    const texts = new Set();
    return facts.filter((fact) => {
      if (fact?.placement !== "summary"
        || typeof fact.code !== "string" || !fact.code.trim()
        || ["fact.pacing_consistency", "fact.consistency", "fact.hr_drift_measured", "fact.hr_drift"].includes(fact.code.trim())
        || typeof fact.text !== "string" || !fact.text.trim()
        || !fact.evidence || typeof fact.evidence !== "object" || Array.isArray(fact.evidence)
        || Object.keys(fact.evidence).length === 0
        || !Object.values(fact.evidence).every(Number.isFinite)) return false;
      const code = fact.code.trim();
      const text = fact.text.trim();
      if (codes.has(code) || texts.has(text)) return false;
      codes.add(code);
      texts.add(text);
      return true;
    }).map((fact) => fact.text.trim());
  }
  return [];
};

export const getAnalysisTakeaway = (analysis) => getAnalysisObservations(analysis)[0] || null;

export const getDistinctCoachObservation = (analysis) => {
  const advice = analysis?.advice;
  if (advice?.available !== true || typeof advice.text !== "string" || !advice.text.trim()) return null;

  const facts = Array.isArray(analysis?.meaning?.factual_observations)
    ? analysis.meaning.factual_observations : [];
  const hasFact = (code) => facts.some((fact) =>
    fact?.code === code
    && fact?.placement === "summary"
    && typeof fact.text === "string" && fact.text.trim()
    && fact.evidence && typeof fact.evidence === "object" && !Array.isArray(fact.evidence)
    && Object.keys(fact.evidence).length > 0
    && Object.values(fact.evidence).every(Number.isFinite));
  const intensity = analysis?.signals?.intensity;
  const paceChange = analysis?.pacing?.pace_drop_min_km;

  if (advice.code === "advice.high_intensity_observation"
    && intensity?.available === true && ["high", "very_high"].includes(intensity.code)) return advice.text.trim();
  if (advice.code === "advice.low_intensity_observation"
    && intensity?.available === true && intensity.code === "low") return advice.text.trim();
  if (advice.code === "advice.even_pacing"
    && Number.isFinite(paceChange) && Math.abs(paceChange) >= 0.4
    && !hasFact("fact.pace_change")) return advice.text.trim();
  if (advice.code === "advice.negative_split_confirmed"
    && analysis?.pacing?.negative_split === true
    && !hasFact("fact.negative_split") && !hasFact("fact.faster_second_half")) return advice.text.trim();

  return null;
};

export const getRenderableAnalysisPhases = (phaseAnalysis) => {
  if (phaseAnalysis?.available !== true) return [];
  const phases = Array.isArray(phaseAnalysis.phases) && phaseAnalysis.phases.length > 0
    ? phaseAnalysis.phases
    : [
      ...(Array.isArray(phaseAnalysis.efforts) ? phaseAnalysis.efforts : []),
      ...(Array.isArray(phaseAnalysis.recoveries) ? phaseAnalysis.recoveries : []),
    ];
  return phases.filter((phase) => phase && typeof phase === "object" && !Array.isArray(phase));
};

const hasMeasuredPhaseObservations = (phaseAnalysis) => {
  const phases = getRenderableAnalysisPhases(phaseAnalysis);
  if (phases.length === 0) return false;
  if (phases.some((phase) =>
    (Number.isFinite(phase.duration_s) && phase.duration_s >= 0)
    || (Number.isFinite(phase.pace_sec_per_km) && phase.pace_sec_per_km > 0)
    || (Number.isFinite(phase.average_hr) && phase.average_hr > 0))) return true;
  const averagePace = phaseAnalysis.effort_statistics?.average_pace_sec_per_km;
  if (Number.isFinite(averagePace) && averagePace > 0) return true;
  const regularity = phaseAnalysis.effort_regularity;
  return regularity?.available === true
    && ((Number.isFinite(regularity.pace_dispersion_sec_per_km) && regularity.pace_dispersion_sec_per_km >= 0)
      || Number.isFinite(regularity.first_to_last_pace_change_sec_per_km));
};

export const getAnalysisFallback = (analysis, t) =>
  analysis && getAnalysisObservations(analysis).length === 0
    && !getDistinctCoachObservation(analysis)
    && !hasMeasuredPhaseObservations(analysis.phase_analysis)
    ? t("workoutDetailExtended.noReliableObservations")
    : null;

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

/**
 * PR #193 — Race Predictions UI — Align Frontend on Performance Curve V2
 *
 * Static analysis tests (file-system reads only, no DOM rendering, no node_modules).
 *
 * Acceptance criteria verified:
 *  A. Subtitle no longer mentions VMA.
 *  B. confidence=high → "High" / "Élevée" label path present.
 *  C. confidence=insufficient rendered even when readiness_score is available.
 *  D. "% prêt" / "% ready" no longer shown in race predictions card.
 *  E. predicted_range not displayed.
 *  F. GOAL badge is associated with distance badge, not chrono.
 *  G. Non-goal distances have no GOAL badge.
 *  H. predicted_time null → "notEnoughPredictionData" key used.
 *  I. confidenceLabel i18n key present in all three languages.
 *  J. racePredictionBasis key present (replaces basedOnVma).
 */

import fs from "fs";
import path from "path";

const PROGRESS_PATH = path.resolve(__dirname, "../pages/Progress.jsx");
const I18N_PATH = path.resolve(__dirname, "../lib/i18n.js");

function readProgress() {
  return fs.readFileSync(PROGRESS_PATH, "utf8");
}

function readI18n() {
  return fs.readFileSync(I18N_PATH, "utf8");
}

// ---------------------------------------------------------------------------
// A — Subtitle no longer claims VMA source
// ---------------------------------------------------------------------------
describe("PR193-A — subtitle no longer mentions VMA", () => {
  test("basedOnVma key is no longer used in Progress.jsx", () => {
    expect(readProgress()).not.toContain("basedOnVma");
  });

  test("racePredictionBasis key is used as subtitle", () => {
    expect(readProgress()).toContain("racePredictionBasis");
  });

  test("i18n EN racePredictionBasis does not mention VMA", () => {
    const i18n = readI18n();
    // Extract EN value
    const match = i18n.match(/racePredictionBasis:\s*"([^"]+)"/g);
    expect(match).not.toBeNull();
    match.forEach((m) => {
      expect(m.toLowerCase()).not.toContain("vma");
    });
  });
});

// ---------------------------------------------------------------------------
// B — confidence=high rendered via confidenceHigh key
// ---------------------------------------------------------------------------
describe("PR193-B — confidence high path", () => {
  test("confidenceHigh i18n key is mapped in Progress.jsx", () => {
    expect(readProgress()).toContain("confidenceHigh");
  });

  test("confidence value 'high' maps to confidenceHigh key", () => {
    expect(readProgress()).toContain(`i18nKey: "confidenceHigh"`);
  });
});

// ---------------------------------------------------------------------------
// C — confidence=insufficient rendered regardless of readiness_score
// ---------------------------------------------------------------------------
describe("PR193-C — confidence insufficient path", () => {
  test("confidenceInsufficient key is mapped in Progress.jsx", () => {
    expect(readProgress()).toContain("confidenceInsufficient");
  });

  test("confidence insufficient is the fallback in the map", () => {
    // The CONFIDENCE_MAP fallback defaults to CONFIDENCE_MAP.insufficient
    expect(readProgress()).toContain(`CONFIDENCE_MAP.insufficient`);
  });
});

// ---------------------------------------------------------------------------
// D — "% prêt" / "% ready" / readinessPct no longer shown in predictions card
// ---------------------------------------------------------------------------
describe("PR193-D — readiness percentage removed from predictions", () => {
  test("readiness_score is not rendered in predictions card", () => {
    // readiness_score should not appear inside the predictions map
    expect(readProgress()).not.toContain("pred.readiness_score");
  });

  test("readinessPct key no longer used inside predictions map", () => {
    // readinessPct should not appear inside predictions map (it's the "% prêt" label)
    expect(readProgress()).not.toContain("readinessPct");
  });
});

// ---------------------------------------------------------------------------
// E — predicted_range not displayed
// ---------------------------------------------------------------------------
describe("PR193-E — predicted_range hidden", () => {
  test("pred.predicted_range is not rendered", () => {
    expect(readProgress()).not.toContain("pred.predicted_range");
  });
});

// ---------------------------------------------------------------------------
// F — GOAL badge is inside distance badge block, not chrono block
// ---------------------------------------------------------------------------
describe("PR193-F — GOAL badge associated with distance", () => {
  const code = readProgress();

  test("goalLabel is rendered inside the distance badge div block", () => {
    // The distance badge div must contain both pred.distance and goalLabel
    // We verify that goalLabel appears after the distance badge section marker
    const distanceBadgeIdx = code.indexOf("Distance badge — GOAL badge attached here");
    expect(distanceBadgeIdx).toBeGreaterThan(-1);
    const goalLabelIdx = code.indexOf('goalLabel")', distanceBadgeIdx);
    expect(goalLabelIdx).toBeGreaterThan(distanceBadgeIdx);
  });

  test("goalLabel does NOT appear next to predicted_time span", () => {
    // In old code, goalLabel appeared inside the "Predicted time" flex row.
    // New code must not show goalLabel after the "Predicted time" comment.
    const predictedTimeIdx = code.indexOf("Predicted time");
    expect(predictedTimeIdx).toBeGreaterThan(-1); // guard: comment must exist
    const goalLabelAfterTime = code.indexOf("goalLabel", predictedTimeIdx);
    // goalLabel must not appear after the "Predicted time" section comment
    expect(goalLabelAfterTime).toBe(-1);
  });
});

// ---------------------------------------------------------------------------
// G — isGoal logic still present (non-goal distances unaffected)
// ---------------------------------------------------------------------------
describe("PR193-G — isGoal guard still present", () => {
  test("isGoal derived from V2_GOAL_TO_PRED_DISTANCE", () => {
    expect(readProgress()).toContain("V2_GOAL_TO_PRED_DISTANCE");
    expect(readProgress()).toContain("isGoal");
  });

  test("isGoal conditional wraps goalLabel rendering", () => {
    expect(readProgress()).toContain("{isGoal && (");
  });
});

// ---------------------------------------------------------------------------
// H — predicted_time null → notEnoughPredictionData state shown
// ---------------------------------------------------------------------------
describe("PR193-H — null predicted_time handled honestly", () => {
  test("notEnoughPredictionData key is used when predicted_time is null", () => {
    expect(readProgress()).toContain("notEnoughPredictionData");
  });

  test("null guard on pred.predicted_time present", () => {
    // Should check pred.predicted_time before rendering chrono
    expect(readProgress()).toContain("pred.predicted_time ?");
  });
});

// ---------------------------------------------------------------------------
// I — confidenceLabel i18n key in all three languages
// ---------------------------------------------------------------------------
describe("PR193-I — confidenceLabel i18n in FR/EN/ES", () => {
  test("confidenceLabel appears at least 3 times (EN + FR + ES)", () => {
    const matches = readI18n().match(/confidenceLabel:/g);
    expect(matches).not.toBeNull();
    expect(matches.length).toBeGreaterThanOrEqual(3);
  });
});

// ---------------------------------------------------------------------------
// J — racePredictionBasis key replaces basedOnVma in all 3 languages
// ---------------------------------------------------------------------------
describe("PR193-J — racePredictionBasis i18n in FR/EN/ES", () => {
  test("racePredictionBasis appears at least 3 times (EN + FR + ES)", () => {
    const matches = readI18n().match(/racePredictionBasis:/g);
    expect(matches).not.toBeNull();
    expect(matches.length).toBeGreaterThanOrEqual(3);
  });

  test("basedOnVma key is gone from i18n", () => {
    expect(readI18n()).not.toContain("basedOnVma");
  });
});

// ---------------------------------------------------------------------------
// INVARIANTS — non-regression
// ---------------------------------------------------------------------------
describe("PR193 — non-regression invariants", () => {
  test("API endpoint /training/race-predictions unchanged", () => {
    expect(readProgress()).toContain("/training/race-predictions");
  });

  test("goal source /training/v2/cycle unchanged", () => {
    expect(readProgress()).toContain("/training/v2/cycle");
  });

  test("pred.confidence is the only source of confidence display", () => {
    expect(readProgress()).toContain("pred.confidence");
  });

  test("readiness_label is not rendered in predictions card", () => {
    expect(readProgress()).not.toContain("pred.readiness_label");
  });
});

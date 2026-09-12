/**
 * PR BETA-BLOCKING — Potential UI contract static checks.
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

describe("Potential block static invariants", () => {
  test("still uses race predictions endpoint truth", () => {
    expect(readProgress()).toContain("/training/race-predictions");
  });

  test("still uses cycle endpoint for goal highlighting", () => {
    expect(readProgress()).toContain("/training/v2/cycle");
  });

  test("maps confidence levels with insufficient fallback", () => {
    const code = readProgress();
    expect(code).toContain("confidenceHigh");
    expect(code).toContain("confidenceMedium");
    expect(code).toContain("confidenceLow");
    expect(code).toContain("confidenceInsufficient");
  });

  test("does not render 0:00 fallback literals", () => {
    expect(readProgress()).not.toContain("0:00");
  });

  test("distance labels are localized", () => {
    const code = readProgress();
    expect(code).toContain("distance5K");
    expect(code).toContain("distance10K");
    expect(code).toContain("distanceHalfMarathon");
    expect(code).toContain("distanceMarathon");
  });
});

describe("Potential i18n keys are present in EN/FR/ES", () => {
  test("potential framing keys exist in all 3 languages", () => {
    const i18n = readI18n();
    ["potentialTitle", "potentialSubtitle", "potentialGarminSource", "potentialTrainingLink", "potentialNotEnoughDataTitle", "potentialError"].forEach((key) => {
      const matches = i18n.match(new RegExp(`${key}:`, "g"));
      expect(matches).not.toBeNull();
      expect(matches.length).toBeGreaterThanOrEqual(3);
    });
  });
});

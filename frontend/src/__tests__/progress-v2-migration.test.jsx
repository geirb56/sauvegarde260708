/**
 * PR #196 — Progress V2 migration to Garmin native VO2max.
 *
 * INVARIANTS:
 *  VMA_FRONTEND_REMOVED = YES
 *  VMA_HISTORY_FRONTEND_REMOVED = YES
 *  GARMIN_NATIVE_VO2MAX_FRONTEND = YES
 *  GARMIN_NATIVE_VO2MAX_HISTORY_FRONTEND = YES
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

describe("PR196 — remove legacy VMA frontend", () => {
  test("/training/vma-history endpoint removed", () => {
    expect(readProgress()).not.toContain("/training/vma-history");
  });

  test("vmaHistory state removed", () => {
    const code = readProgress();
    expect(code).not.toContain("vmaHistory");
    expect(code).not.toContain("setVmaHistory");
  });

  test("old VMA chart key removed", () => {
    expect(readProgress()).not.toContain('dataKey="vo2max"');
  });
});

describe("PR196 — Garmin native VO2max frontend", () => {
  test("current VO2max comes from run-index metrics", () => {
    const code = readProgress();
    expect(code).toContain("/run-index");
    expect(code).toContain("vo2max_running");
    expect(code).toContain("vo2max_date");
  });

  test("Garmin sparse history endpoint consumed", () => {
    expect(readProgress()).toContain("/garmin/vo2max-history?period=12m");
  });

  test("history chart uses Garmin value series", () => {
    expect(readProgress()).toContain('dataKey="value"');
    expect(readProgress()).toContain("connectNulls={false}");
  });

  test("no legacy fallback to predictions athlete_profile VO2max", () => {
    expect(readProgress()).not.toContain("athlete_profile?.estimated_vo2max");
  });

  test("no-vo2max empty state is present", () => {
    expect(readProgress()).toContain("noGarminVo2maxAvailable");
  });
});

describe("PR196 — race predictions preserved", () => {
  test("race predictions endpoint still used", () => {
    expect(readProgress()).toContain("/training/race-predictions");
  });

  test("predictions list rendering preserved", () => {
    expect(readProgress()).toContain("predictions.predictions?.map");
  });
});

describe("PR196 — i18n keys added for Garmin VO2max", () => {
  test("new keys exist in i18n", () => {
    const i18n = readI18n();
    const keys = [
      "garminVo2maxLabel",
      "garminVo2maxHistoryTitle",
      "measurementDateLabel",
      "noGarminVo2maxAvailable",
    ];
    for (const key of keys) {
      expect(i18n).toContain(`${key}:`);
    }
  });
});

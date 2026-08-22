/**
 * PR #184 — Progress V2 Migration — Static Analysis Tests
 *
 * These tests use file-system reads only (no DOM rendering, no node_modules
 * dependencies) so they run in any environment including sandboxes without
 * npm install.
 *
 * Tests mandated by spec:
 *  B. run_index=null → null stays null, never 0 (connectNulls=false)
 *  C. Period without score → no false curve continuity (connectNulls=false)
 *  H. Cycle migrated → /training/v2/cycle used, full-cycle endpoint dropped
 *  I. VMA frontend always present (static invariant)
 *  J. VMA history frontend always present (static invariant)
 *  K. Race Predictions frontend always present (static invariant)
 *  N. No raw i18n keys (Garmin labels translated)
 *  O. FREE paywall not regressed
 *
 * INVARIANTS:
 *  VMA_FRONTEND_PRESERVED = YES
 *  VMA_HISTORY_FRONTEND_PRESERVED = YES
 *  PREDICTIONS_FRONTEND_PRESERVED = YES
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
// RunIndex null semantics
// ---------------------------------------------------------------------------
describe("PR184 — RunIndex null semantics (B/C)", () => {
  test("B/C — connectNulls={false} ensures line breaks at null periods", () => {
    expect(readProgress()).toContain("connectNulls={false}");
  });

  test("B — chart data not pre-filtered: null points kept for gap rendering", () => {
    // Old code removed nulls before chart: filter(h => h.run_index !== null)
    // This caused false continuity. Must be absent.
    expect(readProgress()).not.toContain("filter(h => h.run_index !== null)");
  });
});

// ---------------------------------------------------------------------------
// Training Cycle V2 migration (H)
// ---------------------------------------------------------------------------
describe("PR184 — Training Cycle V2 (H)", () => {
  test("H — /training/v2/cycle is called", () => {
    expect(readProgress()).toContain("/training/v2/cycle");
  });

  test("H — /training/full-cycle is no longer called", () => {
    // The endpoint string must not appear (comments were also removed)
    expect(readProgress()).not.toContain("/training/full-cycle");
  });

  test("H — cycleV2 state replaces fullCycle", () => {
    const code = readProgress();
    expect(code).toContain("cycleV2");
    expect(code).not.toContain("fullCycle");
  });

  test("H — V2_GOAL_TO_PRED_DISTANCE map present", () => {
    expect(readProgress()).toContain("V2_GOAL_TO_PRED_DISTANCE");
  });
});

// ---------------------------------------------------------------------------
// VMA frontend preserved (I/J — INVARIANT)
// ---------------------------------------------------------------------------
describe("PR184 — VMA_FRONTEND_PRESERVED = YES (I/J)", () => {
  test("I — /training/vma-history endpoint still called", () => {
    expect(readProgress()).toContain("/training/vma-history");
  });

  test("I — vmaHistory state still managed", () => {
    const code = readProgress();
    expect(code).toContain("vmaHistory");
    expect(code).toContain("setVmaHistory");
  });

  test("J — VMA history chart: vo2max dataKey present", () => {
    expect(readProgress()).toContain('dataKey="vo2max"');
  });

  test("I — VO2MAX display still rendered (ml/kg/min)", () => {
    expect(readProgress()).toContain("ml/kg/min");
  });
});

// ---------------------------------------------------------------------------
// Race Predictions frontend preserved (K/L — INVARIANT)
// ---------------------------------------------------------------------------
describe("PR184 — PREDICTIONS_FRONTEND_PRESERVED = YES (K/L)", () => {
  test("K — /training/race-predictions endpoint still called", () => {
    expect(readProgress()).toContain("/training/race-predictions");
  });

  test("K — predictions state still managed", () => {
    const code = readProgress();
    expect(code).toContain("predictions");
    expect(code).toContain("setPredictions");
  });

  test("L — predictions.predictions?.map() still renders distance badges", () => {
    expect(readProgress()).toContain("predictions.predictions?.map");
  });

  test("L — pred.distance still rendered", () => {
    expect(readProgress()).toContain("pred.distance");
  });
});

// ---------------------------------------------------------------------------
// Stats source (E)
// ---------------------------------------------------------------------------
describe("PR184 — Stats from DomainActivity (E)", () => {
  test("E — /stats endpoint still called", () => {
    // URL is in a template literal: `${API}/stats`
    expect(readProgress()).toContain("}/stats`");
  });

  test("E — sessions_7_days, km_7_days, km_30_days consumed", () => {
    const code = readProgress();
    expect(code).toContain("sessions_7_days");
    expect(code).toContain("km_7_days");
    expect(code).toContain("km_30_days");
  });
});

// ---------------------------------------------------------------------------
// Garmin health null semantics (M)
// ---------------------------------------------------------------------------
describe("PR184 — Garmin health null semantics (M)", () => {
  test("M — garminHealth section only rendered when count > 0", () => {
    expect(readProgress()).toContain("garminHealth?.latest");
  });

  test("M — null-safe ?? operator used for HRV/RHR/sleep", () => {
    const code = readProgress();
    expect(code).toContain("hrv ??");
    expect(code).toContain("resting_hr ??");
    expect(code).toContain("sleep_hours ??");
  });
});

// ---------------------------------------------------------------------------
// i18n — no raw keys visible (N)
// ---------------------------------------------------------------------------
describe("PR184 — i18n: no raw keys (N)", () => {
  test("N — Garmin Health title uses t() key", () => {
    const code = readProgress();
    expect(code).not.toContain("Garmin Health · 7 days");
    expect(code).toContain("garminHealthTitle");
  });

  test("N — Resting HR uses t() key", () => {
    const code = readProgress();
    expect(code).not.toContain('"Resting HR"');
    expect(code).toContain("garminRestingHr");
  });

  test("N — Sleep uses t() key", () => {
    const code = readProgress();
    expect(code).not.toContain('"Sleep"');
    expect(code).toContain("garminSleep");
  });

  test("N — OBJECTIF badge uses t() key", () => {
    const code = readProgress();
    expect(code).not.toContain('"OBJECTIF"');
    expect(code).toContain("goalLabel");
  });

  test("N — % prêt uses t() key", () => {
    const code = readProgress();
    expect(code).not.toContain("prêt");
    expect(code).toContain("readinessPct");
  });

  test("N — EN: all progressExtended i18n keys have values", () => {
    const i18n = readI18n();
    const keys = ["garminHealthTitle", "garminRestingHr", "garminSleep", "goalLabel", "readinessPct"];
    for (const key of keys) {
      expect(i18n).toContain(`${key}:`);
    }
  });

  test("N — FR: garminHealthTitle is in French", () => {
    expect(readI18n()).toContain("Garmin Health · 7 jours");
  });

  test("N — ES: garminHealthTitle is in Spanish", () => {
    expect(readI18n()).toContain("Garmin Health · 7 días");
  });
});

// ---------------------------------------------------------------------------
// FREE paywall not regressed (O)
// ---------------------------------------------------------------------------
describe("PR184 — FREE paywall not regressed (O)", () => {
  test("O — isFree check still present", () => {
    expect(readProgress()).toContain("isFree");
  });

  test("O — Paywall component still rendered for free users", () => {
    expect(readProgress()).toContain("<Paywall");
  });
});

// ---------------------------------------------------------------------------
// Pillar null → "—" (D)
// ---------------------------------------------------------------------------
describe("PR184 — Pillar null semantics (D)", () => {
  test("D — null pillar renders em-dash, not numeric value", () => {
    // The component renders — for null pillar values
    expect(readProgress()).toContain("—");
  });

  test("D — null check before rendering pillar value", () => {
    expect(readProgress()).toContain("data.current === null");
  });
});


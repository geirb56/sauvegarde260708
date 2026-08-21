/**
 * PR #178 — Dashboard Run Readiness V2 — Frontend Consumer Tests
 *
 * Tests (15 scenarios mandated by spec):
 *  1.  run_readiness=null  → unavailable label, not 0
 *  2.  run_readiness=0     → 0/100 displayed
 *  3.  hrv_status absent   → gray tile
 *  4.  rhr_status absent   → gray tile
 *  5.  sleep_status absent → gray tile
 *  6.  training_load_status absent → gray tile
 *  7.  recommendation_color absent → gray style
 *  8.  recommendation_color unknown → gray style
 *  9.  recommendation_color green/yellow/red → matching styles
 * 10.  history: null entry filtered out
 * 11.  history: 0 entry kept
 * 12.  Refresh calls /run-index only, no other writes
 * 13.  No Readiness formula in React (static check)
 * 14.  RunIndex Score block untouched (static check)
 * 15.  Training V2 components untouched (static check)
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";
import fs from "fs";
import path from "path";

import Dashboard from "@/pages/Dashboard";
import { LanguageProvider } from "@/context/LanguageContext";

jest.mock("axios");
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => ({ unitSystem: "metric", t: (k) => k }),
}));
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({ isFree: true, loading: false }),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function buildCardio({
  run_readiness = 72,
  recommendation_color = "green",
  hrv_status = "green",
  rhr_status = "gray",
  sleep_status = "green",
  training_load_status = "green",
  history = [],
} = {}) {
  return {
    mock: false,
    source: "garmin",
    recommendation: "EASY RUN",
    recommendation_color,
    recommendation_emoji: "🟢",
    reasons: [],
    metrics: {
      run_readiness,
      hrv_today: 45,
      hrv_baseline: 50,
      hrv_delta: -5,
      hrv_status,
      hrv_available: true,
      rhr_today: hrv_status === "gray" ? null : 52,
      rhr_baseline: 51,
      rhr_delta: 1,
      rhr_status,
      sleep_hours: 7.5,
      sleep_efficiency: 0.85,
      sleep_score: 0.5,
      sleep_status,
      training_load: 1.05,
      training_load_status,
      confidence: "normal",
      sufficiency_level: "sufficient",
      readiness_reasons: [],
    },
    history,
  };
}

function setupAxios(cardio) {
  axios.get.mockImplementation((url) => {
    if (url.includes("run-index")) return Promise.resolve({ data: cardio });
    return Promise.resolve({ data: null });
  });
}

function render() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </LanguageProvider>
    );
  });
  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

async function wait() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 60));
  });
}

// ---------------------------------------------------------------------------
// Test 1 — run_readiness=null → unavailable, not 0
// ---------------------------------------------------------------------------
describe("Test 1: run_readiness=null → unavailable label, not 0", () => {
  afterEach(() => jest.clearAllMocks());

  it("shows unavailable label — not 0, not 100", async () => {
    setupAxios(buildCardio({ run_readiness: null }));
    const { container, unmount } = render();
    await wait();

    const scoreEl = container.querySelector('[data-testid="run-readiness-score"]');
    expect(scoreEl).not.toBeNull();
    expect(scoreEl.textContent).not.toBe("0");
    expect(scoreEl.textContent).not.toBe("100");
    expect(scoreEl.textContent.trim().length).toBeGreaterThan(0);

    unmount();
  });

  it("does not render '/ 100' suffix when null", async () => {
    setupAxios(buildCardio({ run_readiness: null }));
    const { container, unmount } = render();
    await wait();

    const scoreEl = container.querySelector('[data-testid="run-readiness-score"]');
    expect(scoreEl.parentElement.textContent).not.toMatch(/\d+\s*\/\s*100/);

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 2 — run_readiness=0 → 0/100 displayed
// ---------------------------------------------------------------------------
describe("Test 2: run_readiness=0 → 0/100 displayed", () => {
  afterEach(() => jest.clearAllMocks());

  it("shows 0 as a real score with / 100 suffix", async () => {
    setupAxios(buildCardio({ run_readiness: 0 }));
    const { container, unmount } = render();
    await wait();

    const scoreEl = container.querySelector('[data-testid="run-readiness-score"]');
    expect(scoreEl).not.toBeNull();
    expect(scoreEl.textContent).toBe("0");

    const parentText = scoreEl.parentElement.textContent;
    expect(parentText).toMatch(/0\s*\/\s*100/);

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 3 — hrv_status absent → gray tile
// ---------------------------------------------------------------------------
describe("Test 3: hrv_status absent → gray tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("HRV tile uses gray color when hrv_status is absent", async () => {
    const cardio = buildCardio({ hrv_status: undefined });
    cardio.metrics.hrv_status = undefined;
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-hrv"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    // Green accent is #22c55e / rgb(34, 197, 94) — neither should appear when status is absent/gray
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 4 — rhr_status absent → gray tile
// ---------------------------------------------------------------------------
describe("Test 4: rhr_status absent → gray tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("RHR tile uses gray color when rhr_status is absent", async () => {
    const cardio = buildCardio({ rhr_status: undefined });
    cardio.metrics.rhr_status = undefined;
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-rhr"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 5 — sleep_status absent → gray tile
// ---------------------------------------------------------------------------
describe("Test 5: sleep_status absent → gray tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("Sleep tile uses gray color when sleep_status is absent", async () => {
    const cardio = buildCardio({ sleep_status: undefined });
    cardio.metrics.sleep_status = undefined;
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-sleep"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 6 — training_load_status absent → gray tile
// ---------------------------------------------------------------------------
describe("Test 6: training_load_status absent → gray tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("Load tile uses gray color when training_load_status is absent", async () => {
    const cardio = buildCardio({ training_load_status: undefined });
    cardio.metrics.training_load_status = undefined;
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-load"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 7 — recommendation_color absent → gray style
// ---------------------------------------------------------------------------
describe("Test 7: recommendation_color absent → gray", () => {
  afterEach(() => jest.clearAllMocks());

  it("Recommendation badge uses gray accent when recommendation_color is absent", async () => {
    const cardio = buildCardio({ recommendation_color: undefined });
    cardio.recommendation_color = undefined;
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const badge = container.querySelector('[data-testid="run-readiness-recommendation"]');
    expect(badge).not.toBeNull();
    // Gray accent is #6b7280 → rgb(107, 114, 128) in jsdom
    const style = badge.getAttribute("style") || "";
    expect(style).toContain("rgb(107, 114, 128)");
    // Must NOT be green
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 8 — recommendation_color unknown → gray
// ---------------------------------------------------------------------------
describe("Test 8: recommendation_color unknown → gray", () => {
  afterEach(() => jest.clearAllMocks());

  it("Recommendation badge uses gray accent for unknown color value", async () => {
    const cardio = buildCardio({ recommendation_color: "purple" });
    cardio.recommendation_color = "purple";
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const badge = container.querySelector('[data-testid="run-readiness-recommendation"]');
    expect(badge).not.toBeNull();
    const style = badge.getAttribute("style") || "";
    // Unknown color → gray: #6b7280 → rgb(107, 114, 128) in jsdom
    expect(style).toContain("rgb(107, 114, 128)");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 9 — recommendation_color green/yellow/red → matching styles
// ---------------------------------------------------------------------------
describe("Test 9: recommendation_color known → matching accent", () => {
  afterEach(() => jest.clearAllMocks());

  it.each([
    ["green", "rgb(34, 197, 94)"],
    ["yellow", "rgb(245, 158, 11)"],
    ["red", "rgb(239, 68, 68)"],
  ])("color=%s → accent %s in badge style", async (color, expectedRgb) => {
    const cardio = buildCardio({ recommendation_color: color });
    cardio.recommendation_color = color;
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const badge = container.querySelector('[data-testid="run-readiness-recommendation"]');
    expect(badge).not.toBeNull();
    const style = badge.getAttribute("style") || "";
    expect(style).toContain(expectedRgb);

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 10 — history: null entry filtered out
// ---------------------------------------------------------------------------
describe("Test 10: history null entry ignored", () => {
  afterEach(() => jest.clearAllMocks());

  it("chart does not render when all history entries are null", async () => {
    const history = [
      { date: "2025-07-01", run_readiness: null },
      { date: "2025-07-02", run_readiness: null },
      { date: "2025-07-03", run_readiness: null },
    ];
    setupAxios(buildCardio({ history }));
    const { container, unmount } = render();
    await wait();

    const chart = container.querySelector('[data-testid="readiness-chart"]');
    expect(chart).toBeNull();

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 11 — history: 0 entry kept
// ---------------------------------------------------------------------------
describe("Test 11: history 0 score is kept (not filtered)", () => {
  afterEach(() => jest.clearAllMocks());

  it("chart renders when history contains score of 0", async () => {
    const history = [
      { date: "2025-07-01", run_readiness: 0 },
      { date: "2025-07-02", run_readiness: 45 },
      { date: "2025-07-03", run_readiness: 72 },
    ];
    setupAxios(buildCardio({ history }));
    const { container, unmount } = render();
    await wait();

    const chart = container.querySelector('[data-testid="readiness-chart"]');
    expect(chart).not.toBeNull();

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 12 — Refresh: calls /run-index only
// ---------------------------------------------------------------------------
describe("Test 12: Refresh button calls /run-index only", () => {
  afterEach(() => jest.clearAllMocks());

  it("clicking refresh triggers exactly one additional GET /run-index call", async () => {
    setupAxios(buildCardio());
    const { container, unmount } = render();
    await wait();

    const initialCallCount = axios.get.mock.calls.filter((c) => c[0].includes("run-index")).length;
    expect(initialCallCount).toBeGreaterThanOrEqual(1);

    const refreshBtn = container.querySelector('[data-testid="run-readiness-refresh"]');
    expect(refreshBtn).not.toBeNull();

    await act(async () => {
      refreshBtn.click();
      await new Promise((r) => setTimeout(r, 60));
    });

    const finalCallCount = axios.get.mock.calls.filter((c) => c[0].includes("run-index")).length;
    expect(finalCallCount).toBe(initialCallCount + 1);

    // Must NOT have called any sync/write/plan endpoints
    const allUrls = axios.get.mock.calls.map((c) => c[0]);
    const forbidden = allUrls.filter((u) =>
      u.includes("garmin/sync") ||
      u.includes("garmin/force") ||
      u.includes("training/plan") ||
      u.includes("refresh") ||
      u.includes("recalculate")
    );
    expect(forbidden).toHaveLength(0);

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 13 — No Readiness formula in React (static scan)
// ---------------------------------------------------------------------------
describe("Test 13: no Readiness formula recalculated in Dashboard.jsx", () => {
  it("Dashboard source does not contain hrv_status fallback to green", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf8"
    );
    expect(src).not.toMatch(/hrv_status\s*\|\|\s*["']green["']/);
    expect(src).not.toMatch(/sleep_status\s*\|\|\s*["']green["']/);
    expect(src).not.toMatch(/training_load_status\s*\|\|\s*["']green["']/);
    expect(src).not.toMatch(/REC_STYLES\[.*\]\s*\|\|\s*REC_STYLES\.green/);
  });

  it("Dashboard source does not contain dead legacy constants", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf8"
    );
    expect(src).not.toContain("FATIGUE_REST_THRESHOLD");
    expect(src).not.toContain("FATIGUE_EASY_THRESHOLD");
    expect(src).not.toContain("LOAD_OPTIMAL_MIN");
    expect(src).not.toContain("LOAD_OPTIMAL_MAX");
  });

  it("Dashboard source does not contain dead legacy color helpers", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf8"
    );
    // getAcwrColor and getTsbColor must have zero callers in Dashboard.jsx
    // (They may still exist in TrainingPlan.jsx which is not in scope)
    const acwrCallerMatches = (src.match(/getAcwrColor\s*\(/g) || []).length;
    const tsbCallerMatches = (src.match(/getTsbColor\s*\(/g) || []).length;
    expect(acwrCallerMatches).toBe(0);
    expect(tsbCallerMatches).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Test 14 — RunIndex Score block untouched
// ---------------------------------------------------------------------------
describe("Test 14: RunIndex Score block preserved", () => {
  it("Dashboard source still references run_index score block elements", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf8"
    );
    expect(src).toContain("run-index-loading");
    expect(src).toContain("runIndexScore");
    expect(src).toContain("runIndexData");
  });
});

// ---------------------------------------------------------------------------
// Test 15 — Training V2 components untouched
// ---------------------------------------------------------------------------
describe("Test 15: Training V2 components untouched", () => {
  it("TrainingPlanV2 source is not modified (still exists and contains V2 markers)", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/TrainingPlanV2.jsx"),
      "utf8"
    );
    expect(src.length).toBeGreaterThan(100);
    expect(src).toContain("TrainingPlanV2");
  });
});

// ---------------------------------------------------------------------------
// Test 16 — hrv_status="purple" → gray tile, never green
// ---------------------------------------------------------------------------
describe("Test 16: hrv_status='purple' → gray tile, never green", () => {
  afterEach(() => jest.clearAllMocks());

  it("HRV tile is gray (not green) when hrv_status is 'purple'", async () => {
    const cardio = buildCardio({ hrv_status: "purple" });
    cardio.metrics.hrv_status = "purple";
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-hrv"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 17 — sleep_status="unknown" → gray tile
// ---------------------------------------------------------------------------
describe("Test 17: sleep_status='unknown' → gray tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("Sleep tile is gray when sleep_status is 'unknown'", async () => {
    const cardio = buildCardio({ sleep_status: "unknown" });
    cardio.metrics.sleep_status = "unknown";
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-sleep"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 18 — training_load_status="unexpected" → gray tile
// ---------------------------------------------------------------------------
describe("Test 18: training_load_status='unexpected' → gray tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("Load tile is gray when training_load_status is 'unexpected'", async () => {
    const cardio = buildCardio({ training_load_status: "unexpected" });
    cardio.metrics.training_load_status = "unexpected";
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-load"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 19 — rhr_status unknown value → gray tile
// ---------------------------------------------------------------------------
describe("Test 19: rhr_status unknown value → gray tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("RHR tile is gray when rhr_status is an unknown non-empty value", async () => {
    const cardio = buildCardio({ rhr_status: "unavailable" });
    cardio.metrics.rhr_status = "unavailable";
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-rhr"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).not.toContain("#22c55e");
    expect(style).not.toContain("rgb(34, 197, 94)");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 20 — status="gray" → no red icon in tile
// ---------------------------------------------------------------------------
describe("Test 20: status='gray' → no red icon (#ef4444) in tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("HRV tile with status gray does not contain any red color", async () => {
    const cardio = buildCardio({ hrv_status: "gray" });
    cardio.metrics.hrv_status = "gray";
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-hrv"]');
    expect(tile).not.toBeNull();
    // No element inside the tile should use the red error color
    expect(tile.innerHTML).not.toContain("#ef4444");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 21 — status="red" → red color preserved in tile
// ---------------------------------------------------------------------------
describe("Test 21: status='red' → red color preserved in tile", () => {
  afterEach(() => jest.clearAllMocks());

  it("HRV tile with status red contains red color #ef4444", async () => {
    const cardio = buildCardio({ hrv_status: "red" });
    cardio.metrics.hrv_status = "red";
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-hrv"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).toContain("#ef4444");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// Test 22 — green/yellow/red → correct tile colors preserved
// ---------------------------------------------------------------------------
describe("Test 22: green/yellow/red → correct tile colors preserved", () => {
  afterEach(() => jest.clearAllMocks());

  it.each([
    ["green", "#22c55e"],
    ["yellow", "#f59e0b"],
    ["red", "#ef4444"],
  ])("hrv_status=%s → tile style contains %s", async (status, expectedHex) => {
    const cardio = buildCardio({ hrv_status: status });
    cardio.metrics.hrv_status = status;
    setupAxios(cardio);
    const { container, unmount } = render();
    await wait();

    const tile = container.querySelector('[data-testid="readiness-tile-hrv"]');
    expect(tile).not.toBeNull();
    const style = tile.getAttribute("style") || "";
    expect(style).toContain(expectedHex);

    unmount();
  });
});

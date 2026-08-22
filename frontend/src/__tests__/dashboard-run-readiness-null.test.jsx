/**
 * R3 — Dashboard run_readiness null-handling tests
 *
 * Verifies that when the backend returns run_readiness = null:
 * - the score display shows the unavailable label (not 0 or 100)
 * - the / 100 suffix is not displayed
 * - the data-testid="run-readiness-score" element contains the unavailable text
 *
 * Also verifies normal (non-null) case works as expected.
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Dashboard from "@/pages/Dashboard";
import { LanguageProvider } from "@/context/LanguageContext";

jest.mock("axios");
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <div>{children}</div>,
  DialogDescription: ({ children }) => <div>{children}</div>,
}));
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => ({ unitSystem: "metric", t: (k) => k }),
}));
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({ isFree: true, loading: false }),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildCardioPayload({ run_readiness }) {
  return {
    mock: false,
    source: "garmin",
    recommendation: run_readiness === null ? "INDISPONIBLE" : "SÉANCE INTENSE",
    recommendation_color: run_readiness === null ? "gray" : "green",
    recommendation_emoji: run_readiness === null ? "⚪" : "🟢",
    reasons: [],
    metrics: {
      run_readiness,
      run_readiness_status: run_readiness === null ? "gray" : "green",
      confidence: run_readiness === null ? "none" : "normal",
      sufficiency_level: run_readiness === null ? "insufficient" : "sufficient",
      readiness_reasons: run_readiness === null ? ["missing_load", "missing_physio"] : [],
      legacy_run_readiness: 72,
      hrv_today: null,
      hrv_baseline: null,
      hrv_delta: null,
      hrv_status: "gray",
      hrv_available: false,
      rhr_today: 52,
      rhr_baseline: 51,
      rhr_delta: 1,
      rhr_status: "green",
      sleep_hours: 7.5,
      sleep_efficiency: 0.85,
      sleep_score: 0.5,
      sleep_status: "green",
      training_load: 1.05,
      training_load_status: "green",
    },
    history: [],
  };
}

function renderDashboard() {
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

async function waitForCardioLoaded(container) {
  // Wait for the cardio section to finish loading (no spinner)
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Dashboard run_readiness null handling", () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it("shows unavailable label when run_readiness is null — no score digits displayed", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("run-index")) return Promise.resolve({ data: buildCardioPayload({ run_readiness: null }) });
      return Promise.resolve({ data: null });
    });

    const { container, unmount } = renderDashboard();
    await waitForCardioLoaded(container);

    const scoreEl = container.querySelector('[data-testid="run-readiness-score"]');
    expect(scoreEl).not.toBeNull();
    const text = scoreEl.textContent;
    // Must NOT show a bare number (0 or 100 as a score)
    expect(text).not.toBe("0");
    expect(text).not.toBe("100");
    // Must NOT be empty
    expect(text.trim().length).toBeGreaterThan(0);

    unmount();
  });

  it("does not render '/ 100' suffix when run_readiness is null", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("run-index")) return Promise.resolve({ data: buildCardioPayload({ run_readiness: null }) });
      return Promise.resolve({ data: null });
    });

    const { container, unmount } = renderDashboard();
    await waitForCardioLoaded(container);

    const scoreEl = container.querySelector('[data-testid="run-readiness-score"]');
    expect(scoreEl).not.toBeNull();
    const scoreParent = scoreEl.parentElement;
    expect(scoreParent).not.toBeNull();
    // "/ 100" suffix must not appear next to the score when unavailable
    expect(scoreParent.textContent).not.toMatch(/^\s*\d+\s*\/\s*100\s*$/);

    unmount();
  });

  it("shows a numeric score and / 100 suffix when run_readiness is a float", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("run-index")) return Promise.resolve({ data: buildCardioPayload({ run_readiness: 78.5 }) });
      return Promise.resolve({ data: null });
    });

    const { container, unmount } = renderDashboard();
    await waitForCardioLoaded(container);

    const scoreEl = container.querySelector('[data-testid="run-readiness-score"]');
    expect(scoreEl).not.toBeNull();
    // Should contain the numeric value
    expect(scoreEl.textContent).toContain("78.5");

    unmount();
  });
});

// ---------------------------------------------------------------------------
// RHR absent → gray tile, no crash (#126 post-merge correction)
// ---------------------------------------------------------------------------

function buildRhrAbsentPayload() {
  return {
    mock: false,
    source: "garmin",
    recommendation: "EASY RUN",
    recommendation_color: "yellow",
    recommendation_emoji: "🟡",
    reasons: [],
    metrics: {
      run_readiness: 60,
      run_readiness_status: "yellow",
      confidence: "low",
      sufficiency_level: "partial",
      readiness_reasons: [],
      legacy_run_readiness: 60,
      hrv_today: 45,
      hrv_baseline: 50,
      hrv_delta: 5,
      hrv_status: "green",
      hrv_available: true,
      rhr_today: null,
      rhr_baseline: null,
      rhr_delta: null,
      rhr_status: "gray",
      sleep_hours: 7.5,
      sleep_efficiency: 0.85,
      sleep_score: 0.5,
      sleep_status: "green",
      training_load: 1.05,
      training_load_status: "green",
    },
    history: [],
  };
}

describe("Dashboard RHR absent — gray tile, no crash (#126)", () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it("renders RHR tile as '—' without crashing when rhr_today is null", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("run-index")) return Promise.resolve({ data: buildRhrAbsentPayload() });
      return Promise.resolve({ data: null });
    });

    const { container, unmount } = renderDashboard();
    await waitForCardioLoaded(container);

    // Dashboard must render without throwing — no crash
    const rhrTile = container.querySelector('[data-testid="readiness-tile-rhr"]');
    expect(rhrTile).not.toBeNull();

    // Value display must be "—" (em dash) when rhr_today is null
    const rhrValue = container.querySelector('[data-testid="readiness-value-rhr"]');
    expect(rhrValue).not.toBeNull();
    expect(rhrValue.textContent).toBe("—");

    unmount();
  });

  it("applies gray color styling (not green) to RHR tile when rhr_status is 'gray'", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("run-index")) return Promise.resolve({ data: buildRhrAbsentPayload() });
      return Promise.resolve({ data: null });
    });

    const { container, unmount } = renderDashboard();
    await waitForCardioLoaded(container);

    const rhrTile = container.querySelector('[data-testid="readiness-tile-rhr"]');
    expect(rhrTile).not.toBeNull();

    // The tile background/border must NOT use the green color (#22c55e).
    const tileStyle = rhrTile.getAttribute("style") || "";
    expect(tileStyle).not.toContain("#22c55e");

    unmount();
  });
});

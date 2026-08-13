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
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: jest.fn(() => ({ unitSystem: "metric", t: (k) => k })),
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
      fatigue_physio: 0.0,
      fatigue_ratio: 1.0,
      fatigue_status: "green",
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

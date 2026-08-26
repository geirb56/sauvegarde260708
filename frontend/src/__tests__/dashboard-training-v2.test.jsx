/**
 * PR #174 — Dashboard Training V2 Migration
 *
 * Tests:
 * 1.  TRIAL/PREMIUM: /training/v2/week called
 * 2.  FREE: /training/v2/week never called
 * 3.  /training/metrics: 0 calls after migration
 * 4.  distance basis: weekly_target.target_km used exclusively
 * 5.  no load_28 / 4 * 1.1 logic
 * 6.  no fallback 80 km
 * 7.  duration basis: target_duration_minutes shown, no fake km, no fake %
 * 8.  Today session source: /training/today
 * 9.  estimated_tss=null: no "0 TSS" in output
 * 10. estimated_tss=0: "0 TSS" is rendered
 * 11. metric / imperial: distances via UnitContext (formatDistance)
 * 12. no extra legacy endpoints introduced
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Dashboard from "@/pages/Dashboard";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

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

// Default: metric system — mutate this object per test to change unitSystem
const mockUseUnitSystem = jest.fn();
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => mockUseUnitSystem(),
}));

// Default subscription: free — reassign mockSubscription per test
const mockUseSubscription = jest.fn();
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => mockUseSubscription(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ─── Fixtures ──────────────────────────────────────────────────────────────────

const INSIGHT_PAYLOAD = {
  week: { sessions: 3, volume_km: 25, actual_duration_minutes: 135 },
  month: { volume_km: 90 },
  run_index: null,
};

const CARDIO_NO_DATA = { no_data: true, connected: false, message: "No data." };

const TODAY_PAYLOAD = {
  status: "success",
  day: "monday",
  adaptation_applied: false,
  readiness: {
    band: "FAVORABLE",
    score: 82,
    confidence: "high",
    sufficiency_level: "sufficient",
    available: true,
    data_source: "garmin",
  },
  planned_session: {
    type: "endurance",
    duration: "45 min",
    details: "Easy pace",
    estimated_tss: 55,
  },
};

const WEEK_V2_DISTANCE = {
  weekly_target: {
    target_basis: "distance",
    target_km: 50,
    target_duration_minutes: null,
  },
};

const WEEK_V2_DURATION = {
  weekly_target: {
    target_basis: "duration",
    target_km: null,
    target_duration_minutes: 180,
  },
};

// ─── Helpers ───────────────────────────────────────────────────────────────────

function buildDefaultMocks(overrides = {}) {
  const defaults = {
    insight: INSIGHT_PAYLOAD,
    rag: null,
    today: TODAY_PAYLOAD,
    cardio: CARDIO_NO_DATA,
    weekV2: null,
  };
  return { ...defaults, ...overrides };
}

function setupAxiosMocks(mocks) {
  axios.get.mockImplementation((url) => {
    if (url.includes("dashboard/insight")) return Promise.resolve({ data: mocks.insight });
    if (url.includes("rag/dashboard")) return mocks.rag ? Promise.resolve({ data: mocks.rag }) : Promise.reject(new Error("no rag"));
    if (url.includes("training/today")) return Promise.resolve({ data: mocks.today });
    if (url.includes("run-index")) return Promise.resolve({ data: mocks.cardio });
    if (url.includes("training/v2/week")) {
      if (mocks.weekV2) return Promise.resolve({ data: mocks.weekV2 });
      return Promise.reject(new Error("not available"));
    }
    if (url.includes("training/metrics")) return Promise.resolve({ data: null });
    return Promise.resolve({ data: null });
  });
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

async function waitForRender() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 80));
  });
}

// ─── Tests ─────────────────────────────────────────────────────────────────────

describe("PR #174 — Dashboard Training V2 Migration", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Re-initialize mock implementations after clearAllMocks
    mockUseUnitSystem.mockReturnValue({ unitSystem: "metric" });
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
  });

  // 1. TRIAL/PREMIUM: /training/v2/week called
  it("1. TRIAL/PREMIUM: calls /training/v2/week", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DISTANCE }));

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.some((u) => u.includes("training/v2/week"))).toBe(true);
    unmount();
  });

  // 2. FREE: /training/v2/week never called
  it("2. FREE: never calls /training/v2/week", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks(buildDefaultMocks());

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.some((u) => u.includes("training/v2/week"))).toBe(false);
    unmount();
  });

  // 3. /training/metrics: 0 calls
  it("3. /training/metrics is never called", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DISTANCE }));

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.filter((u) => u.includes("training/metrics"))).toHaveLength(0);
    unmount();
  });

  // 4. distance basis: weekly target comes from weekly_target.target_km
  it("4. distance basis: displays weekly_target.target_km", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DISTANCE }));

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const card = container.querySelector('[data-testid="weekly-target-card"]');
    expect(card).not.toBeNull();
    const value = container.querySelector('[data-testid="weekly-target-value"]');
    expect(value).not.toBeNull();
    // target_km = 50, metric → "50.0 km"
    expect(value.textContent).toContain("50");
    unmount();
  });

  // 5. no load_28 / 4 * 1.1 logic — verified by static absence + no "80" default
  it("5. no load_28/4*1.1 formula: source code check", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf-8"
    );
    expect(src).not.toMatch(/load_28\s*\/\s*4/);
    expect(src).not.toMatch(/\*\s*1\.1/);
  });

  // 6. no fallback 80 km
  it("6. no fallback 80 km: source code check", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf-8"
    );
    // Must not have ": 80" as a default km value
    expect(src).not.toMatch(/:\s*80\b/);
  });

  // 7a. duration basis: target_duration_minutes shown
  it("7a. duration basis: shows target_duration_minutes, no fake km", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DURATION }));

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const durationSection = container.querySelector('[data-testid="weekly-target-duration"]');
    expect(durationSection).not.toBeNull();
    const value = container.querySelector('[data-testid="weekly-target-value"]');
    expect(value).not.toBeNull();
    // 180 minutes shown
    expect(value.textContent).toContain("180");

    // No fake km conversion — distance section must not render
    const distSection = container.querySelector('[data-testid="weekly-target-distance"]');
    expect(distSection).toBeNull();
    unmount();
  });

  // 7b. duration basis: actual duration comes from DomainActivity-backed insight week stats
  it("7b. duration basis: shows actual minutes and progress", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DURATION }));

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const actual = container.querySelector('[data-testid="weekly-duration-done"]');
    expect(actual).not.toBeNull();
    expect(actual.textContent).toContain("135");

    const progressBar = container.querySelector('[data-testid="weekly-progress-bar"]');
    expect(progressBar).not.toBeNull();
    expect(progressBar.getAttribute("style")).toContain("75%");
    unmount();
  });

  // 8. Today session comes from /training/today (TRIAL/PREMIUM only — PR198)
  it("8. Today session source is /training/today", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks());

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.some((u) => u.includes("training/today"))).toBe(true);

    // Today card must be rendered (from /training/today response)
    const todayCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(todayCard).not.toBeNull();
    unmount();
  });

  // 9. estimated_tss=null: no "0 TSS"
  it("9. estimated_tss=null: no TSS badge rendered", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks(
      buildDefaultMocks({
        today: {
          ...TODAY_PAYLOAD,
          planned_session: { ...TODAY_PAYLOAD.planned_session, estimated_tss: null },
        },
      })
    );

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const todayCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(todayCard).not.toBeNull();
    expect(todayCard.textContent).not.toMatch(/0\s*TSS/);
    unmount();
  });

  // 10. estimated_tss=0: "0 TSS" is rendered (TRIAL/PREMIUM only — PR198)
  it("10. estimated_tss=0: '0 TSS' badge rendered", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(
      buildDefaultMocks({
        today: {
          ...TODAY_PAYLOAD,
          planned_session: { ...TODAY_PAYLOAD.planned_session, estimated_tss: 0 },
        },
      })
    );

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const todayCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(todayCard).not.toBeNull();
    expect(todayCard.textContent).toMatch(/0\s*TSS/);
    unmount();
  });

  // 10b. today recommendation absent: never fabricated as RUN HARD (TRIAL/PREMIUM only — PR198)
  it("10b. today recommendation absent: never shows fabricated RUN HARD", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(
      buildDefaultMocks({
        today: {
          ...TODAY_PAYLOAD,
          fatigue: null,
          readiness: {
            ...TODAY_PAYLOAD.readiness,
            band: "UNAVAILABLE",
            available: false,
            score: null,
          },
        },
      })
    );

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const badge = container.querySelector('[data-testid="today-readiness-badge"]');
    expect(badge).not.toBeNull();
    expect(badge.textContent).not.toContain("RUN HARD");
    unmount();
  });

  // 10c. today unknown readiness uses gray badge, never red by default (TRIAL/PREMIUM only — PR198)
  it("10c. today unknown readiness uses neutral gray", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(
      buildDefaultMocks({
        today: {
          ...TODAY_PAYLOAD,
          readiness: {
            ...TODAY_PAYLOAD.readiness,
            band: "UNAVAILABLE",
            available: false,
            score: null,
          },
        },
      })
    );

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const badge = container.querySelector('[data-testid="today-readiness-badge"]');
    expect(badge).not.toBeNull();
    const style = badge.getAttribute("style") || "";
    expect(style).toContain("rgb(107, 114, 128)");
    expect(style).not.toContain("rgb(239, 68, 68)");
    unmount();
  });

  // 11a. metric: formatDistance in km
  it("11a. metric: weekly target displayed in km", async () => {
    mockUseUnitSystem.mockReturnValue({ unitSystem: "metric" });
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DISTANCE }));

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const value = container.querySelector('[data-testid="weekly-target-value"]');
    expect(value).not.toBeNull();
    expect(value.textContent).toMatch(/km/);
    unmount();
  });

  // 11b. imperial: formatDistance in miles
  it("11b. imperial: weekly target displayed in miles", async () => {
    mockUseUnitSystem.mockReturnValue({ unitSystem: "imperial" });

    // Mock formatDistance to return miles
    const unitsMod = require("@/utils/units");
    jest.spyOn(unitsMod, "formatDistance").mockImplementation((km, opts) => {
      const miles = (km * 0.621371).toFixed(1);
      return `${miles} mi`;
    });

    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DISTANCE }));

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const value = container.querySelector('[data-testid="weekly-target-value"]');
    expect(value).not.toBeNull();
    expect(value.textContent).toMatch(/mi/);

    jest.restoreAllMocks();
    unmount();
  });

  // 12. no extra legacy endpoints
  it("12. no legacy endpoints introduced (subscription/info, run-index, training/today, dashboard/insight only)", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks(buildDefaultMocks());

    const { unmount } = renderDashboard();
    await waitForRender();

    const allowedPatterns = [
      "dashboard/insight",
      "rag/dashboard",
      "training/today",
      "run-index",
    ];

    const calls = axios.get.mock.calls.map(([url]) => url);
    for (const url of calls) {
      const isAllowed = allowedPatterns.some((p) => url.includes(p));
      expect(isAllowed).toBe(true);
    }
    unmount();
  });

  // 12b. RunIndex insufficient remains visible as insufficient
  it.each([
    ["en", "Insufficient data"],
    ["fr", "Données insuffisantes"],
    ["es", "Datos insuficientes"],
  ])("12b. run index insufficient uses translated copy in %s", async (lang, expectedLabel) => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks(
      buildDefaultMocks({
        insight: {
          ...INSIGHT_PAYLOAD,
          run_index: { status: "insufficient", run_index: null, confidence_score: 0 },
        },
      })
    );

    const { container, unmount } = renderDashboard();
    await waitForRender();

    expect(container.textContent).toContain(expectedLabel);
    expect(container.textContent).not.toContain("dashboard.runIndexInsufficient");
    expect(container.textContent).not.toContain("/ 1000");
    unmount();
  });

  // 12c. dashboard visible today consumer no longer depends on legacy fatigue block
  it("12c. source check: no todaySession.fatigue consumer remains", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf-8"
    );
    expect(src).not.toMatch(/todaySession\?*\.fatigue/);
  });

  // 12d. source check: no RUN HARD fallback remains
  it('12d. source check: no "RUN HARD" fallback remains', () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Dashboard.jsx"),
      "utf-8"
    );
    expect(src).not.toContain('|| "RUN HARD"');
  });

  // 13. i18n keys: weeklyTarget, weeklyDone, minutes exist in EN
  it("13. i18n dashboard keys exist in EN", () => {
    const { translations } = require("@/lib/i18n");
    expect(translations.en.dashboard.weeklyTarget).toBeDefined();
    expect(translations.en.dashboard.weeklyDone).toBeDefined();
    expect(translations.en.dashboard.minutes).toBeDefined();
  });

  // 14. i18n keys: weeklyTarget, weeklyDone, minutes exist in FR
  it("14. i18n dashboard keys exist in FR", () => {
    const { translations } = require("@/lib/i18n");
    expect(translations.fr.dashboard.weeklyTarget).toBeDefined();
    expect(translations.fr.dashboard.weeklyDone).toBeDefined();
    expect(translations.fr.dashboard.minutes).toBeDefined();
  });

  // 15. i18n keys: weeklyTarget, weeklyDone, minutes exist in ES
  it("15. i18n dashboard keys exist in ES", () => {
    const { translations } = require("@/lib/i18n");
    expect(translations.es.dashboard.weeklyTarget).toBeDefined();
    expect(translations.es.dashboard.weeklyDone).toBeDefined();
    expect(translations.es.dashboard.minutes).toBeDefined();
  });

  // 16. no raw i18n keys visible in rendered output (duration basis)
  it("16. no raw dashboard i18n keys rendered (duration basis)", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosMocks(buildDefaultMocks({ weekV2: WEEK_V2_DURATION }));

    const { container, unmount } = renderDashboard();
    await waitForRender();

    const html = container.innerHTML;
    expect(html).not.toContain("dashboard.weeklyTarget");
    expect(html).not.toContain("dashboard.weeklyDone");
    expect(html).not.toContain("dashboard.minutes");
    unmount();
  });
});

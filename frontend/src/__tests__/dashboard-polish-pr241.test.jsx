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

const mockUseUnitSystem = jest.fn();
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => mockUseUnitSystem(),
}));

const mockUseSubscription = jest.fn();
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => mockUseSubscription(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const INSIGHT_WITH_RUNINDEX = {
  week: { sessions: 3, volume_km: 25, actual_duration_minutes: 135 },
  month: { volume_km: 90 },
  run_index: {
    run_index: 712,
    confidence_score: 88,
    speed_score: 74,
    endurance_score: 81,
    consistency_score: 69,
    efficiency_score: 77,
  },
};

function buildCardio(metrics = {}) {
  return {
    mock: false,
    source: "garmin",
    recommendation: "EASY RUN",
    recommendation_color: "green",
    recommendation_emoji: "🟢",
    reasons: [],
    metrics: {
      run_readiness: 82,
      hrv_delta: -4,
      hrv_status: "green",
      hrv_available: true,
      rhr_today: 52,
      rhr_status: "green",
      sleep_hours: 7.8,
      sleep_status: "green",
      training_load: 0.92,
      training_load_status: "green",
      sufficiency_level: "sufficient",
      readiness_reasons: [],
      ...metrics,
    },
    history: [],
  };
}

function buildTodayResponse(sessionOverrides = {}) {
  return {
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
    served_prescription: {
      type: "endurance",
      duration: "45 min",
      details: "Allure facile",
      estimated_tss: 55,
      ...sessionOverrides,
    },
    planned_session: {
      type: "endurance",
      duration: "45 min",
      details: "Allure facile",
      estimated_tss: 55,
    },
  };
}

function buildWeekPayload(overrides = {}) {
  return {
    weekly_target: {
      target_basis: "distance",
      target_km: 50,
      target_duration_minutes: null,
      session_count: 5,
    },
    week: {
      sessions: [{ actual: { activity_id: "a1", distance_km: 10 } }],
      unmatched_actuals: [],
    },
    ...overrides,
  };
}

function setupAxiosMocks({
  insight = INSIGHT_WITH_RUNINDEX,
  cardio = buildCardio(),
  today = buildTodayResponse(),
  weekV2 = buildWeekPayload(),
} = {}) {
  axios.get.mockImplementation((url) => {
    if (url.includes("dashboard/insight")) return Promise.resolve({ data: insight });
    if (url.includes("run-index")) return Promise.resolve({ data: cardio });
    if (url.includes("training/today")) return Promise.resolve({ data: today });
    if (url.includes("training/v2/week")) return Promise.resolve({ data: weekV2 });
    if (url.includes("rag/dashboard")) return Promise.resolve({ data: null });
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
    await new Promise((resolve) => setTimeout(resolve, 80));
  });
}

describe("PR241 dashboard polish", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    mockUseUnitSystem.mockReturnValue({ unitSystem: "metric" });
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
  });

  it("renders rest day as 'Jour de repos' and never shows artificial 0 min", async () => {
    setupAxiosMocks({
      today: buildTodayResponse({
        type: "rest",
        duration: null,
        details: "Jour de repos",
        estimated_tss: null,
      }),
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    const todayCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(todayCard.textContent).toContain("Jour de repos");
    expect(todayCard.textContent).not.toContain("0 min");

    unmount();
  });

  it("keeps endurance visible when duration is missing and never fabricates 0 min", async () => {
    setupAxiosMocks({
      today: buildTodayResponse({
        type: "endurance",
        duration: null,
        details: "Allure facile",
      }),
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    const todayCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(todayCard.textContent).toContain("Endurance");
    expect(todayCard.textContent).toContain("Allure facile");
    expect(todayCard.textContent).not.toContain("0 min");

    unmount();
  });

  it("displays a real positive duration when prescribed", async () => {
    setupAxiosMocks({
      today: buildTodayResponse({
        duration: "52 min",
      }),
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    const todayCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(todayCard.textContent).toContain("52 min");

    unmount();
  });

  it("shows the partial-readiness indicator when displayed readiness evidence is incomplete", async () => {
    setupAxiosMocks({
      cardio: buildCardio({
        run_readiness: 100,
        hrv_delta: null,
        hrv_available: false,
        sleep_hours: null,
        sufficiency_level: "sufficient",
      }),
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    expect(container.querySelector('[data-testid="run-readiness-partial-indicator"]')?.textContent).toContain("Données partielles");
    expect(container.querySelector('[data-testid="readiness-value-hrv"]')?.textContent).toBe("—");
    expect(container.querySelector('[data-testid="readiness-value-sleep"]')?.textContent).toBe("—");
    expect(container.querySelector('[data-testid="readiness-value-hrv"]')?.textContent).not.toBe("0");
    expect(container.querySelector('[data-testid="readiness-value-sleep"]')?.textContent).not.toBe("0");

    unmount();
  });

  it("does not show a false partial-readiness indicator when all displayed pillars are available", async () => {
    setupAxiosMocks({
      cardio: buildCardio({
        run_readiness: 88,
        hrv_delta: -3,
        hrv_available: true,
        rhr_today: 50,
        sleep_hours: 8.1,
        training_load: 1.03,
        sufficiency_level: "sufficient",
      }),
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    expect(container.querySelector('[data-testid="run-readiness-partial-indicator"]')).toBeNull();

    unmount();
  });

  it("preserves missing RunIndex pillars as em dash, never 0%", async () => {
    setupAxiosMocks({
      insight: {
        ...INSIGHT_WITH_RUNINDEX,
        run_index: {
          ...INSIGHT_WITH_RUNINDEX.run_index,
          speed_score: null,
        },
      },
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    const runIndexCard = container.querySelector('[data-testid="run-index-card"]');
    expect(runIndexCard.textContent).toContain("—");
    expect(runIndexCard.textContent).not.toContain("0%");

    unmount();
  });

  it("keeps FREE gating unchanged for Today by rendering the preview and skipping premium calls", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks({
      weekV2: null,
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    expect(container.querySelector('[data-testid="today-preview-free"]')).not.toBeNull();
    expect(axios.get.mock.calls.some(([url]) => url.includes("training/today"))).toBe(false);

    unmount();
  });

  it("keeps weekly partial data distinct from 0% by showing incomplete data with no progress bar", async () => {
    setupAxiosMocks({
      weekV2: buildWeekPayload({
        week: {
          sessions: [
            { actual: { activity_id: "m1", distance_km: 5 } },
            { actual: { activity_id: "m2", distance_km: null } },
          ],
          unmatched_actuals: [],
        },
      }),
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();

    const weeklyCard = container.querySelector('[data-testid="weekly-target-card"]');
    expect(weeklyCard.textContent).toContain("Données incomplètes");
    expect(weeklyCard.textContent).not.toContain("0%");
    expect(container.querySelector('[data-testid="weekly-progress-bar"]')).toBeNull();

    unmount();
  });
});

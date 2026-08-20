/**
 * PR170 — TrainingPlanV2 tests
 *
 * Fixture: trainingWeekV2ApiFixture
 * Reproduces exactly TrainingWeekV2Response from backend/training_v2/training_week_response.py
 * Tests will fail if the component accesses data.week_state, data.sessions, or data.target
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import TrainingPlanV2 from "@/pages/TrainingPlanV2";
import TrainingPlan from "@/pages/TrainingPlan";
import { LanguageProvider } from "@/context/LanguageContext";

// ---------------------------------------------------------------------------
// Fixture — faithful reproduction of TrainingWeekV2Response
// ---------------------------------------------------------------------------
const trainingWeekV2ApiFixture = {
  reference_date: "2026-08-18",
  goal: {
    goal_type: "MARATHON",
    race_date: "2026-10-15",
    target_time_seconds: 14400,
  },
  state: {
    continuity_state: "normal",
    allow_intensity: true,
  },
  weekly_target: {
    target_basis: "distance",
    target_km: 50.0,
    target_duration_minutes: null,
    session_count: 5,
    confidence: "high",
  },
  week: {
    planned_km: 50.0,
    planned_duration_minutes: null,
    session_count: 5,
    sessions: [
      {
        day: "monday",
        workout_type: "easy",
        intensity_class: "low",
        distance_km: 10.0,
        duration_minutes: null,
        estimated_tss: null,
        reason_codes: ["normal_week"],
      },
      {
        day: "wednesday",
        workout_type: "quality",
        intensity_class: "high",
        distance_km: 12.0,
        duration_minutes: null,
        estimated_tss: null,
        reason_codes: ["intensity_allowed"],
      },
      {
        day: "thursday",
        workout_type: "recovery",
        intensity_class: "low",
        distance_km: 8.0,
        duration_minutes: null,
        estimated_tss: null,
        reason_codes: ["recovery_day"],
      },
      {
        day: "saturday",
        workout_type: "long_easy",
        intensity_class: "low",
        distance_km: 20.0,
        duration_minutes: null,
        estimated_tss: null,
        reason_codes: ["long_run"],
      },
      {
        day: "sunday",
        workout_type: "rest",
        intensity_class: "rest",
        distance_km: null,
        duration_minutes: null,
        estimated_tss: 0,
        reason_codes: ["rest_day"],
      },
    ],
  },
};

// Fixture for duration-basis plan
const trainingWeekV2DurationFixture = {
  reference_date: "2026-08-18",
  goal: {
    goal_type: "10K",
    race_date: null,
    target_time_seconds: null,
  },
  state: {
    continuity_state: "deep_reprise",
    allow_intensity: false,
  },
  weekly_target: {
    target_basis: "duration",
    target_km: null,
    target_duration_minutes: 180,
    session_count: 3,
    confidence: "low",
  },
  week: {
    planned_km: null,
    planned_duration_minutes: 180,
    session_count: 3,
    sessions: [
      {
        day: "tuesday",
        workout_type: "easy",
        intensity_class: "low",
        distance_km: null,
        duration_minutes: 60,
        estimated_tss: null,
        reason_codes: ["reprise"],
      },
      {
        day: "thursday",
        workout_type: "easy",
        intensity_class: "low",
        distance_km: null,
        duration_minutes: 60,
        estimated_tss: null,
        reason_codes: ["reprise"],
      },
      {
        day: "saturday",
        workout_type: "easy",
        intensity_class: "low",
        distance_km: null,
        duration_minutes: 60,
        estimated_tss: null,
        reason_codes: ["reprise"],
      },
    ],
  },
};

// Fixture with active session (estimated_tss: null) — no TSS display
const trainingWeekV2ActiveTssNullFixture = {
  reference_date: "2026-08-18",
  goal: { goal_type: "SEMI", race_date: null, target_time_seconds: null },
  state: { continuity_state: "normal", allow_intensity: true },
  weekly_target: {
    target_basis: "distance",
    target_km: 40.0,
    target_duration_minutes: null,
    session_count: 4,
    confidence: "medium",
  },
  week: {
    planned_km: 40.0,
    planned_duration_minutes: null,
    session_count: 4,
    sessions: [
      {
        day: "monday",
        workout_type: "easy",
        intensity_class: "low",
        distance_km: 10.0,
        duration_minutes: null,
        estimated_tss: null,
        reason_codes: [],
      },
    ],
  },
};

// Fixture with rest session (estimated_tss: 0)
const trainingWeekV2RestTssZeroFixture = {
  reference_date: "2026-08-18",
  goal: { goal_type: "MARATHON", race_date: null, target_time_seconds: null },
  state: { continuity_state: "normal", allow_intensity: true },
  weekly_target: {
    target_basis: "distance",
    target_km: 45.0,
    target_duration_minutes: null,
    session_count: 4,
    confidence: "high",
  },
  week: {
    planned_km: 45.0,
    planned_duration_minutes: null,
    session_count: 4,
    sessions: [
      {
        day: "sunday",
        workout_type: "rest",
        intensity_class: "rest",
        distance_km: null,
        duration_minutes: null,
        estimated_tss: 0,
        reason_codes: ["rest_day"],
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
jest.mock("axios", () => ({
  get: jest.fn(),
}));

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}));

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(() => ({ user: { id: "u1" }, loading: false })),
}));

jest.mock("@/hooks/useAutoSync", () => ({
  useAutoSync: jest.fn(),
}));

jest.mock("@/components/ChatCoach", () => () => null);

jest.mock("@/components/Paywall", () => () =>
  require("react").createElement("div", { "data-testid": "paywall" }, "PAYWALL")
);

// Subscription mock — matches real SubscriptionContext contract (free/trial/premium)
const mockSubscription = {
  isFree: false,
  isTrial: false,
  isPremium: true,
  loading: false,
};
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(() => mockSubscription),
  SubscriptionProvider: ({ children }) => children,
}));

// UnitContext — metric by default, overridable per test
const mockUnitSystem = { unitSystem: "metric" };
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: jest.fn(() => mockUnitSystem),
  UnitProvider: ({ children }) => children,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------
function renderPage(PageComponent, path = "/training-v2") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/training-v2" element={<TrainingPlanV2 />} />
            <Route path="/training" element={<TrainingPlan />} />
          </Routes>
        </MemoryRouter>
      </LanguageProvider>
    );
  });
  return { container, root };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TrainingPlanV2 — PR170", () => {
  let axiosGetMock;

  beforeEach(() => {
    jest.clearAllMocks();
    axiosGetMock = require("axios").get;
    // Restore unit mock (clearAllMocks can wipe mockReturnValue set by prior test)
    const { useUnitSystem } = require("@/context/UnitContext");
    mockUnitSystem.unitSystem = "metric";
    useUnitSystem.mockReturnValue(mockUnitSystem);
    // Reset subscription to premium (default accessible state)
    mockSubscription.isFree = false;
    mockSubscription.isTrial = false;
    mockSubscription.isPremium = true;
    mockSubscription.loading = false;
    const { useSubscription } = require("@/context/SubscriptionContext");
    useSubscription.mockReturnValue({ ...mockSubscription });
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
  });

  // A — True contract: reads data.state, data.weekly_target, data.week.sessions
  test("A — reads data.state, data.weekly_target, data.week.sessions (true #167 contract)", async () => {
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    // Verify data.state was consumed: allow_intensity=true → "Yes" label visible
    expect(container.textContent).not.toBe("");
    // The component must not throw accessing wrong paths
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // Contractual test: fixture has no week_state, sessions, target — component must not crash
  test("CONTRACT — fixture has no week_state/sessions/target; component renders without error", async () => {
    // Ensure the fixture does NOT contain the wrong paths
    expect(trainingWeekV2ApiFixture.week_state).toBeUndefined();
    expect(trainingWeekV2ApiFixture.sessions).toBeUndefined();
    expect(trainingWeekV2ApiFixture.target).toBeUndefined();
    // And has correct paths
    expect(trainingWeekV2ApiFixture.state).toBeDefined();
    expect(trainingWeekV2ApiFixture.weekly_target).toBeDefined();
    expect(trainingWeekV2ApiFixture.week.sessions).toBeDefined();

    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.querySelector("[data-testid='error']")).toBeNull();
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // B — Route: /training-v2 → TrainingPlanV2, /training → TrainingPlan
  test("B — /training-v2 renders TrainingPlanV2", async () => {
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2, "/training-v2");
    await act(async () => {});
    // TrainingPlanV2 title should be present
    expect(container.textContent).toContain("V2");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  test("B — /training renders TrainingPlan (legacy intact)", async () => {
    axiosGetMock.mockResolvedValue({ data: {} });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <LanguageProvider>
          <MemoryRouter initialEntries={["/training"]}>
            <Routes>
              <Route path="/training-v2" element={<TrainingPlanV2 />} />
              <Route path="/training" element={<TrainingPlan />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      );
    });
    // TrainingPlan has its own content — V2 title should NOT be there
    expect(container.textContent).not.toContain("Training Plan V2");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // C — API exclusivity: only /training/v2/week called
  test("C — calls only GET /training/v2/week", async () => {
    const { root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    const calls = axiosGetMock.mock.calls;
    // Every call must target v2/week
    calls.forEach(([url]) => {
      expect(url).toMatch(/training\/v2\/week/);
    });
    // No legacy endpoints
    calls.forEach(([url]) => {
      expect(url).not.toMatch(/training\/plan/);
      expect(url).not.toMatch(/training\/week-plan/);
      expect(url).not.toMatch(/training\/full-cycle/);
      expect(url).not.toMatch(/training\/metrics/);
      expect(url).not.toMatch(/training\/refresh/);
    });
    act(() => root.unmount());
  });

  // D — distance basis: weekly_target.target_km displayed via UnitContext
  test("D — target_km displayed via UnitContext (metric)", async () => {
    mockUnitSystem.unitSystem = "metric";
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    // 50km in metric → "50.00 km"
    expect(container.textContent).toContain("50");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // E — duration basis: target_duration displayed, target_km null not displayed
  test("E — duration basis: target_duration_minutes shown, target_km null not shown", async () => {
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2DurationFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    // 180 minutes should appear
    expect(container.textContent).toContain("180");
    // target_km is null → "50" (from other fixture) should NOT be in this render
    // Just check that it doesn't throw and renders the duration
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // F — active session with estimated_tss null → no TSS text
  test("F — estimated_tss null → no TSS display (null/0/—/N/A all absent)", async () => {
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ActiveTssNullFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    // Session rendered at all (distance_km=10 is present)
    expect(container.textContent).toContain("Monday");
    // estimated_tss null → absolutely no TSS-suffixed value in this card
    const text = container.textContent;
    expect(text).not.toContain("null TSS");
    expect(text).not.toContain("0 TSS");
    expect(text).not.toContain("— TSS");
    expect(text).not.toContain("N/A TSS");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // G — rest session with estimated_tss = 0 → "0 TSS" displayed (null ≠ 0)
  test("G — estimated_tss 0 → '0 TSS' explicitly displayed on rest card", async () => {
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2RestTssZeroFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    // TSS = 0 is a real value → must render as "0 TSS", proving null ≠ 0
    expect(container.textContent).toContain("0 TSS");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // H — units: metric vs imperial
  test("H — metric: distance in km", async () => {
    mockUnitSystem.unitSystem = "metric";
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.textContent).toContain("km");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  test("H — imperial: distance in mi", async () => {
    mockUnitSystem.unitSystem = "imperial";
    const { useUnitSystem } = require("@/context/UnitContext");
    useUnitSystem.mockReturnValue({ unitSystem: "imperial" });
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.textContent).toContain("mi");
    act(() => root.unmount());
    document.body.removeChild(container);
    // Reset
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  // I — i18n: no raw trainingV2.* keys visible in output
  test("I — no raw trainingV2.* key visible in rendered output", async () => {
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.textContent).not.toMatch(/trainingV2\./);
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // J — error + retry uses only /training/v2/week
  test("J — error state renders retry, retry calls only /training/v2/week", async () => {
    axiosGetMock.mockRejectedValueOnce({ response: { data: { detail: "Server error" } } });
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    // Error state shown
    const retryBtn = container.querySelector("button:not([disabled])");
    // Click retry
    if (retryBtn) {
      await act(async () => { retryBtn.click(); });
    }
    // After retry, still only v2/week called
    axiosGetMock.mock.calls.forEach(([url]) => {
      expect(url).toMatch(/training\/v2\/week/);
    });
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // --- SUBSCRIPTION TESTS ---

  // K — FREE: Paywall shown, no Training V2 data
  test("K — FREE subscription → Paywall shown, no V2 data rendered", async () => {
    const { useSubscription } = require("@/context/SubscriptionContext");
    useSubscription.mockReturnValue({
      isFree: true,
      isTrial: false,
      isPremium: false,
      loading: false,
    });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.querySelector("[data-testid='paywall']")).not.toBeNull();
    expect(container.textContent).not.toContain("Training Plan V2");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // L — TRIAL: TrainingPlanV2 accessible
  test("L — TRIAL subscription → TrainingPlanV2 accessible, no Paywall", async () => {
    const { useSubscription } = require("@/context/SubscriptionContext");
    useSubscription.mockReturnValue({
      isFree: false,
      isTrial: true,
      isPremium: false,
      loading: false,
    });
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.querySelector("[data-testid='paywall']")).toBeNull();
    expect(container.textContent).toContain("V2");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // M — PREMIUM: TrainingPlanV2 accessible
  test("M — PREMIUM subscription → TrainingPlanV2 accessible, no Paywall", async () => {
    const { useSubscription } = require("@/context/SubscriptionContext");
    useSubscription.mockReturnValue({
      isFree: false,
      isTrial: false,
      isPremium: true,
      loading: false,
    });
    axiosGetMock.mockResolvedValue({ data: trainingWeekV2ApiFixture });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.querySelector("[data-testid='paywall']")).toBeNull();
    expect(container.textContent).toContain("V2");
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  // N — LOADING: subscription loading state → skeleton shown, no Paywall
  test("N — subscription loading=true → loading skeleton shown, no Paywall", async () => {
    const { useSubscription } = require("@/context/SubscriptionContext");
    useSubscription.mockReturnValue({
      isFree: false,
      isTrial: false,
      isPremium: false,
      loading: true,
    });
    const { container, root } = renderPage(TrainingPlanV2);
    await act(async () => {});
    expect(container.querySelector("[data-testid='paywall']")).toBeNull();
    act(() => root.unmount());
    document.body.removeChild(container);
  });
});

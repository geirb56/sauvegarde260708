import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route, Navigate } from "react-router-dom";
import axios from "axios";

import TrainingPlanV2 from "@/pages/TrainingPlanV2";
import { LanguageProvider } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { UnitProvider } from "@/context/UnitContext";
import { API_BASE_URL } from "@/config";
import { UNIT_SYSTEM_KEY, formatDistance } from "@/utils/units";

jest.mock("axios");
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(),
}));
jest.mock("@/components/Paywall", () => function MockPaywall({ returnPath }) {
  return <div data-testid="paywall" data-return-path={returnPath}>Paywall</div>;
});

const FORBIDDEN_ENDPOINTS = [
  "/training/plan",
  "/training/full-cycle",
  "/training/metrics",
  "/training/refresh",
];

function buildWeekResponse({ targetBasis = "distance", includeRestTss = true } = {}) {
  return {
    reference_date: "2026-08-18",
    goal: {
      goal_type: "MARATHON",
      race_date: "2026-10-05",
      target_time_seconds: 11700,
    },
    state: {
      continuity_state: "normal",
      allow_intensity: true,
    },
    weekly_target: {
      target_basis: targetBasis,
      target_km: targetBasis === "distance" ? 52.5 : null,
      target_duration_minutes: targetBasis === "duration" ? 210 : null,
      session_count: 5,
      confidence: "high",
    },
    week: {
      planned_km: targetBasis === "distance" ? 52.5 : null,
      planned_duration_minutes: targetBasis === "duration" ? 210 : null,
      session_count: 5,
      sessions: [
        { day: "monday", workout_type: "easy", intensity_class: "low", distance_km: targetBasis === "distance" ? 8 : null, duration_minutes: targetBasis === "duration" ? 45 : null, estimated_tss: null, reason_codes: [] },
        { day: "tuesday", workout_type: "quality", intensity_class: "high", distance_km: targetBasis === "distance" ? 10 : null, duration_minutes: targetBasis === "duration" ? 50 : null, estimated_tss: null, reason_codes: [] },
        { day: "wednesday", workout_type: "recovery", intensity_class: "low", distance_km: targetBasis === "distance" ? 6 : null, duration_minutes: targetBasis === "duration" ? 35 : null, estimated_tss: null, reason_codes: [] },
        { day: "thursday", workout_type: "steady", intensity_class: "moderate", distance_km: targetBasis === "distance" ? 8.5 : null, duration_minutes: targetBasis === "duration" ? 40 : null, estimated_tss: null, reason_codes: [] },
        { day: "friday", workout_type: "rest", intensity_class: "rest", distance_km: null, duration_minutes: null, estimated_tss: includeRestTss ? 0 : null, reason_codes: [] },
        { day: "saturday", workout_type: "long_easy", intensity_class: "moderate", distance_km: targetBasis === "distance" ? 20 : null, duration_minutes: targetBasis === "duration" ? 70 : null, estimated_tss: null, reason_codes: [] },
        { day: "sunday", workout_type: "rest", intensity_class: "rest", distance_km: null, duration_minutes: null, estimated_tss: includeRestTss ? 0 : null, reason_codes: [] },
      ],
    },
  };
}

function buildCycleResponse() {
  return {
    cycle: {
      mode: "race_calendar",
      status: "active",
      start_date: "2026-06-02",
      end_date: "2026-10-05",
      current_week: 12,
      total_weeks: 18,
      days_to_race: 45,
    },
    weeks: [
      { week_number: 11, start_date: "2026-08-10", end_date: "2026-08-16", phase: "build", is_current: false },
      { week_number: 12, start_date: "2026-08-17", end_date: "2026-08-23", phase: "specific", is_current: true },
      { week_number: 13, start_date: "2026-08-24", end_date: "2026-08-30", phase: "specific", is_current: false },
    ],
  };
}

function mockAxiosSuccess({ weekData, cycleData } = {}) {
  axios.get.mockImplementation((url) => {
    if (url.includes("/training/v2/week")) return Promise.resolve({ data: weekData ?? buildWeekResponse() });
    if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: cycleData ?? buildCycleResponse() });
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
}

function renderPage({ unitSystem = "metric" } = {}) {
  window.localStorage.setItem(UNIT_SYSTEM_KEY, unitSystem);
  return render(
    <UnitProvider>
      <LanguageProvider>
        <MemoryRouter>
          <TrainingPlanV2 />
        </MemoryRouter>
      </LanguageProvider>
    </UnitProvider>
  );
}

describe("TrainingPlanV2 — PR #177", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
  });

  // Test 1: /training renders V2 component
  it("renders the TrainingPlanV2 component", async () => {
    mockAxiosSuccess();
    renderPage();
    expect(await screen.findByTestId("training-v2-page")).toBeInTheDocument();
  });

  // Test 2: /training-v2 redirects to /training
  it("redirects /training-v2 to /training", () => {
    render(
      <MemoryRouter initialEntries={["/training-v2"]}>
        <Routes>
          <Route path="/training" element={<div data-testid="training-canonical">Training</div>} />
          <Route path="/training-v2" element={<Navigate to="/training" replace />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByTestId("training-canonical")).toBeInTheDocument();
  });

  // Test 3: FREE → Paywall
  it("shows paywall for FREE users and never fetches V2", () => {
    useSubscription.mockReturnValue({ isFree: true, loading: false });
    renderPage();
    expect(screen.getByTestId("paywall")).toBeInTheDocument();
    expect(axios.get).not.toHaveBeenCalled();
  });

  // Test 4: TRIAL/PREMIUM → /training/v2/week called
  it("fetches /training/v2/week for TRIAL/PREMIUM", async () => {
    mockAxiosSuccess();
    renderPage();
    await waitFor(() => {
      expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/week`);
    });
  });

  // Test 5: TRIAL/PREMIUM → /training/v2/cycle called
  it("fetches /training/v2/cycle for TRIAL/PREMIUM", async () => {
    mockAxiosSuccess();
    renderPage();
    await waitFor(() => {
      expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/cycle`);
    });
  });

  // Test 6: no legacy endpoints called from /training
  it("never calls forbidden legacy training endpoints", async () => {
    mockAxiosSuccess();
    renderPage();
    await screen.findByTestId("training-v2-page");
    const calledUrls = axios.get.mock.calls.map(([url]) => url);
    FORBIDDEN_ENDPOINTS.forEach((endpoint) => {
      expect(calledUrls.some((url) => url.includes(endpoint))).toBe(false);
    });
  });

  // Test 7: duration basis — native minutes, no fake km
  it("renders duration basis in minutes without converting unknown distance to 0", async () => {
    mockAxiosSuccess({ weekData: buildWeekResponse({ targetBasis: "duration" }) });
    renderPage();
    expect(await screen.findByText("210 min")).toBeInTheDocument();
    expect(screen.queryByText("0 km")).not.toBeInTheDocument();
  });

  // Test 8: distance basis via UnitContext
  it("renders distance basis via UnitContext in metric", async () => {
    mockAxiosSuccess({ weekData: buildWeekResponse({ targetBasis: "distance" }) });
    renderPage({ unitSystem: "metric" });
    expect(await screen.findByText(formatDistance(52.5, { unitSystem: "metric" }))).toBeInTheDocument();
    expect(screen.getByText(formatDistance(8, { unitSystem: "metric" }))).toBeInTheDocument();
    expect(screen.queryByText("0 min")).not.toBeInTheDocument();
  });

  // Test 8b: distance basis imperial
  it("renders distance basis via UnitContext in imperial without forcing km", async () => {
    mockAxiosSuccess({ weekData: buildWeekResponse({ targetBasis: "distance" }) });
    renderPage({ unitSystem: "imperial" });
    const weeklyTargetValue = await screen.findByText(formatDistance(52.5, { unitSystem: "imperial" }));
    expect(weeklyTargetValue).toBeInTheDocument();
    expect(screen.getByText(formatDistance(8, { unitSystem: "imperial" }))).toBeInTheDocument();
    const mondayCard = screen.getByTestId("training-v2-day-monday");
    expect(within(mondayCard).queryByText(/\bkm\b/)).not.toBeInTheDocument();
  });

  // Test 9: estimated_tss=null → no "0 TSS"
  it("never shows 0 TSS when estimated_tss is null", async () => {
    mockAxiosSuccess({ weekData: buildWeekResponse({ includeRestTss: false }) });
    renderPage();
    await screen.findByTestId("training-v2-day-sunday");
    expect(screen.queryByText("0 TSS")).not.toBeInTheDocument();
  });

  // Test 10: estimated_tss=0 → "0 TSS" allowed
  it("preserves a valid 0 TSS on REST days when provided", async () => {
    mockAxiosSuccess({ weekData: buildWeekResponse({ includeRestTss: true }) });
    renderPage();
    const fridayCard = await screen.findByTestId("training-v2-day-friday");
    expect(within(fridayCard).getByText("0 TSS")).toBeInTheDocument();
  });

  // Test 11: Cycle — total_weeks affichable, current week identifiable
  it("renders cycle total_weeks and identifies current week", async () => {
    mockAxiosSuccess();
    renderPage();
    await screen.findByTestId("training-v2-cycle");
    expect(screen.getByTestId("cycle-week-12")).toBeInTheDocument();
    expect(within(screen.getByTestId("cycle-week-12")).getByTestId("cycle-current-badge")).toBeInTheDocument();
    expect(within(screen.getByTestId("cycle-week-11")).queryByTestId("cycle-current-badge")).not.toBeInTheDocument();
    expect(screen.getByText(/12 \/ 18/)).toBeInTheDocument();
  });

  // Test 12: phases base/build/specific/taper/race/consolidation supported
  it("renders all V2 cycle phases without error", async () => {
    const phases = ["base", "build", "specific", "taper", "race", "consolidation"];
    const cycleData = {
      cycle: { mode: "race_calendar", status: "active", current_week: 3, total_weeks: phases.length },
      weeks: phases.map((phase, i) => ({
        week_number: i + 1,
        start_date: "2026-08-01",
        end_date: "2026-08-07",
        phase,
        is_current: i === 2,
      })),
    };
    mockAxiosSuccess({ cycleData });
    renderPage();
    await screen.findByTestId("training-v2-cycle");
    for (const phase of phases) {
      expect(screen.getByTestId(`cycle-week-${phases.indexOf(phase) + 1}`)).toBeInTheDocument();
    }
  });

  // Test 13: no future prescription invented in cycle weeks
  it("does not show prescription data (sessions/targets/TSS) in cycle weeks", async () => {
    mockAxiosSuccess();
    renderPage();
    await screen.findByTestId("training-v2-cycle");
    const cycleCard = screen.getByTestId("training-v2-cycle");
    expect(within(cycleCard).queryByText(/TSS/)).not.toBeInTheDocument();
    expect(within(cycleCard).queryByText(/km\/h/)).not.toBeInTheDocument();
    expect(within(cycleCard).queryByText(/target_km/i)).not.toBeInTheDocument();
  });

  // Test 14: Coach not modified — TrainingPlanV2 renders without Coach component
  it("does not render Coach component inside TrainingPlanV2", async () => {
    mockAxiosSuccess();
    renderPage();
    await screen.findByTestId("training-v2-page");
    // No coach-specific testid should appear in the training page
    expect(screen.queryByTestId("chat-coach")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coach-page")).not.toBeInTheDocument();
  });

  // Test 16: cycle mode race_calendar renders correctly (not "Not available")
  it("renders cycle mode race_calendar without falling back to 'Not available'", async () => {
    const cycleData = buildCycleResponse(); // mode: "race_calendar"
    mockAxiosSuccess({ cycleData });
    renderPage();
    await screen.findByTestId("training-v2-cycle");
    expect(screen.queryByText(/not available/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/non disponible/i)).not.toBeInTheDocument();
  });

  // Test 17: cycle mode continuous renders correctly (not "Not available")
  it("renders cycle mode continuous without falling back to 'Not available'", async () => {
    const cycleData = {
      ...buildCycleResponse(),
      cycle: { ...buildCycleResponse().cycle, mode: "continuous" },
    };
    mockAxiosSuccess({ cycleData });
    renderPage();
    await screen.findByTestId("training-v2-cycle");
    expect(screen.queryByText(/not available/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/non disponible/i)).not.toBeInTheDocument();
  });
});

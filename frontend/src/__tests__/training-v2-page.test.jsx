import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

function weekData() {
  return {
    reference_date: "2026-08-25",
    weekly_target: {
      target_basis: "distance",
      target_km: 50,
      target_duration_minutes: null,
      session_count: 5,
      confidence: "high",
    },
    week: {
      sessions: [
        { day: "monday", workout_type: "easy", distance_km: 8, duration_minutes: 45, estimated_tss: null },
        { day: "tuesday", workout_type: "quality", distance_km: 10, duration_minutes: 50, estimated_tss: null },
        { day: "wednesday", workout_type: "recovery", distance_km: 6, duration_minutes: 35, estimated_tss: null },
        { day: "thursday", workout_type: "steady", distance_km: 8, duration_minutes: 42, estimated_tss: null },
        { day: "friday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: 0 },
        { day: "saturday", workout_type: "long_easy", distance_km: 18, duration_minutes: 90, estimated_tss: null },
        { day: "sunday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: 0 },
      ],
    },
  };
}

function cycleData() {
  return {
    goal: { goal_type: "marathon", race_date: "2026-10-05" },
    cycle: {
      mode: "race_calendar",
      status: "active",
      start_date: "2026-06-02",
      end_date: "2026-10-05",
      current_week: 12,
      total_weeks: 18,
    },
    weeks: [{ week_number: 12, start_date: "2026-08-17", end_date: "2026-08-23", phase: "specific", is_current: true }],
  };
}

function todayData({ adapted = false } = {}) {
  return {
    status: "success",
    readiness: { band: "EASY" },
    planned_session: { workout_type: "easy", duration_minutes: 45, distance_km: 8, prescription: "45 min easy" },
    original_prescription: { workout_type: "easy", duration_minutes: 45, distance_km: 8, prescription: "45 min easy" },
    adapted_prescription: adapted
      ? { workout_type: "recovery", duration_minutes: 35, distance_km: 6, prescription: "35 min recovery" }
      : { workout_type: "easy", duration_minutes: 45, distance_km: 8, prescription: "45 min easy" },
    adaptive_session: adapted ? { workout_type: "recovery", duration_minutes: 35, distance_km: 6 } : null,
    adaptation_applied: adapted,
    adaptation_reason: adapted ? "MISSING_SLEEP" : "",
  };
}

function pacesData({ confidence = "HIGH" } = {}) {
  return {
    reference_date: "2026-08-25",
    confidence,
    vdot_reference: 44.2,
    paces: confidence === "INSUFFICIENT" ? {
      easy: null,
      marathon: null,
      threshold: null,
      interval: null,
      repetition: null,
    } : {
      easy: { lower: { pace_str: "5:10" }, upper: { pace_str: "5:55" } },
      marathon: { pace_str: "4:58" },
      threshold: { pace_str: "4:35" },
      interval: { lower: { pace_str: "4:00" }, upper: { pace_str: "4:20" } },
      repetition: { pace_str: "3:42" },
    },
  };
}

function mockAxios({ today = todayData(), paces = pacesData(), week = weekData(), cycle = cycleData() } = {}) {
  axios.get.mockImplementation((url) => {
    if (url.includes("/training/today")) return Promise.resolve({ data: today });
    if (url.includes("/training/v2/paces")) return Promise.resolve({ data: paces });
    if (url.includes("/training/v2/week")) return Promise.resolve({ data: week });
    if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: cycle });
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

describe("TrainingPlanV2 — PR196", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
  });

  test("calls required endpoints", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-page");

    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/today`);
    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/paces`);
    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/week`);
    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/cycle`);
  });

  test("never calls forbidden legacy training endpoints", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-page");
    const calledUrls = axios.get.mock.calls.map(([url]) => url);
    FORBIDDEN_ENDPOINTS.forEach((endpoint) => {
      expect(calledUrls.some((url) => String(url).includes(endpoint))).toBe(false);
    });
  });

  test("shows paywall for free users", () => {
    useSubscription.mockReturnValue({ isFree: true, loading: false });
    renderPage();
    expect(screen.getByTestId("paywall")).toBeInTheDocument();
    expect(axios.get).not.toHaveBeenCalled();
  });

  test("renders adapted session clearly", async () => {
    mockAxios({ today: todayData({ adapted: true }) });
    renderPage();
    expect(await screen.findByTestId("today-adapted")).toBeInTheDocument();
    expect(screen.getByText("MISSING_SLEEP")).toBeInTheDocument();
  });

  test("renders non-adapted session without adapted badge", async () => {
    mockAxios({ today: todayData({ adapted: false }) });
    renderPage();
    await screen.findByTestId("training-v2-page");
    expect(screen.queryByTestId("today-adapted")).not.toBeInTheDocument();
  });

  test("renders E/M/T/I/R paces with easy and interval ranges", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-paces");
    expect(screen.getByText("5:10 - 5:55 /km")).toBeInTheDocument();
    expect(screen.getByText("4:58 /km")).toBeInTheDocument();
    expect(screen.getByText("4:35 /km")).toBeInTheDocument();
    expect(screen.getByText("4:00 - 4:20 /km")).toBeInTheDocument();
    expect(screen.getByText("3:42 /km")).toBeInTheDocument();
  });

  test("renders distance basis in metric using km", async () => {
    mockAxios();
    renderPage({ unitSystem: "metric" });
    await screen.findByTestId("training-v2-week");
    expect(screen.getAllByText(formatDistance(8, { unitSystem: "metric" })).length).toBeGreaterThan(0);
  });

  test("renders distance basis in imperial using miles without forced km", async () => {
    mockAxios();
    renderPage({ unitSystem: "imperial" });
    const mileText = formatDistance(8, { unitSystem: "imperial" });
    expect((await screen.findAllByText(mileText)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/\b8(?:\.0+)? km\b/i)).not.toBeInTheDocument();
  });

  test("handles INSUFFICIENT confidence without inventing paces", async () => {
    mockAxios({ paces: pacesData({ confidence: "INSUFFICIENT" }) });
    renderPage();
    await screen.findByTestId("training-v2-paces");
    expect(screen.getByText(/performance/i)).toBeInTheDocument();
    expect(screen.queryByText("5:10 - 5:55 /km")).not.toBeInTheDocument();
  });

  test("keeps page functional if today endpoint fails", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("/training/today")) return Promise.reject(new Error("down"));
      if (url.includes("/training/v2/paces")) return Promise.resolve({ data: pacesData() });
      if (url.includes("/training/v2/week")) return Promise.resolve({ data: weekData() });
      if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: cycleData() });
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });

    renderPage();
    expect(await screen.findByTestId("training-v2-page")).toBeInTheDocument();
  });

  test("estimated_tss null does not render 0 TSS", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-day-monday");
    const mondayCard = screen.getByTestId("training-v2-day-monday");
    expect(mondayCard.textContent).not.toContain("0 TSS");
  });

  test("estimated_tss zero is rendered when provided by backend", async () => {
    mockAxios();
    renderPage();
    const fridayCard = await screen.findByTestId("training-v2-day-friday");
    expect(fridayCard.textContent).toContain("0 TSS");
  });

  test("mobile-first section order is Today -> Paces -> Week -> Cycle", async () => {
    mockAxios();
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    const paces = screen.getByTestId("training-v2-paces");
    const week = screen.getByTestId("training-v2-week");
    const cycle = screen.getByTestId("training-v2-cycle");

    expect(today.compareDocumentPosition(paces) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(paces.compareDocumentPosition(week) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(week.compareDocumentPosition(cycle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("does not display vdot to runner", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-paces");
    expect(screen.queryByText(/VDOT/i)).not.toBeInTheDocument();
  });

  test("cycle current week badge still shown", async () => {
    mockAxios();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("cycle-current-badge")).toBeInTheDocument();
    });
  });

  test("cycle section does not render fake future prescriptions", async () => {
    mockAxios();
    renderPage();
    const cycleCard = await screen.findByTestId("training-v2-cycle");
    expect(cycleCard.textContent).not.toMatch(/target_km/i);
    expect(cycleCard.textContent).not.toMatch(/prescription/i);
    expect(cycleCard.textContent).not.toMatch(/TSS/i);
  });
});

import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import TrainingPlanV2 from "@/pages/TrainingPlanV2";
import { LanguageProvider } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { UnitProvider } from "@/context/UnitContext";
import { API_BASE_URL } from "@/config";
import { UNIT_SYSTEM_KEY, formatDistance } from "@/utils/units";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

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

function weekData({ withSessionIds = false } = {}) {
  return {
    reference_date: "2026-08-25",
    goal: { goal_type: "MARATHON", race_date: "2026-10-05" },
    weekly_target: {
      target_basis: "distance",
      target_km: 50,
      target_duration_minutes: null,
      session_count: 5,
      confidence: "high",
    },
    week: {
      completed_km: 21,
      completed_duration_minutes: null,
      completed_session_count: 2,
      sessions: [
        { day: "monday", workout_type: "easy", distance_km: 8, duration_minutes: 45, estimated_tss: null, ...(withSessionIds ? { session_id: "s-1" } : {}) },
        { day: "tuesday", workout_type: "quality", distance_km: 10, duration_minutes: 50, estimated_tss: null, status: "DONE", ...(withSessionIds ? { workout_id: "w-2" } : {}) },
        { day: "wednesday", workout_type: "recovery", distance_km: 6, duration_minutes: 35, estimated_tss: null, status: "PLANNED" },
        { day: "thursday", workout_type: "steady", distance_km: 8, duration_minutes: 42, estimated_tss: null, status: "MISSED" },
        { day: "friday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null, status: "REST" },
        { day: "saturday", workout_type: "long_easy", distance_km: 18, duration_minutes: 90, estimated_tss: null },
        { day: "sunday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null },
      ],
    },
  };
}

function cycleData({ goalType = "marathon", daysToRace = 39 } = {}) {
  return {
    goal: { goal_type: goalType, race_date: goalType === "maintenance" ? null : "2026-10-05" },
    cycle: {
      mode: goalType === "maintenance" ? "continuous" : "race_calendar",
      status: "active",
      start_date: "2026-06-02",
      end_date: "2026-10-05",
      current_week: 12,
      total_weeks: 18,
      days_to_race: goalType === "maintenance" ? null : daysToRace,
    },
    weeks: [
      { week_number: 11, start_date: "2026-08-10", end_date: "2026-08-16", phase: "build", is_current: false },
      { week_number: 12, start_date: "2026-08-17", end_date: "2026-08-23", phase: "specific", is_current: true },
      { week_number: 13, start_date: "2026-08-24", end_date: "2026-08-30", phase: "specific", is_current: false },
    ],
  };
}

function todayData({ adapted = false, noSession = false } = {}) {
  if (noSession) {
    return {
      status: "no_session",
      message: "No session planned for today",
      date: "2026-08-25",
      day: "Tuesday",
    };
  }

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

function renderPage({ unitSystem = "metric", lang = "en" } = {}) {
  window.localStorage.setItem(UNIT_SYSTEM_KEY, unitSystem);
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
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

describe("TrainingPlanV2 — PR206", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 1024 });
  });

  test("uses only canonical V2 endpoints", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-page");

    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/today`);
    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/paces`);
    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/week`);
    expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/cycle`);

    const calledUrls = axios.get.mock.calls.map(([url]) => url);
    FORBIDDEN_ENDPOINTS.forEach((endpoint) => {
      expect(calledUrls.some((url) => String(url).includes(endpoint))).toBe(false);
    });
  });

  test("shows paywall for free users and skips premium API calls", () => {
    useSubscription.mockReturnValue({ isFree: true, loading: false });
    renderPage();
    expect(screen.getByTestId("paywall")).toBeInTheDocument();
    expect(axios.get).not.toHaveBeenCalled();
  });

  test("renders hierarchy with today first, then week, cycle progress, paces, full cycle", async () => {
    mockAxios();
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    const week = screen.getByTestId("training-v2-week");
    const cycleProgress = screen.getByTestId("training-v2-cycle-progress");
    const paces = screen.getByTestId("training-v2-paces");
    const cycle = screen.getByTestId("training-v2-cycle");

    expect(today.compareDocumentPosition(week) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(week.compareDocumentPosition(cycleProgress) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(cycleProgress.compareDocumentPosition(paces) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(paces.compareDocumentPosition(cycle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("today card keeps adaptation visible but secondary", async () => {
    mockAxios({ today: todayData({ adapted: true }) });
    renderPage();
    expect(await screen.findByTestId("today-adapted")).toBeInTheDocument();
    expect(screen.getByText("MISSING_SLEEP")).toBeInTheDocument();
  });

  test("today card shows clear no-session rest state", async () => {
    mockAxios({ today: todayData({ noSession: true }) });
    renderPage();
    expect(await screen.findByTestId("today-rest-state")).toBeInTheDocument();
  });

  test("week card highlights today and shows distinct states when available", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-week");

    expect(screen.getByTestId("today-highlight-badge")).toBeInTheDocument();
    expect(screen.getByTestId("session-status-done")).toBeInTheDocument();
    expect(screen.getByTestId("session-status-planned")).toBeInTheDocument();
    expect(screen.getAllByTestId("session-status-rest").length).toBeGreaterThan(0);
    expect(screen.getByTestId("session-status-missed")).toBeInTheDocument();
  });

  test("missing session in weekly payload does not show REST badge", async () => {
    const weekWithMissingSunday = weekData();
    weekWithMissingSunday.week.sessions = weekWithMissingSunday.week.sessions.filter((session) => session.day !== "sunday");

    mockAxios({ week: weekWithMissingSunday });
    renderPage();
    await screen.findByTestId("training-v2-week");

    const sundayCard = screen.getByTestId("training-v2-day-sunday");
    expect(within(sundayCard).queryByTestId("session-status-rest")).not.toBeInTheDocument();
    expect(within(sundayCard).getAllByText("No session").length).toBeGreaterThan(0);
  });

  test("unknown distance, duration and null tss are not shown as zero", async () => {
    mockAxios();
    renderPage();
    const fridayCard = await screen.findByTestId("training-v2-day-friday");
    expect(fridayCard.textContent).not.toMatch(/0\s*km/i);
    expect(fridayCard.textContent).not.toMatch(/0\s*min/i);
    expect(fridayCard.textContent).not.toContain("0 TSS");
  });

  test("session detail links are not fabricated when no ID is present", async () => {
    mockAxios({ week: weekData({ withSessionIds: false }) });
    renderPage();
    await screen.findByTestId("training-v2-week");
    expect(screen.getByTestId("session-detail-support").textContent).toMatch(/unavailable/i);
    expect(screen.queryByTestId("training-v2-day-monday").getAttribute("data-detail-route")).toBeNull();
  });

  test("session cards become clickable when compatible IDs are provided", async () => {
    mockAxios({ week: weekData({ withSessionIds: true }) });
    renderPage();
    await screen.findByTestId("training-v2-week");

    const monday = screen.getByTestId("training-v2-day-monday");
    const tuesday = screen.getByTestId("training-v2-day-tuesday");

    expect(monday.getAttribute("href") || monday.getAttribute("data-detail-route")).toContain("/sessions/s-1");
    expect(tuesday.getAttribute("href") || tuesday.getAttribute("data-detail-route")).toContain("/workout/w-2");
  });

  test("shows cycle progress with week ratio and percent", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-cycle-progress");
    const cycleProgress = screen.getByTestId("training-v2-cycle-progress");
    expect(within(cycleProgress).getByText("12 / 18")).toBeInTheDocument();
    expect(screen.getByTestId("cycle-progress-percent").textContent).toContain("67%");
  });

  test("shows paces and supports insufficient-confidence state", async () => {
    mockAxios({ paces: pacesData({ confidence: "INSUFFICIENT" }) });
    renderPage();
    await screen.findByTestId("training-v2-paces");
    expect(screen.getByText(/representative performance/i)).toBeInTheDocument();
    expect(screen.queryByText("5:10 - 5:55 /km")).not.toBeInTheDocument();
  });

  test("paces section is collapsible on mobile", async () => {
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 390 });
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-paces");

    expect(screen.queryByTestId("paces-collapsible-content")).not.toBeVisible();
    fireEvent.click(screen.getByTestId("paces-collapsible-trigger"));
    expect(screen.getByTestId("paces-collapsible-content")).toBeVisible();
  });

  test("maintenance goal removes race countdown and race-week UI", async () => {
    mockAxios({ cycle: cycleData({ goalType: "maintenance" }) });
    renderPage();
    await screen.findByTestId("training-v2-plan-status");

    expect(screen.queryByText(/days left/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/race countdown/i)).not.toBeInTheDocument();
  });

  test("metric and imperial units are respected", async () => {
    mockAxios();
    renderPage({ unitSystem: "metric" });
    await screen.findByTestId("training-v2-week");
    expect(screen.getAllByText(formatDistance(8, { unitSystem: "metric" })).length).toBeGreaterThan(0);

    jest.clearAllMocks();
    mockAxios();
    renderPage({ unitSystem: "imperial" });
    const miles = formatDistance(8, { unitSystem: "imperial" });
    expect((await screen.findAllByText(miles)).length).toBeGreaterThan(0);
  });

  test.each([
    ["en", "Training Plan"],
    ["fr", "Plan d'entraînement"],
    ["es", "Plan de entrenamiento"],
  ])("i18n renders translated plan header in %s", async (lang, expected) => {
    mockAxios();
    renderPage({ lang });
    await screen.findByTestId("training-v2-plan-status");
    expect(screen.getByText(expected)).toBeInTheDocument();
  });
});

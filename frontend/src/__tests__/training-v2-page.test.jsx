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
  "/training/feedback",
];

function weekData() {
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
        {
          day: "monday", workout_type: "easy", distance_km: 8, duration_minutes: 45, estimated_tss: null,
          reason_codes: [], matching_status: "matched", adherence_status: "completed_as_planned",
          actual: { activity_id: "a1", distance_km: 8.1, duration_minutes: 44, pace_min_per_km: 5.5, activity_type: "running", start_time: "2026-08-24T07:00:00" },
          prescription: "45 min easy",
        },
        {
          day: "tuesday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
        },
        {
          day: "wednesday", workout_type: "quality", distance_km: 10, duration_minutes: 50, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          prescription: "3 × 10 min",
        },
        {
          day: "thursday", workout_type: "steady", distance_km: 8, duration_minutes: 42, estimated_tss: null,
          reason_codes: [], matching_status: "missed", adherence_status: "missed", actual: null,
          prescription: "40 min steady",
        },
        {
          day: "friday", workout_type: "easy", distance_km: 7, duration_minutes: 40, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          prescription: "40 min easy",
        },
        {
          day: "saturday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
        },
        {
          day: "sunday", workout_type: "long_easy", distance_km: 18, duration_minutes: 95, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          prescription: "Long run 18 km",
        },
      ],
      unmatched_actuals: [],
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
      { week_number: 11, start_date: "2026-08-10", end_date: "2026-08-16", phase: "build", is_current: false, weekly_target_km: 45 },
      { week_number: 12, start_date: "2026-08-17", end_date: "2026-08-23", phase: "specific", is_current: true, weekly_target_km: 50 },
      { week_number: 13, start_date: "2026-08-24", end_date: "2026-08-30", phase: "specific", is_current: false, weekly_target_km: 52 },
    ],
  };
}

function todayData({ explicitRest = false, noSession = false } = {}) {
  if (noSession) {
    return {
      status: "no_session",
      message: "No session planned for today",
      date: "2026-08-25",
      day: "Tuesday",
      planned_session: null,
      original_prescription: null,
      adapted_prescription: null,
      adaptive_session: null,
      adaptation_applied: false,
    };
  }

  if (explicitRest) {
    return {
      status: "success",
      planned_session: { workout_type: "rest", duration_minutes: null, distance_km: null, prescription: "REST" },
      original_prescription: { workout_type: "rest", duration_minutes: null, distance_km: null, prescription: "REST" },
      adapted_prescription: { workout_type: "rest", duration_minutes: null, distance_km: null, prescription: "REST" },
      adaptive_session: null,
      adaptation_applied: false,
      adaptation_reason: "",
    };
  }

  return {
    status: "success",
    readiness: { band: "EASY" },
    planned_session: {
      workout_type: "threshold",
      duration_minutes: 55,
      distance_km: 10,
      prescription: "3 × 10 min",
      pace_target: "5:10–5:20/km",
    },
    original_prescription: {
      workout_type: "threshold",
      duration_minutes: 55,
      distance_km: 10,
      prescription: "3 × 10 min",
      pace_target: "5:10–5:20/km",
    },
    adapted_prescription: {
      workout_type: "threshold",
      duration_minutes: 55,
      distance_km: 10,
      prescription: "3 × 10 min",
      pace_target: "5:10–5:20/km",
    },
    adaptive_session: null,
    adaptation_applied: false,
    adaptation_reason: "",
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
      marathon: null,
      threshold: { pace_str: "4:35" },
      interval: null,
      repetition: null,
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

function renderPage({ unitSystem = "metric", lang = "en", width = 1024 } = {}) {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
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

describe("TrainingPlanV2 — PR209 Runner Calendar", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
  });

  test("uses only canonical V2 endpoints and no legacy calls", async () => {
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

  test("keeps hierarchy with today as primary block", async () => {
    mockAxios();
    renderPage();

    const header = await screen.findByTestId("training-v2-plan-status");
    const today = screen.getByTestId("training-v2-today");
    const week = screen.getByTestId("training-v2-week");
    const paces = screen.getByTestId("training-v2-paces");
    const cycle = screen.getByTestId("training-v2-cycle");

    expect(header.compareDocumentPosition(today) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(today.compareDocumentPosition(week) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(week.compareDocumentPosition(paces) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(paces.compareDocumentPosition(cycle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("today card shows primary workout type, prescription, pace and duration", async () => {
    mockAxios();
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).getByTestId("today-session-type").textContent.toLowerCase()).toContain("threshold");
    expect(within(today).getByTestId("today-session-prescription")).toHaveTextContent("3 × 10 min");
    expect(within(today).getByTestId("today-session-pace-zone")).toHaveTextContent("5:10–5:20/km");
    expect(within(today).getByTestId("today-session-duration")).toHaveTextContent("55 min");
    expect(within(today).getByTestId("today-session-distance")).toHaveTextContent(formatDistance(10, { unitSystem: "metric" }));
    expect(within(today).queryByText(/TSS/i)).not.toBeInTheDocument();
  });

  test("today no-session state is not rendered as REST", async () => {
    mockAxios({ today: todayData({ noSession: true }) });
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).getByTestId("today-no-session-state")).toBeInTheDocument();
    expect(within(today).queryByTestId("today-rest-state")).not.toBeInTheDocument();
    expect(within(today).queryByTestId("today-session-type")).not.toBeInTheDocument();
  });

  test("today explicit REST is shown only when backend returns REST session", async () => {
    mockAxios({ today: todayData({ explicitRest: true }) });
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).getByTestId("today-session-type").textContent.toLowerCase()).toContain("rest");
  });

  test("week is compact, highlights today, and distinguishes done/planned/rest/missed from the real contract", async () => {
    mockAxios();
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    expect(within(week).getByTestId("today-highlight-badge")).toBeInTheDocument();
    expect(within(week).getByTestId("session-status-done")).toBeInTheDocument();
    expect(within(week).getAllByTestId("session-status-planned").length).toBeGreaterThan(0);
    expect(within(week).getAllByTestId("session-status-rest").length).toBeGreaterThan(0);
    expect(within(week).getByTestId("session-status-missed")).toBeInTheDocument();
  });

  test("never calls the legacy /training/feedback endpoint", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-page");

    const calledUrls = axios.get.mock.calls.map(([url]) => url);
    expect(calledUrls.some((url) => String(url).includes("/training/feedback"))).toBe(false);
    expect(axios.post).not.toHaveBeenCalled();
  });

  test("maps matched + completed_modified to a modified state, never fabricated as done", async () => {
    const modifiedWeek = weekData();
    modifiedWeek.week.sessions[0].adherence_status = "completed_modified";

    mockAxios({ week: modifiedWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    expect(within(week).getByTestId("session-status-modified")).toBeInTheDocument();
    expect(within(week).queryByTestId("session-status-done")).not.toBeInTheDocument();
  });

  test("maps matched + completed_unverified to an unverified state", async () => {
    const unverifiedWeek = weekData();
    unverifiedWeek.week.sessions[0].adherence_status = "completed_unverified";

    mockAxios({ week: unverifiedWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    expect(within(week).getByTestId("session-status-unverified")).toBeInTheDocument();
  });

  test("maps ambiguous matching_status to an ambiguous state, never disambiguated", async () => {
    const ambiguousWeek = weekData();
    ambiguousWeek.week.sessions[2].matching_status = "ambiguous";
    ambiguousWeek.week.sessions[2].adherence_status = "ambiguous";

    mockAxios({ week: ambiguousWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    expect(within(week).getByTestId("session-status-ambiguous")).toBeInTheDocument();
  });

  test("a past session without a matching_status is never fabricated as done", async () => {
    const unresolvedWeek = weekData();
    // C231 — a session in the past that the backend could not resolve stays
    // unresolved. It must never fall back to "done" purely because it is a
    // past calendar day.
    unresolvedWeek.week.sessions[3] = {
      day: "thursday", workout_type: "steady", distance_km: 8, duration_minutes: 42, estimated_tss: null,
      reason_codes: [], matching_status: null, adherence_status: null, actual: null,
      prescription: "40 min steady",
    };

    mockAxios({ week: unresolvedWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    const thursdayRow = within(week).getByTestId("training-v2-day-thursday");
    expect(thursdayRow.getAttribute("data-day-state")).not.toBe("done");
    expect(within(thursdayRow).queryByTestId("session-status-done")).not.toBeInTheDocument();
  });

  test("missing day in week payload stays neutral and is not marked REST", async () => {
    const weekWithMissingSunday = weekData();
    weekWithMissingSunday.week.sessions = weekWithMissingSunday.week.sessions.filter((session) => session.day !== "sunday");

    mockAxios({ week: weekWithMissingSunday });
    renderPage();
    await screen.findByTestId("training-v2-week");

    const sundayRow = screen.getByTestId("training-v2-day-sunday");
    expect(sundayRow.getAttribute("data-day-state")).toBe("absent");
    expect(within(sundayRow).queryByTestId("session-status-rest")).not.toBeInTheDocument();
    expect(within(sundayRow).getAllByText(/No session/i).length).toBeGreaterThan(0);
  });

  test("paces section stays collapsible and closed by default", async () => {
    mockAxios({ paces: pacesData({ confidence: "INSUFFICIENT" }) });
    renderPage({ width: 390 });

    await screen.findByTestId("training-v2-paces");
    expect(screen.getByTestId("paces-collapsible-content")).not.toBeVisible();
    fireEvent.click(screen.getByTestId("paces-collapsible-trigger"));
    expect(screen.getByTestId("paces-collapsible-content")).toBeVisible();
    expect(screen.getByText(/representative performance/i)).toBeInTheDocument();
  });

  test("cycle section is compact and collapsible", async () => {
    mockAxios();
    renderPage();

    await screen.findByTestId("training-v2-cycle");
    expect(screen.getByTestId("cycle-collapsible-content")).not.toBeVisible();
    fireEvent.click(screen.getByTestId("cycle-collapsible-trigger"));
    expect(screen.getByTestId("cycle-collapsible-content")).toBeVisible();
    expect(screen.getByTestId("cycle-week-12")).toBeInTheDocument();
  });

  test("maintenance goal removes race countdown UI", async () => {
    mockAxios({ cycle: cycleData({ goalType: "maintenance" }) });
    renderPage();

    await screen.findByTestId("training-v2-plan-status");
    expect(screen.queryByTestId("header-race-countdown")).not.toBeInTheDocument();
    expect(screen.queryByText(/days left/i)).not.toBeInTheDocument();
  });

  test.each([
    ["en", "Training Plan"],
    ["fr", "Plan d'entraînement"],
    ["es", "Plan de entrenamiento"],
  ])("i18n renders translated header in %s", async (lang, expected) => {
    mockAxios();
    renderPage({ lang });
    await screen.findByTestId("training-v2-plan-status");
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  test("does not expose backend technical labels", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-page");

    expect(screen.queryByText(/sessionDetailLinkAvailable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sessionDetailLinkUnavailable/i)).not.toBeInTheDocument();
  });
});

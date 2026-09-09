import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import TrainingPlanV2, { aggregateKnownMetric } from "@/pages/TrainingPlanV2";
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
      planned_km: 50,
      planned_duration_minutes: null,
      session_count: 5,
      sessions: [
        {
          day: "monday", planned_date: "2026-08-24", workout_type: "easy", distance_km: 8, duration_minutes: 45, estimated_tss: null,
          reason_codes: [], matching_status: "matched", adherence_status: "completed_as_planned",
          actual: { activity_id: "a1", distance_km: 8.1, duration_minutes: 44, pace_min_per_km: 5.5, activity_type: "running", start_time: "2026-08-24T07:00:00" },
          prescription: "45 min easy",
        },
        {
          day: "tuesday", planned_date: "2026-08-25", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
        },
        {
          day: "wednesday", planned_date: "2026-08-26", workout_type: "quality", distance_km: 10, duration_minutes: 50, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          prescription: "3 × 10 min",
        },
        {
          day: "thursday", planned_date: "2026-08-27", workout_type: "steady", distance_km: 8, duration_minutes: 42, estimated_tss: null,
          reason_codes: [], matching_status: "missed", adherence_status: "missed", actual: null,
          prescription: "40 min steady",
        },
        {
          day: "friday", planned_date: "2026-08-28", workout_type: "easy", distance_km: 7, duration_minutes: 40, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          prescription: "40 min easy",
        },
        {
          day: "saturday", planned_date: "2026-08-29", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
        },
        {
          day: "sunday", planned_date: "2026-08-30", workout_type: "long_easy", distance_km: 18, duration_minutes: 95, estimated_tss: null,
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
      served_prescription: null,
      planned_session: null,
      original_prescription: null,
      adapted_prescription: null,
      adaptive_session: null,
      adaptation_applied: false,
    };
  }

  // C233 — real /training/today shape (prescription_to_runtime_session):
  // day/type/duration ("Xmin"|"0min")/intensity/distance_km (0 sentinel)/
  // estimated_tss. No workout_type/duration_minutes/prescription/
  // pace_target/target_zone field exists on this object.
  if (explicitRest) {
    const restSession = { day: "tuesday", type: "rest", duration: "0min", intensity: "rest", distance_km: 0, estimated_tss: 0 };
    return {
      status: "success",
      served_prescription: restSession,
      planned_session: restSession,
      original_prescription: restSession,
      adapted_prescription: restSession,
      adaptive_session: null,
      adaptation_applied: false,
      adaptation_reason: "",
    };
  }

  const session = { day: "tuesday", type: "threshold", duration: "55min", intensity: "hard", distance_km: 10, estimated_tss: null };
  return {
    status: "success",
    readiness: { band: "EASY" },
    served_prescription: session,
    planned_session: session,
    original_prescription: session,
    adapted_prescription: session,
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
      easy: { lower: { pace_str: "5:10", min_per_km: 5.1667 }, upper: { pace_str: "5:55", min_per_km: 5.9167 } },
      marathon: null,
      threshold: { pace_str: "4:35", min_per_km: 4.5833 },
      interval: null,
      repetition: null,
    },
  };
}

function structuredData() {
  return {
    workout_type: "quality",
    quality_kind: "threshold_intervals",
    target_basis: "distance",
    total_distance_km: 9,
    total_duration_minutes: null,
    steps: [
      { step_type: "warmup", repetitions: 1, distance_m: 1500, duration_seconds: null, recovery: null, pace_zone: "E", pace_min_per_km: null, pace_min_per_km_min: 6.1667, pace_min_per_km_max: 6.5833 },
      { step_type: "work", repetitions: 3, distance_m: 2000, duration_seconds: null, recovery: { kind: "jog", duration_seconds: 120, distance_m: null, count: 2 }, pace_zone: "T", pace_min_per_km: 5.1333, pace_min_per_km_min: null, pace_min_per_km_max: null },
      { step_type: "cooldown", repetitions: 1, distance_m: 1500, duration_seconds: null, recovery: null, pace_zone: "E", pace_min_per_km: null, pace_min_per_km_min: 6.1667, pace_min_per_km_max: 6.5833 },
    ],
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

  test("today card shows the real /training/today contract: type, duration, and distance from served_prescription", async () => {
    mockAxios();
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).getByTestId("today-session-type").textContent.toLowerCase()).toContain("quality");
    expect(within(today).getByTestId("today-session-duration")).toHaveTextContent("55 min");
    expect(within(today).getByTestId("today-session-distance")).toHaveTextContent(formatDistance(10, { unitSystem: "metric" }));
    expect(within(today).queryByTestId("today-session-prescription")).not.toBeInTheDocument();
    expect(within(today).queryByTestId("today-session-pace-zone")).not.toBeInTheDocument();
    expect(within(today).queryByText(/3 × 10 min/)).not.toBeInTheDocument();
    expect(within(today).queryByText(/5:10/)).not.toBeInTheDocument();
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
    // weekData(): reference_date "2026-08-25" is a Tuesday -> exactly the
    // tuesday row (a rest day) carries the Today badge, driven purely by
    // reference_date, never the browser clock.
    expect(within(screen.getByTestId("training-v2-day-tuesday")).getByTestId("today-highlight-badge")).toBeInTheDocument();
    expect(within(week).getAllByTestId("today-highlight-badge")).toHaveLength(1);
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

  test("matched + unknown/invalid adherence_status is never fabricated as done", async () => {
    // C231 — item 5: matching_status="matched" with an adherence_status the
    // frontend does not recognise (unknown string, null, or missing) must
    // never fall back to "done" — the ONLY sanctioned fallback is
    // "unverified" (or null), never a fabricated success state.
    const unknownAdherenceWeek = weekData();
    unknownAdherenceWeek.week.sessions[0].matching_status = "matched";
    unknownAdherenceWeek.week.sessions[0].adherence_status = "some_future_unrecognised_status";

    mockAxios({ week: unknownAdherenceWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    expect(within(week).queryByTestId("session-status-done")).not.toBeInTheDocument();
    expect(within(week).getByTestId("session-status-unverified")).toBeInTheDocument();
  });

  test("matched + null adherence_status is never fabricated as done", async () => {
    const nullAdherenceWeek = weekData();
    nullAdherenceWeek.week.sessions[0].matching_status = "matched";
    nullAdherenceWeek.week.sessions[0].adherence_status = null;

    mockAxios({ week: nullAdherenceWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    expect(within(week).queryByTestId("session-status-done")).not.toBeInTheDocument();
    expect(within(week).getByTestId("session-status-unverified")).toBeInTheDocument();
  });

  test("C231 round 2 item 1: today always shows served_prescription, never the stale planned_session even when adaptation_applied is false", async () => {
    // Simulates: plan brut 18 km -> first call froze a CAUTION snapshot at
    // 12.6 km -> a later call's live recompute now says FAVORABLE/KEEP
    // (adaptation_applied=false), but the canonical frozen snapshot must
    // still be what is displayed: 12.6 km, never the raw 18 km plan.
    mockAxios({
      today: {
        status: "success",
        readiness: { band: "EASY" },
        planned_session: {
          day: "monday", type: "long_run", duration: "95min", intensity: "easy", distance_km: 18, estimated_tss: null,
        },
        original_prescription: {
          day: "monday", type: "long_run", duration: "95min", intensity: "easy", distance_km: 18, estimated_tss: null,
        },
        served_prescription: {
          day: "monday", type: "long_run", duration: "66min", intensity: "easy", distance_km: 12.6, estimated_tss: null,
        },
        adapted_prescription: {
          day: "monday", type: "long_run", duration: "66min", intensity: "easy", distance_km: 12.6, estimated_tss: null,
        },
        adaptive_session: null,
        // KEY: adaptation_applied is FALSE (live recompute says KEEP), yet
        // the canonical served_prescription must still win the display.
        adaptation_applied: false,
        adaptation_reason: "",
      },
    });
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).getByTestId("today-session-distance")).toHaveTextContent(
      formatDistance(12.6, { unitSystem: "metric" })
    );
    expect(within(today).queryByText(formatDistance(18, { unitSystem: "metric" }))).not.toBeInTheDocument();
  });

  test("C231 round 2 item 3: a prescription_unavailable session shows a neutral state, no Done/Missed/Modified badge, no fabricated distance", async () => {
    const unavailableWeek = weekData();
    unavailableWeek.week.sessions[3] = {
      day: "thursday",
      workout_type: null,
      intensity_class: null,
      distance_km: null,
      duration_minutes: null,
      estimated_tss: null,
      reason_codes: [],
      matching_status: null,
      adherence_status: null,
      actual: null,
      execution_status: "prescription_unavailable",
    };

    mockAxios({ week: unavailableWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    const thursdayRow = within(week).getByTestId("training-v2-day-thursday");
    expect(within(thursdayRow).getByTestId("session-status-unavailable")).toBeInTheDocument();
    expect(within(thursdayRow).queryByTestId("session-status-done")).not.toBeInTheDocument();
    expect(within(thursdayRow).queryByTestId("session-status-missed")).not.toBeInTheDocument();
    expect(within(thursdayRow).queryByTestId("session-status-modified")).not.toBeInTheDocument();
    expect(thursdayRow.getAttribute("data-day-state")).toBe("unavailable");
    expect(within(thursdayRow).queryByText(/8/)).not.toBeInTheDocument();
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

  // ── PR233 — Training UX V3 ────────────────────────────────────────────

  test("separates planned volume from real Garmin completed volume, and never counts an unmatched extra as a completed planned session", async () => {
    mockAxios();
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    // weekData(): weekly_target.target_km = 50, only session[0] (monday) is
    // matched with actual.distance_km = 8.1 -> completed must reflect ONLY
    // that matched activity, never the full planned 50 km.
    expect(within(volume).getByTestId("week-volume-planned")).toHaveTextContent(
      formatDistance(50, { unitSystem: "metric" })
    );
    expect(within(volume).getByTestId("week-volume-completed")).toHaveTextContent(
      formatDistance(8.1, { unitSystem: "metric" })
    );
    expect(within(volume).getByTestId("week-volume-sessions")).toHaveTextContent("1/5");
  });

  test("shows a separate 'extra Garmin volume' figure driven only by unmatched_actuals, never merged into completed plan volume", async () => {
    const week = weekData();
    week.week.unmatched_actuals = [
      { activity_id: "extra-1", distance_km: 6.2, duration_minutes: 32, pace_min_per_km: 5.16, activity_type: "running", start_time: "2026-08-23T09:00:00" },
    ];
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    expect(within(volume).getByTestId("week-volume-extra")).toHaveTextContent(
      formatDistance(6.2, { unitSystem: "metric" })
    );
    // The extra Garmin activity must never inflate "completed" plan volume.
    expect(within(volume).getByTestId("week-volume-completed")).toHaveTextContent(
      formatDistance(8.1, { unitSystem: "metric" })
    );
  });

  test("unmatched Garmin activities are rendered in their own section, never attached to a planned session card", async () => {
    const week = weekData();
    week.week.unmatched_actuals = [
      { activity_id: "extra-1", distance_km: 6.2, duration_minutes: 32, pace_min_per_km: 5.16, activity_type: "running", start_time: "2026-08-23T09:00:00" },
    ];
    mockAxios({ week });
    renderPage();

    const unmatched = await screen.findByTestId("training-v2-unmatched");
    expect(within(unmatched).getAllByTestId("unmatched-activity-row")).toHaveLength(1);
    expect(within(unmatched).getByTestId("unmatched-activity-row")).toHaveTextContent(
      formatDistance(6.2, { unitSystem: "metric" })
    );
    // Saturday/other rows must not show this unmatched activity's distance.
    const weekCard = screen.getByTestId("training-v2-week");
    expect(within(weekCard).queryByText(formatDistance(6.2, { unitSystem: "metric" }))).not.toBeInTheDocument();
  });

  test("unmatched section shows an explicit empty state when there is nothing extra this week", async () => {
    mockAxios();
    renderPage();

    const unmatched = await screen.findByTestId("training-v2-unmatched");
    expect(within(unmatched).getByTestId("unmatched-empty-state")).toBeInTheDocument();
    expect(within(unmatched).queryByTestId("unmatched-activity-row")).not.toBeInTheDocument();
  });

  test("clicking a matched session reveals prescribed vs real Garmin actual, with real pace and a link to analysis using the real activity id", async () => {
    mockAxios();
    renderPage();

    await screen.findByTestId("training-v2-week");
    fireEvent.click(screen.getByTestId("session-detail-toggle-monday"));

    const detail = screen.getByTestId("training-v2-day-detail-monday");
    expect(detail).toBeVisible();
    expect(within(detail).getByTestId("session-actual-distance-monday")).toHaveTextContent(
      formatDistance(8.1, { unitSystem: "metric" })
    );
    expect(within(detail).getByTestId("session-actual-duration-monday")).toHaveTextContent("44 min");
    expect(within(detail).getByTestId("session-actual-pace-monday")).toHaveTextContent("/km");
    expect(within(detail).getByTestId("session-analysis-link-monday")).toHaveAttribute("href", "/workout/garmin-a1");
  });

  test("clicking a planned (not-yet-matched) session shows no fabricated actual and no analysis link", async () => {
    mockAxios();
    renderPage();

    await screen.findByTestId("training-v2-week");
    fireEvent.click(screen.getByTestId("session-detail-toggle-friday"));

    const detail = screen.getByTestId("training-v2-day-detail-friday");
    expect(detail).toBeVisible();
    expect(within(detail).getByTestId("session-no-actual-friday")).toBeInTheDocument();
    expect(within(detail).queryByTestId("session-analysis-link-friday")).not.toBeInTheDocument();
  });

  test("a prescription_unavailable session cannot be expanded (no detail toggle beyond the neutral state)", async () => {
    const unavailableWeek = weekData();
    unavailableWeek.week.sessions[3] = {
      day: "thursday", workout_type: null, intensity_class: null, distance_km: null, duration_minutes: null,
      estimated_tss: null, reason_codes: [], matching_status: null, adherence_status: null, actual: null,
      execution_status: "prescription_unavailable",
    };
    mockAxios({ week: unavailableWeek });
    renderPage();

    await screen.findByTestId("training-v2-week");
    const toggle = screen.getByTestId("session-detail-toggle-thursday");
    expect(toggle).toBeDisabled();
    expect(screen.queryByTestId("training-v2-day-detail-thursday")).not.toBeInTheDocument();
  });

  test("a rest day cannot be expanded (nothing real to show beyond 'rest')", async () => {
    mockAxios();
    renderPage();

    await screen.findByTestId("training-v2-week");
    // weekData()'s tuesday and saturday are explicit rest days.
    expect(screen.getByTestId("session-detail-toggle-tuesday")).toBeDisabled();
    expect(screen.queryByTestId("training-v2-day-detail-tuesday")).not.toBeInTheDocument();
  });

  test("never invents a structured workout (splits/reps/warmup) for a 'quality' session — only the raw backend prescription text is shown", async () => {
    mockAxios();
    renderPage();

    const week = await screen.findByTestId("training-v2-week");
    // wednesday is workout_type=quality with prescription "3 × 10 min" from
    // the mock backend payload — this is rendered verbatim, never expanded
    // into an invented structure like "3x2km threshold" or a warmup/cooldown.
    expect(within(week).getByTestId("training-v2-day-prescription-wednesday")).toHaveTextContent("3 × 10 min");
    expect(screen.queryByText(/warmup/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/cooldown/i)).not.toBeInTheDocument();
  });

  test("never invents a pace for a session whose prescription carries none", async () => {
    mockAxios();
    renderPage();

    await screen.findByTestId("training-v2-week");
    fireEvent.click(screen.getByTestId("session-detail-toggle-wednesday"));
    const detail = screen.getByTestId("training-v2-day-detail-wednesday");
    // weekData()'s quality session has no pace_target/pace/zone field at all
    // -> no pace must appear anywhere in its prescribed block.
    expect(within(detail).queryByText(/min\/km/i)).not.toBeInTheDocument();
    expect(within(detail).queryByText(/\/km$/)).not.toBeInTheDocument();
  });

  test("imperial mode never shows a hardcoded /km suffix (distance, pace, and training paces)", async () => {
    mockAxios();
    renderPage({ unitSystem: "imperial" });

    await screen.findByTestId("training-v2-week");
    fireEvent.click(screen.getByTestId("session-detail-toggle-monday"));
    const detail = screen.getByTestId("training-v2-day-detail-monday");
    expect(within(detail).getByTestId("session-actual-pace-monday")).toHaveTextContent("/mi");
    expect(within(detail).queryByText(/\/km/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("paces-collapsible-trigger"));
    const paces = screen.getByTestId("training-v2-paces");
    expect(within(paces).queryByText(/\/km/)).not.toBeInTheDocument();
    expect(within(paces).getAllByText(/\/mi/).length).toBeGreaterThan(0);
  });

  test("metric mode shows /km for training paces and real activity pace", async () => {
    mockAxios();
    renderPage({ unitSystem: "metric" });

    await screen.findByTestId("training-v2-week");
    fireEvent.click(screen.getByTestId("session-detail-toggle-monday"));
    expect(screen.getByTestId("session-actual-pace-monday")).toHaveTextContent("/km");

    fireEvent.click(screen.getByTestId("paces-collapsible-trigger"));
    expect(within(screen.getByTestId("training-v2-paces")).getAllByText(/\/km/).length).toBeGreaterThan(0);
  });

  test("renders correctly on a narrow mobile viewport with no horizontal session-detail overflow markers", async () => {
    mockAxios();
    renderPage({ width: 360 });

    const page = await screen.findByTestId("training-v2-page");
    expect(page).toBeInTheDocument();
    expect(screen.getByTestId("training-v2-week-volume")).toBeInTheDocument();
    expect(screen.getByTestId("training-v2-unmatched")).toBeInTheDocument();
  });

  test("no Done/Missed manual feedback button exists anywhere on the page", async () => {
    mockAxios();
    renderPage();
    await screen.findByTestId("training-v2-page");

    // Only the toggle buttons (session-detail-toggle-*) exist for sessions;
    // none of them are a manual Done/Missed feedback action. A real manual
    // feedback control would use a dedicated test id / exact button label —
    // neither exists in this UI.
    const allButtons = screen.getAllByRole("button");
    allButtons.forEach((button) => {
      expect(button.getAttribute("data-testid") || "").not.toMatch(/^(mark-)?(done|missed)-button$/i);
    });
    expect(screen.queryByText(/mark as done/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/mark as missed/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("done-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("missed-button")).not.toBeInTheDocument();
  });

  // ── C233 — correction blockers ─────────────────────────────────────────

  test("C233 #1: a matched session's analysis link uses garmin-${external_id}, the id /workout/:id actually expects", async () => {
    // Cross-layer: db.workouts.id is built by activity_to_workout() as
    // f"garmin-{external_id}" (backend/garmin/service.py:544); actual.activity_id
    // on WeekV2ActualResponse is the raw external_id. Garmin activity_id="12345" ->
    // the ONLY working link is /workout/garmin-12345.
    const week = weekData();
    week.week.sessions[0].actual.activity_id = "12345";
    mockAxios({ week });
    renderPage();

    await screen.findByTestId("training-v2-week");
    fireEvent.click(screen.getByTestId("session-detail-toggle-monday"));
    expect(screen.getByTestId("session-analysis-link-monday")).toHaveAttribute("href", "/workout/garmin-12345");
  });

  test("C233 #1: an unmatched Garmin actual's analysis link uses the same garmin-${external_id} rule", async () => {
    const week = weekData();
    week.week.unmatched_actuals = [
      { activity_id: "12345", distance_km: 6.2, duration_minutes: 32, pace_min_per_km: 5.16, activity_type: "running", start_time: "2026-08-23T09:00:00" },
    ];
    mockAxios({ week });
    renderPage();

    const unmatched = await screen.findByTestId("training-v2-unmatched");
    const row = within(unmatched).getByTestId("unmatched-activity-row");
    expect(within(row).getByText(/View analysis|Voir l.analyse|Ver análisis/i)).toHaveAttribute("href", "/workout/garmin-12345");
  });

  test("C233 #2: today's real duration ('Xmin' string) is displayed, and '0min' is never shown as a real duration", async () => {
    mockAxios({
      today: {
        status: "success",
        served_prescription: { day: "tuesday", type: "rest", duration: "0min", intensity: "rest", distance_km: 0, estimated_tss: 0 },
      },
    });
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).queryByTestId("today-session-duration")).not.toBeInTheDocument();
    expect(within(today).queryByText(/0min/)).not.toBeInTheDocument();
    expect(within(today).queryByText(/0 min/)).not.toBeInTheDocument();
  });

  test("C233 #2: distance_km=0 runtime sentinel is never shown as a real '0 km' distance for a rest day", async () => {
    mockAxios({
      today: {
        status: "success",
        served_prescription: { day: "tuesday", type: "rest", duration: "0min", intensity: "rest", distance_km: 0, estimated_tss: 0 },
      },
    });
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).queryByTestId("today-session-distance")).not.toBeInTheDocument();
  });

  test("C233 #2: no fabricated prescription text or pace is ever shown on the Today card", async () => {
    mockAxios();
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).queryByTestId("today-session-prescription")).not.toBeInTheDocument();
    expect(within(today).queryByTestId("today-session-pace-zone")).not.toBeInTheDocument();
  });

  test("C233 #3: Today's badge is driven exclusively by weekData.reference_date, never by the browser's clock/timezone", async () => {
    // Browser is mocked far away in both date AND timezone from the
    // backend's reference_date (2026-08-25, a Tuesday). If the frontend ever
    // fell back to `new Date()`, the badge would land on the wrong day (or
    // no day at all).
    const originalTZ = process.env.TZ;
    process.env.TZ = "Pacific/Kiritimati"; // UTC+14, deliberately far from UTC
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2099-01-01T23:00:00Z")); // a Thursday, decades away

    try {
      mockAxios();
      renderPage();

      const week = await screen.findByTestId("training-v2-week");
      expect(within(screen.getByTestId("training-v2-day-tuesday")).getByTestId("today-highlight-badge")).toBeInTheDocument();
      expect(within(week).getAllByTestId("today-highlight-badge")).toHaveLength(1);
    } finally {
      jest.useRealTimers();
      process.env.TZ = originalTZ;
    }
  });

  test("C233 #3: reference_date remains the sole authority even when no session.planned_date matches it exactly", async () => {
    const week = weekData();
    // Remove planned_date from every session: the deterministic weekday
    // fallback (computed from reference_date itself, not the browser clock)
    // must still resolve Today to tuesday (2026-08-25's real weekday).
    week.week.sessions.forEach((session) => { delete session.planned_date; });
    mockAxios({ week });
    renderPage();

    const weekCard = await screen.findByTestId("training-v2-week");
    expect(within(screen.getByTestId("training-v2-day-tuesday")).getByTestId("today-highlight-badge")).toBeInTheDocument();
    expect(within(weekCard).getAllByTestId("today-highlight-badge")).toHaveLength(1);
  });

  test("C233 #4: each week card shows its real weekday + planned_date, e.g. 'Wednesday · 26 Aug'", async () => {
    mockAxios();
    renderPage();

    await screen.findByTestId("training-v2-week");
    expect(screen.getByTestId("training-v2-day-label-wednesday")).toHaveTextContent(/Wednesday/);
    expect(screen.getByTestId("training-v2-day-label-wednesday")).toHaveTextContent(/26 Aug/);
    expect(screen.getByTestId("training-v2-day-label-monday")).toHaveTextContent(/24 Aug/);
  });

  test("C233 #4: the day+date label respects the active locale (fr/es), never the browser clock", async () => {
    mockAxios();
    renderPage({ lang: "fr" });

    await screen.findByTestId("training-v2-week");
    expect(screen.getByTestId("training-v2-day-label-wednesday")).toHaveTextContent(/Mercredi/);
  });

  test("C233 #4: no date suffix is fabricated when a session has no real planned_date", async () => {
    const week = weekData();
    delete week.week.sessions[2].planned_date; // wednesday
    mockAxios({ week });
    renderPage();

    await screen.findByTestId("training-v2-week");
    expect(screen.getByTestId("training-v2-day-label-wednesday")).toHaveTextContent("Wednesday");
    expect(screen.getByTestId("training-v2-day-label-wednesday").textContent).not.toContain("·");
  });

  // ── C233 final round — "None != 0" volume aggregate truth ─────────────
  // A missing metric on a real activity must never be silently dropped and
  // the remaining known values presented as a complete total. Zero matched
  // activities is a real, complete zero and must render as "0 km"/"0 min",
  // never as "—".

  test("C233 final #1: distance basis, zero matched activities -> Completed (Garmin) = 0 km, not '—'", async () => {
    const week = weekData();
    week.week.sessions.forEach((session) => { session.actual = null; session.matching_status = "planned"; });
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    expect(within(volume).getByTestId("week-volume-completed")).toHaveTextContent(
      formatDistance(0, { unitSystem: "metric" })
    );
    expect(within(volume).getByTestId("week-volume-completed")).not.toHaveTextContent("—");
  });

  test("C233 final #2: duration basis, zero matched activities -> Completed (Garmin) = 0 min, not '—'", async () => {
    const week = weekData();
    week.weekly_target.target_basis = "duration";
    week.week.sessions.forEach((session) => { session.actual = null; session.matching_status = "planned"; });
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    expect(within(volume).getByTestId("week-volume-completed")).toHaveTextContent("0 min");
    expect(within(volume).getByTestId("week-volume-completed")).not.toHaveTextContent("—");
  });

  test("C233 final #3: distance basis, two matched activities with known distances -> exact sum (8.1 + 6.2 = 14.3 km)", async () => {
    const week = weekData();
    week.week.sessions[3].matching_status = "matched"; // thursday
    week.week.sessions[3].actual = {
      activity_id: "a2", distance_km: 6.2, duration_minutes: 30, pace_min_per_km: 4.8,
      activity_type: "running", start_time: "2026-08-27T07:00:00",
    };
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    expect(within(volume).getByTestId("week-volume-completed")).toHaveTextContent(
      formatDistance(14.3, { unitSystem: "metric" })
    );
  });

  test("C233 final #4: distance basis, two matched activities but one has a null distance_km -> never shows 8.1 km as the completed total, shows incomplete state instead", async () => {
    const week = weekData();
    week.week.sessions[3].matching_status = "matched"; // thursday
    week.week.sessions[3].actual = {
      activity_id: "a2", distance_km: null, duration_minutes: 30, pace_min_per_km: null,
      activity_type: "running", start_time: "2026-08-27T07:00:00",
    };
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    const completed = within(volume).getByTestId("week-volume-completed");
    expect(completed).not.toHaveTextContent(formatDistance(8.1, { unitSystem: "metric" }));
    expect(completed.textContent).toMatch(/—|Incomplete data/);
  });

  test("C233 final #5: duration basis, two matched activities but one has a null duration_minutes -> never shows 44 min as a complete total", async () => {
    const week = weekData();
    week.weekly_target.target_basis = "duration";
    week.week.sessions[3].matching_status = "matched"; // thursday
    week.week.sessions[3].actual = {
      activity_id: "a2", distance_km: 6, duration_minutes: null, pace_min_per_km: null,
      activity_type: "running", start_time: "2026-08-27T07:00:00",
    };
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    const completed = within(volume).getByTestId("week-volume-completed");
    expect(completed).not.toHaveTextContent("44 min");
    expect(completed.textContent).toMatch(/—|Incomplete data/);
  });

  test("C233 final #6: unmatched extras with one null distance_km never show the partial sum as the complete extra total", async () => {
    const week = weekData();
    week.week.unmatched_actuals = [
      { activity_id: "extra-1", distance_km: 6.2, duration_minutes: 32, pace_min_per_km: 5.16, activity_type: "running", start_time: "2026-08-23T09:00:00" },
      { activity_id: "extra-2", distance_km: null, duration_minutes: 20, pace_min_per_km: null, activity_type: "running", start_time: "2026-08-22T09:00:00" },
    ];
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    const extra = within(volume).getByTestId("week-volume-extra");
    expect(extra).not.toHaveTextContent(formatDistance(6.2, { unitSystem: "metric" }));
    expect(extra.textContent).toMatch(/—|Incomplete data/);
  });

  test("C233 final #7: completedSessionCount stays correct (count of real matched actuals) even when a matched actual's metric is missing", async () => {
    const week = weekData();
    week.week.sessions[3].matching_status = "matched"; // thursday
    week.week.sessions[3].actual = {
      activity_id: "a2", distance_km: null, duration_minutes: 30, pace_min_per_km: null,
      activity_type: "running", start_time: "2026-08-27T07:00:00",
    };
    mockAxios({ week });
    renderPage();

    const volume = await screen.findByTestId("training-v2-week-volume");
    // monday (a1) + thursday (a2) are both real matched activities, even
    // though thursday's distance_km is unknown -> session count is still 2.
    expect(within(volume).getByTestId("week-volume-sessions")).toHaveTextContent("2/5");
  });

  test("C233 final #8: None != 0 — a null field on a real row is never coerced to 0, and an empty row list is a true, distinct zero", () => {
    expect(aggregateKnownMetric([], "distance_km")).toEqual({ state: "empty", value: 0 });
    expect(aggregateKnownMetric([{ distance_km: null }], "distance_km")).toEqual({ state: "partial", value: null });
    expect(aggregateKnownMetric([{ distance_km: 5 }, { distance_km: null }], "distance_km").state).toBe("partial");
    expect(aggregateKnownMetric([{ distance_km: 5 }, { distance_km: 3 }], "distance_km")).toEqual({ state: "complete", value: 8 });
  });

  // ── PR236 — structured sessions ────────────────────────────────────────

  test("Today renders only the served structured prescription, including structure and primary pace", async () => {
    const today = todayData();
    today.structured_prescription = structuredData();
    today.prescription_id = "u1:2026-08-25:tuesday";
    today.planned_session = { ...today.served_prescription, distance_km: 18 };
    mockAxios({ today });
    renderPage();

    const card = await screen.findByTestId("training-v2-today");
    expect(within(card).getByTestId("structured-workout-view")).toBeInTheDocument();
    expect(within(card).getByTestId("today-session-distance")).toHaveTextContent("9.00 km");
    expect(within(card).getByTestId("today-session-pace")).toHaveTextContent("5:08 /km");
    expect(within(card).getByTestId("today-session-type")).toHaveTextContent("Threshold");
    expect(within(card).queryByText("18.0 km")).not.toBeInTheDocument();
  });

  test("Week displays a structured summary before expansion and full detail after expansion", async () => {
    const week = weekData();
    week.week.sessions[2].structured = structuredData();
    week.week.sessions[2].structured_status = "future_live";
    week.week.sessions[2].prescription_id = "u1:2026-08-26:wednesday";
    mockAxios({ week });
    renderPage();

    const row = await screen.findByTestId("training-v2-day-wednesday");
    expect(within(row).getByTestId("training-v2-day-type-wednesday")).toHaveTextContent("Threshold");
    expect(within(row).getByTestId("structured-workout-summary")).toHaveTextContent("3 × 2.00 km");
    fireEvent.click(screen.getByTestId("session-detail-toggle-wednesday"));
    expect(within(row).getByTestId("structured-workout-view")).toBeVisible();
  });

  test.each(["historical_frozen", "future_live", "today_served"])(
    "renders backend structure for structured_status=%s without exposing the technical status",
    async (structuredStatus) => {
      const week = weekData();
      week.week.sessions[2].structured = structuredData();
      week.week.sessions[2].structured_status = structuredStatus;
      mockAxios({ week });
      renderPage();
      const row = await screen.findByTestId("training-v2-day-wednesday");
      expect(within(row).getByTestId("structured-workout-summary")).toBeInTheDocument();
      expect(within(row).queryByText(structuredStatus)).not.toBeInTheDocument();
    }
  );

  test("historical_unavailable renders parent facts but never invents structured details", async () => {
    const week = weekData();
    week.week.sessions[2].structured = structuredData();
    week.week.sessions[2].structured_status = "historical_unavailable";
    mockAxios({ week });
    renderPage();

    const row = await screen.findByTestId("training-v2-day-wednesday");
    expect(within(row).getByTestId("training-v2-day-type-wednesday")).toBeInTheDocument();
    expect(within(row).queryByTestId("structured-workout-summary")).not.toBeInTheDocument();
    expect(within(row).queryByText(/Warm-up|Échauffement/)).not.toBeInTheDocument();
  });

  test("legacy structured quality without quality_kind keeps the generic quality label", async () => {
    const week = weekData();
    week.week.sessions[2].structured = structuredData();
    delete week.week.sessions[2].structured.quality_kind;
    week.week.sessions[2].structured_status = "historical_frozen";
    mockAxios({ week });
    renderPage();

    expect(within(await screen.findByTestId("training-v2-day-wednesday")).getByTestId(
      "training-v2-day-type-wednesday"
    )).toHaveTextContent("Quality session");
  });

  test.each([
    ["tempo_continuous", "Tempo"],
    ["threshold_intervals", "Threshold"],
    ["vo2_intervals", "Intervals"],
    ["race_specific_steady", "Race pace"],
  ])("Today uses the backend quality_kind %s for its exact label", async (qualityKind, label) => {
    const today = todayData();
    today.structured_prescription = { ...structuredData(), quality_kind: qualityKind };
    mockAxios({ today });
    renderPage();

    expect(within(await screen.findByTestId("training-v2-today")).getByTestId(
      "today-session-type"
    )).toHaveTextContent(label);
  });

  test("ignores quality_kind for a non-quality structured workout", async () => {
    const today = todayData();
    today.structured_prescription = {
      ...structuredData(),
      workout_type: "easy",
      quality_kind: "vo2_intervals",
    };
    mockAxios({ today });
    renderPage();

    expect(within(await screen.findByTestId("training-v2-today")).getByTestId(
      "today-session-type"
    )).toHaveTextContent("Easy run");
  });

  test.each([
    [true, true],
    [false, false],
    [null, false],
  ])("Today adaptation badge follows session_modified_from_planned=%s only", async (modified, visible) => {
    const today = { ...todayData(), session_modified_from_planned: modified };
    mockAxios({ today });
    renderPage();
    const card = await screen.findByTestId("training-v2-today");
    expect(Boolean(within(card).queryByTestId("session-adapted-badge"))).toBe(visible);
  });

  test("Week adaptation badge follows backend truth and does not compare prescriptions", async () => {
    const week = weekData();
    week.week.sessions[2].session_modified_from_planned = true;
    week.week.sessions[3].session_modified_from_planned = false;
    mockAxios({ week });
    renderPage();
    expect(within(await screen.findByTestId("training-v2-day-wednesday")).getByTestId("session-adapted-badge")).toBeInTheDocument();
    expect(within(screen.getByTestId("training-v2-day-thursday")).queryByTestId("session-adapted-badge")).not.toBeInTheDocument();
  });

  test("prescription_id is used as the stable React key contract", () => {
    const source = require("fs").readFileSync(require.resolve("@/pages/TrainingPlanV2"), "utf8");
    expect(source).toMatch(/key=\{session\?\.prescription_id \|\| day\}/);
  });

  test.each([
    ["en", "Warm-up", "Adapted"],
    ["fr", "Échauffement", "Adaptée"],
  ])("structured labels and adaptation are translated in %s", async (lang, stepLabel, adaptedLabel) => {
    const today = { ...todayData(), structured_prescription: structuredData(), session_modified_from_planned: true };
    mockAxios({ today });
    renderPage({ lang });
    const card = await screen.findByTestId("training-v2-today");
    expect(within(card).getByText(stepLabel)).toBeInTheDocument();
    expect(within(card).getByText(adaptedLabel)).toBeInTheDocument();
  });
});

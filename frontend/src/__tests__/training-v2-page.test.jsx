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
      planned_km: 50,
      planned_duration_minutes: null,
      session_count: 5,
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
      easy: { lower: { pace_str: "5:10", min_per_km: 5.1667 }, upper: { pace_str: "5:55", min_per_km: 5.9167 } },
      marathon: null,
      threshold: { pace_str: "4:35", min_per_km: 4.5833 },
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
          workout_type: "long_easy", duration_minutes: 95, distance_km: 18,
          prescription: "Long run 18 km",
        },
        original_prescription: {
          workout_type: "long_easy", duration_minutes: 95, distance_km: 18,
          prescription: "Long run 18 km",
        },
        served_prescription: {
          workout_type: "long_easy", duration_minutes: 66, distance_km: 12.6,
          prescription: "Long run 12.6 km (frozen)",
        },
        adapted_prescription: {
          workout_type: "long_easy", duration_minutes: 66, distance_km: 12.6,
          prescription: "Long run 12.6 km (frozen)",
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
    expect(within(detail).getByTestId("session-analysis-link-monday")).toHaveAttribute("href", "/workout/a1");
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
});

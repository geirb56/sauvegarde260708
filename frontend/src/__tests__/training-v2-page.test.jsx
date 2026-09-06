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

const DAYS_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

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
      planned_km: 58,
      planned_duration_minutes: null,
      session_count: 5,
      sessions: [
        {
          day: "monday", workout_type: "easy", distance_km: 8, duration_minutes: 45, estimated_tss: null,
          reason_codes: [], matching_status: "matched", adherence_status: "completed_as_planned",
          actual: { activity_id: "a1", distance_km: 8.1, duration_minutes: 44, pace_min_per_km: 5.5, activity_type: "running", start_time: "2026-08-24T07:00:00" },
          primary_pace: { lower_min_per_km: 5.75, upper_min_per_km: 6.3 },
        },
        {
          day: "tuesday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
        },
        {
          day: "wednesday", workout_type: "quality", distance_km: 9, duration_minutes: 50, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          // C232 (correction) — "quality"'s exact nature is not decided by
          // the Training Engine: never a fabricated pace zone or split.
          primary_pace: null,
        },
        {
          day: "thursday", workout_type: "steady", distance_km: 8, duration_minutes: 42, estimated_tss: null,
          reason_codes: [], matching_status: "missed", adherence_status: "missed", actual: null,
        },
        {
          day: "friday", workout_type: "easy", distance_km: 7, duration_minutes: 40, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          primary_pace: { lower_min_per_km: 6.25, upper_min_per_km: 6.67 },
        },
        {
          day: "saturday", workout_type: "rest", distance_km: null, duration_minutes: null, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
        },
        {
          day: "sunday", workout_type: "long_easy", distance_km: 18, duration_minutes: 95, estimated_tss: null,
          reason_codes: [], matching_status: "planned", adherence_status: "not_applicable", actual: null,
          primary_pace: { lower_min_per_km: 5.58, upper_min_per_km: 5.75 },
        },
      ],
      unmatched_actuals: [
        { activity_id: "extra1", distance_km: 5.2, duration_minutes: 30, pace_min_per_km: 5.77, activity_type: "running", start_time: "2026-08-22T06:30:00" },
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
      planned_session: { workout_type: "rest", duration_minutes: null, distance_km: null },
      served_prescription: { workout_type: "rest", duration_minutes: null, distance_km: null, steps: [], primary_pace: null },
      original_prescription: { workout_type: "rest", duration_minutes: null, distance_km: null },
      adapted_prescription: { workout_type: "rest", duration_minutes: null, distance_km: null },
      adaptive_session: null,
      adaptation_applied: false,
      adaptation_reason: "",
    };
  }

  return {
    status: "success",
    readiness: { band: "EASY" },
    // C232 (correction, round 7 — BLOCKER FIX): served_prescription is the
    // REAL backend contract emitted by prescription_to_runtime_session() —
    // legacy keys (type/duration/intensity/estimated_tss) alongside the
    // canonical ones (workout_type/duration_minutes/steps/primary_pace).
    // No `prescription`/`pace_target` string fields exist on the real
    // payload; they must never be asserted against.
    served_prescription: {
      day: "wednesday",
      type: "threshold",
      duration: "55min",
      intensity: "high",
      distance_km: 10,
      estimated_tss: null,
      workout_type: "threshold",
      duration_minutes: 55,
      primary_pace: null,
      steps: [
        { kind: "warmup", repetitions: null, distance_km: 2, duration_minutes: null, pace_zone: "easy", pace_range: null },
        {
          kind: "work", repetitions: 3, distance_km: 2, duration_minutes: null, pace_zone: "threshold",
          pace_range: { lower_min_per_km: 5.1667, upper_min_per_km: 5.25 },
        },
      ],
    },
    planned_session: {
      workout_type: "threshold",
      duration_minutes: 55,
      distance_km: 10,
    },
    original_prescription: {
      workout_type: "threshold",
      duration_minutes: 55,
      distance_km: 10,
    },
    adapted_prescription: {
      workout_type: "threshold",
      duration_minutes: 55,
      distance_km: 10,
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

  test("today card shows only real backend fields: workout type, structural steps, numeric pace and duration", async () => {
    // C232 (correction, round 7 — BLOCKER FIX / test H): the Today card must
    // read ONLY fields that exist in the real served_prescription payload
    // (prescription_to_runtime_session contract) — never a fictitious
    // `prescription`/`pace_target` string. Structural steps (warmup/work)
    // and the work step's NUMERIC frozen pace_range render verbatim.
    mockAxios();
    renderPage();

    const today = await screen.findByTestId("training-v2-today");
    expect(within(today).getByTestId("today-session-type").textContent.toLowerCase()).toContain("threshold");
    expect(within(today).queryByTestId("today-session-prescription")).not.toBeInTheDocument();
    expect(within(today).queryByTestId("today-session-pace-zone")).not.toBeInTheDocument();
    expect(within(today).getByTestId("today-session-duration")).toHaveTextContent("55 min");
    expect(within(today).getByTestId("today-session-distance")).toHaveTextContent(formatDistance(10, { unitSystem: "metric" }));
    expect(within(today).queryByText(/TSS/i)).not.toBeInTheDocument();

    // The two steps sent by the backend render verbatim, and the numeric
    // work-step pace shows the real "5:10–5:15/km" range, not just a zone.
    expect(within(today).getByTestId("session-step-0")).toBeInTheDocument();
    expect(within(today).getByTestId("session-step-1-metric")).toHaveTextContent("5:10");
    expect(within(today).getByTestId("session-step-1-metric")).toHaveTextContent("5:15");
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

  test("C232 (correction round 3) BLOCKER 2: backend reference_date always wins over the browser clock/timezone for 'Today'", async () => {
    // Backend says today is Friday 2026-09-04, while the browser's own clock
    // is mocked to already be Saturday 2026-09-05 (e.g. a different device
    // timezone, or just after local midnight). "Today" must stay Friday —
    // never recomputed from `new Date().getDay()`.
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-09-05T01:30:00Z"));

    const fridayWeek = weekData();
    fridayWeek.reference_date = "2026-09-04";
    // No session carries `planned_date` in this fixture — the fallback
    // (ISO date → UTC weekday, no timezone drift) must still resolve
    // 2026-09-04 to "friday".
    mockAxios({ week: fridayWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    const fridayRow = within(week).getByTestId("training-v2-day-friday");
    expect(within(fridayRow).getByTestId("today-highlight-badge")).toBeInTheDocument();
    // Saturday (the browser's own idea of "today") must NOT be highlighted.
    const saturdayRow = within(week).getByTestId("training-v2-day-saturday");
    expect(within(saturdayRow).queryByTestId("today-highlight-badge")).not.toBeInTheDocument();

    jest.useRealTimers();
  });

  test("C232 (correction round 3) BLOCKER 2: missing/malformed reference_date never fabricates a 'Today' via the browser clock", async () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-09-05T01:30:00Z"));

    const noRefDateWeek = weekData();
    delete noRefDateWeek.reference_date;
    mockAxios({ week: noRefDateWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    // No day should be highlighted as "Today" — `null` stays `null`, never
    // falling back to the browser's own idea of the current weekday.
    expect(within(week).queryByTestId("today-highlight-badge")).not.toBeInTheDocument();

    jest.useRealTimers();
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
        },
        original_prescription: {
          workout_type: "long_easy", duration_minutes: 95, distance_km: 18,
        },
        served_prescription: {
          workout_type: "long_easy", duration_minutes: 66, distance_km: 12.6,
        },
        adapted_prescription: {
          workout_type: "long_easy", duration_minutes: 66, distance_km: 12.6,
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

  // ---------------------------------------------------------------------
  // PR232 — Training UX V3
  // ---------------------------------------------------------------------

  test("PR232: week summary card shows planned volume and session count without opening any session", async () => {
    mockAxios();
    renderPage();

    const summary = await screen.findByTestId("training-v2-week-summary");
    expect(within(summary).getByTestId("week-summary-planned")).toHaveTextContent(
      formatDistance(58, { unitSystem: "metric" })
    );
    expect(within(summary).getByTestId("week-summary-session-count")).toHaveTextContent("1/5");
    expect(within(summary).getByTestId("week-summary-day-dots")).toBeInTheDocument();
  });

  test("PR232: week summary progress is factual — only sums real actual.distance_km, never fabricated", async () => {
    mockAxios();
    renderPage();

    const summary = await screen.findByTestId("training-v2-week-summary");
    // Only monday has an `actual` (8.1 km); every other session is planned/
    // missed/rest with actual=null, so the factual sum must be exactly 8.1.
    expect(within(summary).getByTestId("week-summary-progress-value")).toHaveTextContent(
      formatDistance(8.1, { unitSystem: "metric" })
    );
  });

  test("C232 (correction round 2): week summary distinguishes plan progress from real Garmin volume (matched + unmatched, no double counting)", async () => {
    mockAxios();
    renderPage();

    const summary = await screen.findByTestId("training-v2-week-summary");
    // Plan-side progress stays exactly the matched sum (8.1 km) — never
    // inflated by the unrelated extra Garmin activity.
    expect(within(summary).getByTestId("week-summary-progress-value")).toHaveTextContent(
      formatDistance(8.1, { unitSystem: "metric" })
    );
    // Real Garmin volume this week = matched (8.1) + unmatched (5.2) = 13.3,
    // shown as a DISTINCT figure, never presented as "plan progress" — it
    // can (and here does) exceed the planned volume.
    expect(within(summary).getByTestId("week-summary-real-volume")).toHaveTextContent(
      formatDistance(13.3, { unitSystem: "metric" })
    );
  });

  test("PR232: a simple session card shows distance and primary pace directly, no expansion needed", async () => {
    mockAxios();
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    const fridayRow = within(week).getByTestId("training-v2-day-friday");
    expect(within(fridayRow).getByTestId("training-v2-day-pace-friday")).toBeInTheDocument();
    expect(fridayRow.textContent).toMatch(formatDistance(7, { unitSystem: "metric" }));
  });

  test("C232 (correction): a quality session never renders a fabricated pace or split structure", async () => {
    mockAxios();
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    const wednesdayRow = within(week).getByTestId("training-v2-day-wednesday");
    // No pace line rendered for "quality" — the engine has not decided its
    // exact nature (BLOCKER 1 fix: no fabricated Threshold zone/intervals).
    expect(within(wednesdayRow).queryByTestId("training-v2-day-pace-wednesday")).not.toBeInTheDocument();
    // No blocks/splits section ever rendered — the feature has been removed.
    expect(within(week).queryByTestId("session-blocks-wednesday")).not.toBeInTheDocument();
  });

  test("C232 (correction): an easy/long_easy session shows only the honest whole-session pace zone, never a fabricated split", async () => {
    mockAxios();
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    fireEvent.click(within(week).getByTestId("training-v2-day-toggle-sunday"));

    const sundayRow = within(week).getByTestId("training-v2-day-sunday");
    expect(within(sundayRow).getByTestId("training-v2-day-pace-sunday")).toBeInTheDocument();
    // No numbered/labelled split blocks exist anywhere in the week view.
    expect(within(week).queryByTestId("session-blocks-sunday")).not.toBeInTheDocument();
    expect(within(week).queryByTestId(/^session-block-/)).not.toBeInTheDocument();
  });

  test("C232 (correction round 3, tests 1/2/9): quality/long_easy/prescription_unavailable sessions never render a steps section (steps=[] today)", async () => {
    mockAxios();
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    for (const day of ["wednesday", "sunday"]) {
      fireEvent.click(within(week).getByTestId(`training-v2-day-toggle-${day}`));
      const row = within(week).getByTestId(`training-v2-day-${day}`);
      expect(within(row).queryByTestId("session-steps")).not.toBeInTheDocument();
    }
  });

  test("C232 (correction round 3, tests 3/4/5): a session with explicit engine steps renders EXACTLY those steps, no recomputed total/repetition/recovery", async () => {
    const structuredWeek = weekData();
    // Simulates a FUTURE engine capability (WorkoutGenerator does not
    // populate this yet) — the frontend must render it verbatim, with no
    // client-side aggregation, invented repetition count, or recovery.
    structuredWeek.week.sessions[2] = {
      ...structuredWeek.week.sessions[2],
      steps: [
        { kind: "warmup", repetitions: null, distance_km: 2, duration_minutes: null, pace_zone: "easy" },
        { kind: "work", repetitions: 3, distance_km: 2, duration_minutes: null, pace_zone: "threshold" },
        { kind: "recovery", repetitions: null, distance_km: null, duration_minutes: 2, pace_zone: null },
        { kind: "cooldown", repetitions: null, distance_km: 1, duration_minutes: null, pace_zone: "easy" },
      ],
    };
    mockAxios({ week: structuredWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    fireEvent.click(within(week).getByTestId("training-v2-day-toggle-wednesday"));
    const wednesdayRow = within(week).getByTestId("training-v2-day-wednesday");

    const steps = within(wednesdayRow).getByTestId("session-steps");
    expect(steps).toBeInTheDocument();
    // Exactly the 4 given steps — never a 5th fabricated one, never merged.
    expect(within(steps).getByTestId("session-step-0-metric")).toHaveTextContent(
      `${formatDistance(2, { unitSystem: "metric" })} @`
    );
    expect(within(steps).getByTestId("session-step-1-metric")).toHaveTextContent(
      `3 × ${formatDistance(2, { unitSystem: "metric" })}`
    );
    expect(within(steps).getByTestId("session-step-2-metric")).toHaveTextContent("2 min");
    expect(within(steps).getByTestId("session-step-3-metric")).toHaveTextContent(
      formatDistance(1, { unitSystem: "metric" })
    );
    expect(within(steps).queryByTestId("session-step-4")).not.toBeInTheDocument();

    // Every other session still has no steps section (nothing invented for
    // any other card as a side effect of one session having explicit steps).
    for (const day of ["monday", "tuesday", "thursday", "friday", "saturday", "sunday"]) {
      const row = within(week).getByTestId(`training-v2-day-${day}`);
      if (within(row).queryByTestId(`training-v2-day-toggle-${day}`)) {
        fireEvent.click(within(row).getByTestId(`training-v2-day-toggle-${day}`));
      }
      expect(within(row).queryByTestId("session-steps")).not.toBeInTheDocument();
    }
  });

  test("C232 (correction round 3, test 10): imperial unit system converts step distances to miles, never forces /km on a step's pace zone", async () => {
    const structuredWeek = weekData();
    structuredWeek.week.sessions[2] = {
      ...structuredWeek.week.sessions[2],
      steps: [
        { kind: "work", repetitions: 3, distance_km: 2, duration_minutes: null, pace_zone: "threshold" },
      ],
    };
    mockAxios({ week: structuredWeek });
    renderPage({ width: 390, unitSystem: "imperial" });

    const week = await screen.findByTestId("training-v2-week");
    fireEvent.click(within(week).getByTestId("training-v2-day-toggle-wednesday"));
    const wednesdayRow = within(week).getByTestId("training-v2-day-wednesday");
    const stepMetric = within(wednesdayRow).getByTestId("session-step-0-metric");
    expect(stepMetric.textContent).toContain(formatDistance(2, { unitSystem: "imperial" }));
    expect(stepMetric.textContent).not.toMatch(/\/km/);
  });

  test("PR232: expanding a matched session shows the prescribed vs actually performed comparison", async () => {
    mockAxios();
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    fireEvent.click(within(week).getByTestId("training-v2-day-toggle-monday"));

    const comparison = within(week).getByTestId("session-actual-comparison");
    expect(within(comparison).getByTestId("session-actual-distance")).toHaveTextContent(
      formatDistance(8.1, { unitSystem: "metric" })
    );
    expect(within(comparison).getByTestId("session-actual-duration")).toHaveTextContent("44 min");
  });

  test("PR232: unmatched Garmin activities are shown as extra activities, never attached to a prescribed session card", async () => {
    mockAxios();
    renderPage();

    const section = await screen.findByTestId("training-v2-unmatched-actuals");
    expect(within(section).getByTestId("unmatched-actual-0")).toHaveTextContent(
      formatDistance(5.2, { unitSystem: "metric" })
    );
    // Must not appear nested inside any day's session card.
    const week = screen.getByTestId("training-v2-week");
    expect(within(week).queryByTestId("unmatched-actual-0")).not.toBeInTheDocument();
  });

  test("PR232: prescription_unavailable session never renders blocks or a primary pace", async () => {
    const unavailableWeek = weekData();
    unavailableWeek.week.sessions[3] = {
      day: "thursday",
      workout_type: null,
      distance_km: null,
      duration_minutes: null,
      estimated_tss: null,
      reason_codes: [],
      matching_status: null,
      adherence_status: null,
      actual: null,
      execution_status: "prescription_unavailable",
      primary_pace: null,
    };

    mockAxios({ week: unavailableWeek });
    renderPage({ width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    const thursdayRow = within(week).getByTestId("training-v2-day-thursday");
    expect(within(thursdayRow).queryByTestId(/training-v2-day-pace-/)).not.toBeInTheDocument();
    expect(thursdayRow.querySelector('[data-testid="training-v2-day-toggle-thursday"]').getAttribute("aria-expanded")).toBeNull();
  });

  test("PR232: imperial unit system never shows a /km suffix on any pace, including splits and week paces", async () => {
    mockAxios();
    renderPage({ unitSystem: "imperial", width: 390 });

    const week = await screen.findByTestId("training-v2-week");
    fireEvent.click(within(week).getByTestId("training-v2-day-toggle-wednesday"));
    expect(week.textContent).not.toMatch(/\/km/);
    expect(week.textContent).toMatch(/\/mi/);

    const paces = screen.getByTestId("training-v2-paces");
    fireEvent.click(within(paces).getByTestId("paces-collapsible-trigger"));
    expect(paces.textContent).not.toMatch(/\/km/);
  });

  test("PR232: narrow mobile viewport still renders the week summary and all session cards", async () => {
    mockAxios();
    renderPage({ width: 360 });

    await screen.findByTestId("training-v2-week-summary");
    const week = await screen.findByTestId("training-v2-week");
    DAYS_ORDER.forEach((day) => {
      expect(within(week).getByTestId(`training-v2-day-${day}`)).toBeInTheDocument();
    });
  });
});

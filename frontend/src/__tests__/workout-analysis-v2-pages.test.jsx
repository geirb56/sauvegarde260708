import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, Link, useLocation } from "react-router-dom";
import axios from "axios";

import WorkoutDetail, { formatDistance, formatSignedDistance } from "@/pages/WorkoutDetail";
import Sessions from "@/pages/Sessions";
import Coach from "@/pages/Coach";
import DetailedAnalysis from "@/pages/DetailedAnalysis";
import SessionDetail from "@/pages/SessionDetail";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { translations, LANGUAGE_STORAGE_KEY } from "@/lib/i18n";
import { formatPaceDisplay, formatPaceDelta } from "@/lib/workoutAnalysis";
import { getCoachConclusions, getAnalysisTakeaway, getAnalysisObservations, getDistinctCoachObservation } from "@/lib/workoutAnalysis";

jest.mock("axios");
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(),
}));

const workout = {
  id: "w1",
  type: "run",
  name: "Morning Run",
  date: "2024-01-10T07:00:00Z",
  distance_km: 10,
  duration_minutes: 60,
  avg_heart_rate: 150,
  max_heart_rate: 170,
  avg_pace_min_km: 6,
  km_splits: [
    { km: 1, pace_min_km: 5.9, pace_str: "5:54" },
    { km: 2, pace_min_km: 6.1, pace_str: "6:06" },
  ],
};

const analysis = {
  version: "v2",
  workout: { id: "w1", name: "Morning Run", date: "2024-01-10T07:00:00Z", type: "run" },
  summary: { code: "summary.standard_structural", text: "Standard-duration session completed." },
  signals: {
    intensity: {
      available: false,
      code: null,
      text: null,
      reason_unavailable: "Intensity classification is unavailable without individualized physiological evidence.",
    },
    volume: { available: true, code: "usual_recent", text: "Close to recent volume", reason_unavailable: null },
    session_type: { available: true, code: "standard", text: "Standard session", reason_unavailable: null },
  },
  physiology: {
    available: true,
    avg_hr: 150,
    max_hr: 170,
    zone_distribution: { z1: 20, z2: 50, z3: 20, z4: 10, z5: 0 },
    hr_drift: 5,
    reason_unavailable: null,
  },
  pacing: {
    available: true,
    average_pace_min_km: 6,
    average_speed_kmh: null,
    fastest_split_min_km: 5.9,
    slowest_split_min_km: 6.1,
    pace_drop_min_km: 0.2,
    negative_split: false,
    consistency_score: 90,
    variability: 0.1,
    reason_unavailable: null,
  },
  comparison: {
    available: true,
    baseline_period_days: 14,
    baseline_sample_count: 2,
    distance_km: { current: 10, baseline: 9, difference: 1, percent_change: 11.1 },
    duration_minutes: { current: 60, baseline: 58, difference: 2, percent_change: 3.4 },
    avg_heart_rate: { current: 150, baseline: 146, difference: 4, percent_change: 2.7 },
    avg_pace_min_km: { current: 6, baseline: 6.1, difference: -0.1, percent_change: -1.6 },
    avg_speed_kmh: null,
    reason_unavailable: null,
  },
  meaning: { code: "meaning.hr_without_intensity_with_pacing", text: "Heart-rate facts are available, but intensity classification is unavailable without trustworthy zone evidence, so this session is interpreted structurally." },
  advice: { available: true, code: "advice.maintain_consistency", text: "The recorded pace stayed consistent during this session." },
  evidence: {
    has_heart_rate: true,
    has_hr_zones: true,
    has_splits: true,
    has_baseline: true,
    has_cadence: false,
    has_elevation: false,
  },
};

const analysisMissingEvidence = {
  ...analysis,
  signals: {
    intensity: {
      available: false,
      code: null,
      text: null,
      reason_unavailable: "Intensity classification is unavailable without individualized physiological evidence.",
    },
    volume: {
      available: true,
      code: "medium_volume",
      text: "Moderate session volume",
      reason_unavailable: null,
    },
    session_type: {
      available: true,
      code: "standard",
      text: "Standard session",
      reason_unavailable: null,
    },
  },
  physiology: {
    available: false,
    avg_hr: null,
    max_hr: null,
    zone_distribution: null,
    hr_drift: null,
    reason_unavailable: "Heart-rate evidence is unavailable.",
  },
  pacing: {
    available: false,
    average_pace_min_km: null,
    average_speed_kmh: null,
    fastest_split_min_km: null,
    slowest_split_min_km: null,
    pace_drop_min_km: null,
    negative_split: null,
    consistency_score: null,
    variability: null,
    reason_unavailable: "Pacing evidence is unavailable.",
  },
  evidence: {
    has_heart_rate: false,
    has_hr_zones: false,
    has_splits: false,
    has_baseline: false,
    has_cadence: false,
    has_elevation: false,
  },
  comparison: {
    available: false,
    baseline_period_days: 14,
    baseline_sample_count: 0,
    distance_km: null,
    duration_minutes: null,
    avg_heart_rate: null,
    avg_pace_min_km: null,
    avg_speed_kmh: null,
    reason_unavailable: "No prior same-type workouts in the last 14 days.",
  },
};

const makeStructuredPhaseAnalysis = () => {
  const effortPaces = [288.4, 282, 271, 291];
  const effortDistances = [832, 851, 886, 825];
  const effortHeartRates = [151, 157, 159, 159];
  const efforts = effortPaces.map((pace, index) => ({
    order: index * 2 + 1,
    phase_type: "effort",
    effort_number: index + 1,
    duration_s: 240,
    distance_m: effortDistances[index],
    pace_sec_per_km: pace,
    average_hr: effortHeartRates[index],
    max_hr: [160, 165, 175, 166][index],
  }));
  const recoveries = effortPaces.map((_, index) => ({
    order: index * 2 + 2,
    phase_type: "recovery",
    recovery_number: index + 1,
    duration_s: 120,
    distance_m: 180,
    pace_sec_per_km: 666,
    average_hr: 130,
    max_hr: 145,
  }));
  const phases = efforts.flatMap((effort, index) => [effort, recoveries[index]]);

  return {
    available: true,
    analysis_type: "structured_phases",
    phases,
    efforts,
    recoveries,
    effort_statistics: {
      count: 4,
      total_duration_s: 960,
      total_distance_m: 3394,
      average_pace_sec_per_km: 283,
      average_hr: 156.5,
      max_hr: 175,
    },
    recovery_statistics: { count: 4, total_duration_s: 480, total_distance_m: 720 },
    effort_regularity: {
      available: true,
      effort_count: 4,
      comparable_effort_count: 4,
      comparability_basis: "duration",
      pace_sample_count: 4,
      partial_comparison: false,
      pace_dispersion_sec_per_km: 7.7,
      first_to_last_pace_change_sec_per_km: 2.6,
      average_hr_change_bpm: 8,
    },
    missing_data: [],
    limitations: [],
  };
};

function renderWithProviders(ui, route, language = "en", unitSystem = "metric") {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  window.localStorage.setItem("runindex_unit_system", unitSystem);
  return render(
    <LanguageProvider>
      <UnitProvider>
        <MemoryRouter initialEntries={[route]}>
          {ui}
        </MemoryRouter>
      </UnitProvider>
    </LanguageProvider>,
  );
}

const LocationDisplay = () => {
  const { pathname, search } = useLocation();
  return <span data-testid="current-location">{pathname}{search}</span>;
};

function setAnalysisAccess({ loading = false, allowed = true } = {}) {
  useSubscription.mockReturnValue({
    loading,
    hasFeature: (feature) => feature === "coach_workout_analysis" && allowed,
  });
}

function mockAxios({ analysisPayload = analysis, workoutPayload = workout, delayedAnalysis = null, rejectAnalysis = false } = {}) {
  axios.get.mockImplementation((url) => {
    if (url.includes("/workouts/w1")) {
      return Promise.resolve({ data: workoutPayload });
    }
    if (url.includes("/coach/workout-analysis/w1")) {
      if (rejectAnalysis) {
        return Promise.reject(new Error("analysis failed"));
      }
      if (delayedAnalysis) {
        return delayedAnalysis;
      }
      return Promise.resolve({ data: analysisPayload });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  setAnalysisAccess();
});

const coachConclusion = (updates = {}) => ({
  code: "coach.pacing",
  text: "Tu as gardé une allure stable sur les kilomètres enregistrés.",
  category: "pacing",
  priority: 30,
  available: true,
  kind: "conclusion",
  evidence: { split_count: 4, fastest_pace_sec_per_km: 300, slowest_pace_sec_per_km: 304 },
  replaces_factual_codes: ["fact.pace_change"],
  ...updates,
});

const coachScreens = [
  ["workout", "/workout/w1", "/workout/:id", WorkoutDetail],
  ["session", "/session/w1", "/session/:id", SessionDetail],
  ["detailed", "/analysis/w1", "/analysis/:id", DetailedAnalysis],
];

test("Coach V1 validates evidence, sorts, deduplicates and never pads conclusions", () => {
  const primary = coachConclusion({ code: "coach.execution.pace_hr", category: "execution", priority: 10 });
  const history = coachConclusion({ code: "coach.history.pace", category: "history", priority: 40, text: "Historical pace." });
  const payload = { coach_language: { version: "v1", conclusions: [
    history,
    coachConclusion({ evidence: { value: NaN } }),
    coachConclusion({ evidence: { value: "300" } }),
    coachConclusion({ evidence: {} }),
    coachConclusion({ available: false }),
    coachConclusion({ priority: Infinity }),
    coachConclusion({ category: "" }),
    coachConclusion({ kind: "unsupported" }),
    coachConclusion({ text: "Complement." }),
    primary,
    coachConclusion({ code: "duplicate-category", text: "Same phenomenon." }),
    coachConclusion({ code: "fourth", category: "other", priority: 50, text: "Not selected." }),
  ] } };
  expect(getCoachConclusions(payload).map((item) => item.code)).toEqual([
    "coach.execution.pace_hr", "coach.pacing", "coach.history.pace",
  ]);
  expect(payload.coach_language.conclusions[0]).toBe(history);
  expect(getCoachConclusions({ coach_language: { version: "v1", conclusions: [primary] } })).toEqual([primary]);
  expect(getCoachConclusions({ coach_language: { version: "v1", conclusions: [] } })).toEqual([]);
  expect(getCoachConclusions({ coach_language: { version: "v2", conclusions: [primary] } })).toEqual([]);
});

test.each(coachScreens)("%s renders Coach V1 before factual phase and split details without duplicates", async (_, route, path, Page) => {
  const primary = coachConclusion();
  const extra = coachConclusion({
    code: "coach.history.hr", category: "history_hr", priority: 40,
    text: "Ta fréquence cardiaque moyenne est supérieure de 4 bpm aux sorties comparables.",
    evidence: { current_hr_bpm: 154, baseline_hr_bpm: 150, difference_bpm: 4 },
    replaces_factual_codes: ["fact.similar_hr"],
  });
  mockAxios({ analysisPayload: {
    ...analysis,
    phase_analysis: makeStructuredPhaseAnalysis(),
    coach_language: { version: "v1", conclusions: [extra, primary] },
    meaning: { ...analysis.meaning, factual_observations: [
      { code: "fact.pace_change", placement: "summary", text: "Replaced pace fact.", evidence: { delta: 4 } },
      { code: "fact.similar_hr", placement: "summary", text: "Replaced HR fact.", evidence: { delta: 4 } },
      { code: "fact.other", placement: "summary", text: "A distinct factual detail.", evidence: { count: 6 } },
    ] },
  } });
  renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, "fr");
  expect(await screen.findByTestId("coach-primary")).toHaveTextContent(primary.text);
  expect(screen.getAllByTestId("coach-complementary")).toHaveLength(1);
  expect(screen.getByTestId("coach-complementary")).toHaveTextContent(extra.text);
  expect(screen.getByTestId("coach-primary").compareDocumentPosition(screen.getByTestId("structured-phase-analysis")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByTestId("coach-primary").compareDocumentPosition(screen.getByTestId("kilometer-splits")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText("A distinct factual detail.")).toBeInTheDocument();
  expect(screen.queryByText("Replaced pace fact.")).not.toBeInTheDocument();
  expect(screen.queryByText("Replaced HR fact.")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
});

describe.each(coachScreens)("%s Coach V1 access and localization", (_, route, path, Page) => {
  test.each([
    ["fr", "Tu as accéléré de 30 secondes par kilomètre."],
    ["en", "You ran 30 seconds per kilometre faster."],
    ["es", "Corriste 30 segundos por kilómetro más rápido."],
  ])("preserves the localized backend conclusion in %s", async (language, text) => {
    mockAxios({ analysisPayload: { ...analysis, coach_language: {
      version: "v1", conclusions: [coachConclusion({ text })],
    } } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
    expect(await screen.findByTestId("coach-primary")).toHaveTextContent(text);
    expect(axios.get.mock.calls.some(([url]) => url.includes(`language=${language}`))).toBe(true);
  });

  test.each([{ allowed: false }, { loading: true }])("does not fetch or expose Coach V1 without entitlement: %j", async (access) => {
    setAnalysisAccess(access);
    mockAxios({ analysisPayload: { ...analysis, coach_language: {
      version: "v1", conclusions: [coachConclusion()],
    } } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    await waitFor(() => {
      if (Page !== DetailedAnalysis) expect(axios.get.mock.calls.some(([url]) => url.includes("/workouts/w1"))).toBe(true);
      expect(screen.queryByTestId("coach-language")).not.toBeInTheDocument();
    });
    expect(axios.get.mock.calls.some(([url]) => url.includes("/coach/workout-analysis/"))).toBe(false);
  });

  test("empty or invalid conclusions preserve honest fallback and suppress legacy generic advice", async () => {
    mockAxios({ analysisPayload: { ...analysisMissingEvidence, coach_language: {
      version: "v1", conclusions: [coachConclusion({ evidence: { value: null } })],
    } } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("analysis-fallback")).toBeInTheDocument();
    expect(screen.queryByTestId("coach-primary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
    expect(screen.queryByTestId("header-context")).not.toBeInTheDocument();
  });
});

test("legacy takeaway fields never become factual observations, including trusted intensity and phases", () => {
  expect(getAnalysisTakeaway({
    meaning: { text: "Legacy historical figures.", observations: [], caveats: ["Scientific uncertainty."] },
    signals: { intensity: { available: true } },
  })).toBeNull();
  expect(getAnalysisTakeaway({
    meaning: { code: "meaning.consistent_pacing", observations: ["Unsupported intensity classification."] },
    signals: { intensity: { available: false } },
  })).toBeNull();
  expect(getAnalysisTakeaway({
    meaning: { code: "meaning.structured_phases", observations: ["Effort dispersion: 7.7 s/km.", "Second observation."] },
    phase_analysis: { effort_regularity: { available: true } },
    signals: { intensity: { available: false } },
  })).toBeNull();
  expect(getAnalysisTakeaway({
    meaning: { code: "meaning.structured_phases", observations: ["Physiological conclusion."] },
    phase_analysis: { effort_regularity: { available: false } },
    signals: { intensity: { available: false } },
  })).toBeNull();
  expect(getAnalysisTakeaway({
    meaning: { code: "meaning.with_hr_high", observations: ["Reliable high-intensity classification."] },
    signals: { intensity: { available: true, code: "high" } },
  })).toBeNull();
  expect(getAnalysisTakeaway({
    meaning: { code: "meaning.with_hr_high", observations: ["Unsupported high-intensity classification."] },
    signals: { intensity: { available: false, code: null } },
  })).toBeNull();
});

test.each(["fr", "en", "es"])("interval analysis hides diagnostics and history in %s", async (language) => {
  const labels = translations[language].workoutDetailExtended;
  const payload = {
    ...analysis,
    signals: { ...analysis.signals, session_structure: { available: true, code: "intervals" } },
    meaning: {
      ...analysis.meaning,
      code: "meaning.structured_phases",
      text: "Legacy facts and historical comparison 14 days 180 days.",
      observations: ["Synthetic effort dispersion 7.7 s/km.", "Synthetic HR 151 to 159 bpm."],
      caveats: ["Synthetic physiological uncertainty."],
    },
    phase_analysis: makeStructuredPhaseAnalysis(),
    evidence: { ...analysis.evidence, has_splits: false, has_structured_phases: true },
    comparison: {
      ...analysis.comparison,
      similar: { available: true, comparable: false, period_days: 180, sample_count: 2, avg_pace_min_km: 6 },
    },
  };
  mockAxios({ analysisPayload: payload, workoutPayload: { ...workout, km_splits: [] } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1", language);
  const section = await screen.findByTestId("structured-phase-analysis");
  expect(screen.getByTestId("session-classification")).toHaveTextContent(`${labels.structure}: ${labels.structureIntervals}`);
  expect(screen.queryByText(/Standard session/)).not.toBeInTheDocument();
  expect(section).toHaveTextContent(labels.averageEffortPace);
  expect(screen.getByTestId("effort-regularity")).toHaveTextContent("7,7 s/km".replace(",", language === "en" ? "." : ","));
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.queryByText(/14 days|180 days|historical comparison|Synthetic physiological uncertainty/)).not.toBeInTheDocument();
  expect(screen.queryByText(translations[language].workoutDetailExtended.intensityUnavailable)).not.toBeInTheDocument();
});

test.each([
  ["continuous", true, true, "continuous"],
  ["absent", false, false, null],
  ["unknown", true, false, null],
  ["mixed", true, true, null],
])("PR328 keeps the three evidence levels separate for %s", async (_, available, classified, structure) => {
  mockAxios({
    analysisPayload: {
      ...analysis,
      signals: { ...analysis.signals, session_structure: { available: Boolean(structure), code: structure } },
      phase_analysis: { available, phases: [], efforts: [], recoveries: [] },
      evidence: { ...analysis.evidence, has_splits: false, has_structured_phases: classified },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  if (structure) {
    expect(screen.getByTestId("session-classification")).toHaveTextContent("Structure: Continuous");
  } else {
    expect(screen.queryByTestId("session-classification")).not.toBeInTheDocument();
  }
  expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.queryByText(translations.en.workoutDetailExtended.intensityUnavailable)).not.toBeInTheDocument();
});

test("historical references are hidden even when the backend returns comparable distances", async () => {
  mockAxios({ analysisPayload: {
    ...analysis,
    comparison: { ...analysis.comparison, similar: { available: true, comparable: true, period_days: 180, avg_pace_min_km: 6 } },
  } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByText(/180 days|similar workouts|reference sessions/i)).not.toBeInTheDocument();
});

test.each([
  ["DetailedAnalysis", "/analysis/w1", "/analysis/:id", DetailedAnalysis],
  ["SessionDetail", "/session/w1", "/session/:id", SessionDetail],
])("%s shares compact phase presentation and suppresses caveats", async (_, route, path, Page) => {
  mockAxios({ analysisPayload: {
    ...analysis,
    signals: { ...analysis.signals, session_structure: { available: true, code: "intervals" } },
    meaning: { ...analysis.meaning, code: "meaning.structured_phases", observations: ["Compact synthetic execution."], caveats: ["Scientific reserve."] },
    phase_analysis: makeStructuredPhaseAnalysis(),
  } });
  renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
  expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
  expect(screen.queryByText("Compact synthetic execution. Scientific reserve.")).not.toBeInTheDocument();
  expect(screen.queryByText("Scientific reserve.")).not.toBeInTheDocument();
  expect(screen.getByText(/Intervals/)).toBeVisible();
  expect(screen.queryByText("Standard session")).not.toBeInTheDocument();
  expect(screen.queryByText(analysis.meaning.text)).not.toBeInTheDocument();
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
});

test("WorkoutDetail makes only one canonical analysis request", async () => {
  mockAxios();

  renderWithProviders(
    <Routes>
      <Route path="/workout/:id" element={<WorkoutDetail />} />
    </Routes>,
    "/workout/w1",
  );

  expect(screen.getByText(/analyzing/i)).toBeInTheDocument();
  await screen.findByTestId("coach-summary");

  const analysisCalls = axios.get.mock.calls
    .map(([url]) => url)
    .filter((url) => url.includes("/coach/") || url.includes("/rag/"));

  expect(analysisCalls).toEqual([expect.stringContaining("/coach/workout-analysis/w1")]);
  expect(analysisCalls.some((url) => url.includes("/coach/detailed-analysis/"))).toBe(false);
  expect(analysisCalls.some((url) => url.includes("/rag/workout/"))).toBe(false);
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.getByTestId("analysis-fallback")).toBeVisible();
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10 km");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("1h");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("6:00/km");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("150 bpm");
  expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Coach observation" })).not.toBeInTheDocument();
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
  expect(screen.queryByText("Easy effort")).not.toBeInTheDocument();
  expect(screen.queryByText("High intensity")).not.toBeInTheDocument();
  expect(screen.queryByText("Balanced")).not.toBeInTheDocument();
});

test("WorkoutDetail hides physiology and pacing cards when evidence is unavailable", async () => {
  mockAxios({ analysisPayload: analysisMissingEvidence });

  renderWithProviders(
    <Routes>
      <Route path="/workout/:id" element={<WorkoutDetail />} />
    </Routes>,
    "/workout/w1",
  );

  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("pacing-summary-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("available-intensity")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByText(analysisMissingEvidence.signals.intensity.reason_unavailable)).not.toBeInTheDocument();
  expect(screen.queryByText("Pacing evidence is unavailable.")).not.toBeInTheDocument();
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("150 bpm");
});

test("structured phases show compact 4×4 efforts with collapsed ordered recoveries", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: phaseAnalysis } });

  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );

  const section = await screen.findByTestId("structured-phase-analysis");
  expect(screen.getByTestId("phase-summary")).toHaveTextContent("Efforts: 4");
  expect(screen.getByTestId("phase-summary")).toHaveTextContent("Recoveries: 4");
  expect(section).toHaveTextContent("4:43/km");
  expect(section).toHaveTextContent("7.7 s/km");
  const effortRows = within(section).getAllByTestId("phase-effort-row");
  expect(effortRows).toHaveLength(4);
  expect(within(section).getAllByTestId("phase-recovery-row")).toHaveLength(4);
  expect(within(section).getAllByTestId("phase-recovery-row").every((row) => !row.open)).toBe(true);
  effortRows.forEach((row, index) => {
    expect(row).toHaveTextContent(`Effort ${index + 1}`);
    expect(within(row).getByTestId("phase-recovery-row")).toHaveTextContent(`Recovery ${index + 1}`);
  });
  expect(section).toHaveTextContent("4:48/km");
  expect(section).toHaveTextContent("151 bpm");
  expect(section).not.toHaveTextContent("175 bpm");
  expect(section).not.toHaveTextContent("832 m");
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(axios.get).toHaveBeenCalledTimes(2);
});

test("structured phases sort efforts and recoveries by their recorded order", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        efforts: [...phaseAnalysis.efforts].reverse(),
        recoveries: [...phaseAnalysis.recoveries].reverse(),
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  const effortRows = within(section).getAllByTestId("phase-effort-row");
  expect(effortRows[0]).toHaveTextContent("Effort 1");
  expect(effortRows[0]).toHaveTextContent("4:48/km");
  expect(effortRows[3]).toHaveTextContent("Effort 4");
  expect(effortRows[3]).toHaveTextContent("4:51/km");
});

test("unavailable or absent phase_analysis preserves standard Workout Detail without an empty phase section", async () => {
  for (const phaseAnalysis of [undefined, { available: false, analysis_type: "standard", efforts: [], limitations: ["structured_phases_unavailable"] }]) {
    mockAxios({
      analysisPayload: phaseAnalysis === undefined ? analysis : { ...analysis, phase_analysis: phaseAnalysis },
    });

    const { unmount } = renderWithProviders(
      <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
      "/workout/w1",
    );
    await screen.findByTestId("coach-summary");
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10 km");
    expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
    unmount();
  }
});

test.each([
  ["WorkoutDetail", "/workout/w1", "/workout/:id", WorkoutDetail, "workout-detail"],
  ["DetailedAnalysis", "/workout/w1/analysis", "/workout/:id/analysis", DetailedAnalysis, "detailed-analysis"],
  ["SessionDetail", "/sessions/w1", "/sessions/:id", SessionDetail, "session-detail-page"],
])("%s renders available recorded kilometer splits compactly and in source order", async (_name, route, path, Page, pageId) => {
  mockAxios({
    workoutPayload: {
      ...workout,
      km_splits: [
        { km: 2, pace_min_km: 5.5, avg_hr: 149 },
        { km: 1, pace_min_km: 6 },
        null,
        { km: 3, pace_min_km: null },
        { km: 4, pace_min_km: -1 },
      ],
    },
  });
  renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
  await screen.findByTestId(pageId);
  const section = screen.getByTestId("kilometer-splits");
  expect(section.open).toBe(false);
  const rows = within(section).getAllByTestId("kilometer-split-row");
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("Km 2");
  expect(rows[0]).toHaveTextContent("5:30 /km");
  expect(rows[0]).toHaveTextContent("149 bpm");
  expect(rows[1]).toHaveTextContent("Km 1");
  expect(rows[1]).toHaveTextContent("6:00 /km");
  expect(section.querySelector("svg, canvas")).toBeNull();
});

test.each([
  ["WorkoutDetail", "/workout/w1", "/workout/:id", WorkoutDetail, "workout-detail"],
  ["DetailedAnalysis", "/workout/w1/analysis", "/workout/:id/analysis", DetailedAnalysis, "detailed-analysis"],
  ["SessionDetail", "/sessions/w1", "/sessions/:id", SessionDetail, "session-detail-page"],
])("%s keeps supported 4×4 effort regularity when intensity is unavailable", async (_name, route, path, Page, pageId) => {
  mockAxios({
    analysisPayload: {
      ...analysis,
      signals: { ...analysis.signals, intensity: { available: false, code: null, text: null } },
      meaning: {
        code: "meaning.structured_phases",
        text: "Execution details and unavailable intensity caveat.",
        observations: ["Measured comparable efforts show 7.7 s/km pace dispersion."],
      },
      advice: {
        available: true,
        code: "advice.structured_phases",
        text: "The final effort was faster. Physiological intensity cannot be reliably determined.",
      },
      phase_analysis: makeStructuredPhaseAnalysis(),
    },
  });
  renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
  await screen.findByTestId(pageId);
  expect(screen.getByTestId("effort-regularity")).toHaveTextContent("7.7 s/km");
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  expect(screen.getByTestId("structured-phase-analysis")).toHaveAttribute("data-testid", "structured-phase-analysis");
  expect(screen.queryByText("Execution details and unavailable intensity caveat.")).not.toBeInTheDocument();
  expect(screen.queryByText(/intensity.*unavailable/i)).not.toBeInTheDocument();
  expect(screen.queryByText("The final effort was faster. Physiological intensity cannot be reliably determined.")).not.toBeInTheDocument();
});

test.each([
  null,
  [],
  [null, { km: 1, pace_min_km: null }, { km: 2, pace_min_km: 0 }],
])("WorkoutDetail omits absent or unusable kilometer splits: %s", async (km_splits) => {
  mockAxios({ workoutPayload: { ...workout, km_splits } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("workout-detail");
  expect(screen.queryByTestId("kilometer-splits")).not.toBeInTheDocument();
});

test.each([
  ["WorkoutDetail", "/workout/w1", "/workout/:id", WorkoutDetail, "workout-detail"],
  ["DetailedAnalysis", "/workout/w1/analysis", "/workout/:id/analysis", DetailedAnalysis, "detailed-analysis"],
  ["SessionDetail", "/sessions/w1", "/sessions/:id", SessionDetail, "session-detail-page"],
])("%s omits kilometer splits when absent or unusable", async (_name, route, path, Page, pageId) => {
  mockAxios({ workoutPayload: { ...workout, km_splits: null } });
  renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
  await screen.findByTestId(pageId);
  expect(screen.queryByTestId("kilometer-splits")).not.toBeInTheDocument();
});

test("kilometer split pace respects units and sport-specific speed display", async () => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle", km_splits: [{ km: 1, pace_min_km: 2.5 }] },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
    "en",
    "imperial",
  );
  const section = await screen.findByTestId("kilometer-splits");
  expect(within(section).getByTestId("kilometer-split-row")).toHaveTextContent("14.9 mph");
});

test("collapsed kilometer splits use a wrapping mobile layout without a chart", async () => {
  mockAxios();
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("kilometer-splits");
  const row = within(section).getAllByTestId("kilometer-split-row")[0];
  expect(section).toHaveClass("min-w-0");
  expect(row).toHaveClass("min-w-0");
  expect(row).toHaveClass("flex");
  expect(section.querySelector("table, svg, canvas")).toBeNull();
});

test("one effort is shown without a regularity judgment", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  const effort = { ...phaseAnalysis.efforts[0], order: 1, effort_number: 1 };
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        phases: [effort],
        efforts: [effort],
        recoveries: [],
        effort_statistics: { count: 1, total_duration_s: 240, total_distance_m: 832, average_pace_sec_per_km: 288.4 },
        recovery_statistics: { count: 0 },
        effort_regularity: { available: false, effort_count: 1, comparable_effort_count: 1 },
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  expect(within(section).getAllByRole("listitem")).toHaveLength(1);
  expect(section).toHaveTextContent("4:00");
  expect(screen.queryByTestId("effort-regularity")).not.toBeInTheDocument();
  expect(section).not.toHaveTextContent("Following recovery");
});

test("unknown phases remain chronological, use a neutral label, and do not invent recovery links", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  const [effort1, recovery1, effort2, recovery2, effort3, recovery3, effort4, recovery4] = phaseAnalysis.phases;
  const unknown = { order: 2, phase_type: "unknown", native_type: "DEVICE_INTERNAL_PHASE", duration_s: 30 };
  const phases = [
    { ...effort1, order: 1 },
    unknown,
    { ...recovery1, order: 3 },
    { ...effort2, order: 4 },
    { ...recovery2, order: 5 },
    { ...effort3, order: 6 },
    { ...recovery3, order: 7 },
    { ...effort4, order: 8 },
    { ...recovery4, order: 9 },
  ];
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        phases,
        efforts: [phases[0], phases[3], phases[5], phases[7]],
        recoveries: [phases[2], phases[4], phases[6], phases[8]],
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  const effortRows = within(section).getAllByTestId("phase-effort-row");
  expect(within(effortRows[0]).queryByTestId("phase-recovery-row")).not.toBeInTheDocument();
  expect(section).toHaveTextContent("Other phase");
  expect(section).toHaveTextContent("Recovery 1");
  expect(section).toHaveTextContent("4:51/km");
  expect(section).not.toHaveTextContent("DEVICE_INTERNAL_PHASE");
});

test("missing recoveries are reported as zero without inferred associations", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  const efforts = phaseAnalysis.efforts.map((effort, index) => ({ ...effort, order: index + 1 }));
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        phases: efforts,
        efforts,
        recoveries: [],
        recovery_statistics: { count: 0 },
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  expect(screen.getByTestId("phase-summary")).toHaveTextContent("Recoveries: 0");
  expect(screen.queryByTestId("phase-recovery-row")).not.toBeInTheDocument();
});

test("missing effort heart-rate values are omitted rather than fabricated", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  const efforts = phaseAnalysis.efforts.map((effort) => ({ ...effort, average_hr: null, max_hr: null }));
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        efforts,
        phases: phaseAnalysis.phases.map((phase) => phase.phase_type === "effort"
          ? { ...phase, average_hr: null, max_hr: null }
          : phase),
        missing_data: ["heart_rate"],
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  within(section).getAllByTestId("phase-effort-row").forEach((row) => expect(row.firstElementChild).not.toHaveTextContent("bpm"));
  expect(section).not.toHaveTextContent("undefined");
});

test("missing effort paces and incomplete coverage do not produce technical panels", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  const efforts = phaseAnalysis.efforts.map((effort) => ({ ...effort, pace_sec_per_km: null }));
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        efforts,
        phases: phaseAnalysis.phases.map((phase) => phase.phase_type === "effort" ? { ...phase, pace_sec_per_km: null } : phase),
        effort_statistics: { ...phaseAnalysis.effort_statistics, average_pace_sec_per_km: null },
        effort_regularity: { ...phaseAnalysis.effort_regularity, available: false },
        missing_data: ["pace"],
        limitations: ["effort_paces_incomplete", "future_internal_code"],
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  expect(section).not.toHaveTextContent("Average effort pace");
  expect(section).toHaveTextContent("Effort 1");
  expect(section).not.toHaveTextContent("effort_paces_incomplete");
  expect(section).not.toHaveTextContent("future_internal_code");
});

test("available partial regularity shows one concise indicator and required caveat", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        effort_regularity: { ...phaseAnalysis.effort_regularity, partial_comparison: true, comparable_effort_count: 3 },
        limitations: ["efforts_partially_comparable"],
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const regularity = await screen.findByTestId("effort-regularity");
  expect(regularity).toHaveTextContent("7.7 s/km");
  expect(regularity).toHaveTextContent(translations.en.workoutDetailExtended.partialEffortComparison);
  expect(regularity).not.toHaveTextContent("+2.6 s/km");
  expect(regularity).not.toHaveTextContent("Average HR change across repetitions");
  expect(regularity).not.toHaveTextContent(/drift/i);
});

test("unavailable regularity does not display a performance judgment or regularity card", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  mockAxios({
    analysisPayload: {
      ...analysis,
      phase_analysis: {
        ...phaseAnalysis,
        effort_regularity: { ...phaseAnalysis.effort_regularity, available: false },
      },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  expect(screen.queryByTestId("effort-regularity")).not.toBeInTheDocument();
  expect(section).not.toHaveTextContent("perfect");
  expect(section).not.toHaveTextContent("goal achieved");
});

test("structured phases without kilometer splits remain distinct from split data", async () => {
  mockAxios({
    workoutPayload: { ...workout, km_splits: [] },
    analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.queryByText(translations.en.workoutDetailExtended.splitsUnavailable)).not.toBeInTheDocument();
});

test("kilometer splits are not added as a fourth detail layer", async () => {
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
});

test.each([
  ["FREE", false],
  ["active TRIAL", true],
  ["PREMIUM", true],
])("WorkoutDetail network and rendering access matches %s entitlement", async (_tier, allowed) => {
  setAnalysisAccess({ allowed });
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });

  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );

  await screen.findByTestId("workout-detail");
  if (allowed) {
    expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
    expect(axios.get.mock.calls.map(([url]) => url).filter((url) => url.includes("/coach/workout-analysis/"))).toHaveLength(1);
    expect(screen.queryByTestId("analysis-upgrade-notice")).not.toBeInTheDocument();
  } else {
    expect(await screen.findByTestId("analysis-upgrade-notice")).toBeVisible();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coach-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("takeaways-title")).not.toBeInTheDocument();
    expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
    expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-coach-btn")).not.toBeInTheDocument();
    expect(axios.get.mock.calls.map(([url]) => url).some((url) => url.includes("/coach/workout-analysis/"))).toBe(false);
    expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10 km");
    expect(screen.getByTestId("primary-metrics")).toHaveTextContent("1h");
    expect(screen.getByTestId("primary-metrics")).toHaveTextContent("6:00/km");
    expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  }
});

test.each([
  ["expired trial", { loading: false, allowed: false }],
  ["unknown rights", { loading: false, allowed: null }],
  ["rights loading", { loading: true, allowed: true }],
])("WorkoutDetail does not request analysis for %s", async (_state, access) => {
  setAnalysisAccess(access);
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("workout-detail");
  expect(axios.get.mock.calls.map(([url]) => url).some((url) => url.includes("/coach/workout-analysis/"))).toBe(false);
  expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
  expect(screen.queryByTestId("coach-summary")).not.toBeInTheDocument();
});

test("WorkoutDetail waits for entitlement resolution before requesting analysis", async () => {
  setAnalysisAccess({ loading: true, allowed: true });
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });
  const route = <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>;
  const view = renderWithProviders(route, "/workout/w1");
  await screen.findByTestId("workout-detail");
  expect(axios.get.mock.calls.map(([url]) => url).some((url) => url.includes("/coach/workout-analysis/"))).toBe(false);

  setAnalysisAccess({ allowed: true });
  view.rerender(
    <LanguageProvider>
      <UnitProvider>
        <MemoryRouter initialEntries={["/workout/w1"]}>{route}</MemoryRouter>
      </UnitProvider>
    </LanguageProvider>,
  );
  expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
  expect(axios.get.mock.calls.map(([url]) => url).filter((url) => url.includes("/coach/workout-analysis/"))).toHaveLength(1);
});

test("WorkoutDetail hides loaded analysis immediately on downgrade and reloads after reactivation", async () => {
  setAnalysisAccess({ allowed: true });
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });
  const route = <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>;
  const view = renderWithProviders(route, "/workout/w1");
  expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();

  setAnalysisAccess({ loading: true, allowed: true });
  view.rerender(<LanguageProvider><UnitProvider><MemoryRouter initialEntries={["/workout/w1"]}>{route}</MemoryRouter></UnitProvider></LanguageProvider>);
  expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
  expect(screen.queryByTestId("coach-summary")).not.toBeInTheDocument();

  setAnalysisAccess({ allowed: false });
  view.rerender(<LanguageProvider><UnitProvider><MemoryRouter initialEntries={["/workout/w1"]}>{route}</MemoryRouter></UnitProvider></LanguageProvider>);
  expect(screen.getByTestId("analysis-upgrade-notice")).toBeVisible();
  expect(axios.get.mock.calls.map(([url]) => url).filter((url) => url.includes("/coach/workout-analysis/"))).toHaveLength(1);

  setAnalysisAccess({ allowed: true });
  view.rerender(<LanguageProvider><UnitProvider><MemoryRouter initialEntries={["/workout/w1"]}>{route}</MemoryRouter></UnitProvider></LanguageProvider>);
  expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
  expect(axios.get.mock.calls.map(([url]) => url).filter((url) => url.includes("/coach/workout-analysis/"))).toHaveLength(2);
});

test.each(["fr", "en", "es"])("structured phase headings and labels are localized in %s", async (language) => {
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
    language,
  );
  const section = await screen.findByTestId("structured-phase-analysis");
  const labels = translations[language].workoutDetailExtended;
  expect(within(section).getByRole("heading", { level: 2 })).toHaveTextContent(labels.structuredPhases);
  expect(section).toHaveTextContent(labels.effortCount);
  expect(section).toHaveTextContent(labels.effortNumber.replace("{number}", "1"));
  expect(section).toHaveTextContent(labels.averageEffortPace);
});

test("structured phase cards keep a compact, wrapping layout at a 360px mobile viewport", async () => {
  const originalWidth = window.innerWidth;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const section = await screen.findByTestId("structured-phase-analysis");
  expect(screen.getByTestId("workout-detail")).toHaveClass("min-w-0");
  expect(section.querySelectorAll(".min-w-0").length).toBeGreaterThan(0);
  expect(section.querySelector("table")).toBeNull();
  expect(section.innerHTML).not.toContain("min-w-max");
  Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
});

test("WorkoutDetail shows one coherent error state for analysis failure", async () => {
  const delayed = new Promise((resolve) => setTimeout(() => resolve({ data: workout }), 0));
  axios.get.mockImplementation((url) => {
    if (url.includes("/workouts/w1")) return delayed;
    if (url.includes("/coach/workout-analysis/w1")) return Promise.reject(new Error("analysis failed"));
    return Promise.reject(new Error(`unexpected ${url}`));
  });

  renderWithProviders(
    <Routes>
      <Route path="/workout/:id" element={<WorkoutDetail />} />
    </Routes>,
    "/workout/w1",
  );

  expect(screen.getByText(/analyzing/i)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId("workout-detail")).toBeInTheDocument());
  expect(screen.queryByTestId("coach-summary")).not.toBeInTheDocument();
  expect(screen.getByText(translations.en.workoutDetailExtended.analysisLoadError)).toBeVisible();
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(axios.get).toHaveBeenCalledTimes(2);
});

test("WorkoutDetail keeps primary recorded facts visible while canonical analysis is pending", async () => {
  let resolveAnalysis;
  const delayedAnalysis = new Promise((resolve) => { resolveAnalysis = resolve; });
  mockAxios({ delayedAnalysis });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("workout-detail");
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.queryByTestId("coach-summary")).not.toBeInTheDocument();
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10 km");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10 km");
  resolveAnalysis({ data: analysis });
  await screen.findByTestId("coach-summary");
  expect(axios.get).toHaveBeenCalledTimes(2);
});

test.each(["fr", "en", "es"])("visible analysis headings use the same translated hierarchy in %s", async (language) => {
  mockAxios({ analysisPayload: { ...analysis, comparison: { ...analysis.comparison, similar: similarReference } } });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1", language,
  );
  await screen.findByTestId("coach-summary");
  const labels = translations[language].workoutDetailExtended;
  const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
  expect(headings).toContain(labels.sessionSummary);
  expect(headings).not.toContain(labels.historyComparison);
  expect(headings).not.toContain(labels.advancedDetails);
  expect(screen.queryByTestId("advanced-toggle")).not.toBeInTheDocument();
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("heart-response")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("--");
});

test("missing metrics and analysis evidence are omitted without repeated unavailable messages", async () => {
  mockAxios({
    workoutPayload: { ...workout, date: null, distance_km: null, duration_minutes: null, avg_pace_min_km: null, avg_heart_rate: null, max_heart_rate: null, km_splits: null },
    analysisPayload: { ...analysisMissingEvidence, summary: null, meaning: null, advice: null, evidence: null },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).toBeEmptyDOMElement();
  expect(screen.queryByTestId("heart-response")).not.toBeInTheDocument();
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-unavailable")).not.toBeInTheDocument();
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("not recorded");
});

test.each([null, {}, { available: "true", text: "Untrustworthy intensity" }, { available: false, text: "Untrustworthy intensity" }])(
  "intensity requires a strictly true available flag: %s", async (intensity) => {
    mockAxios({ analysisPayload: { ...analysis, signals: { intensity } } });
    renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
    await screen.findByTestId("coach-summary");
    expect(screen.queryByTestId("intensity-card-unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText(/Untrustworthy intensity/)).not.toBeInTheDocument();
  },
);

test("available intensity is displayed without reclassification", async () => {
  mockAxios({ analysisPayload: { ...analysis, signals: { intensity: { available: true, code: "low", text: "Engine supplied intensity" } } } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByText(/Engine supplied intensity/)).toBeVisible();
  expect(screen.getByTestId("available-intensity")).toBeVisible();
});

test.each(["fr", "en", "es"])("running retains valid average pace even when speed is recorded in %s", async (language) => {
  mockAxios({ workoutPayload: { ...workout, avg_speed_kmh: 10 } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1", language);
  await screen.findByTestId("coach-summary");
  const metrics = screen.getByTestId("primary-metrics");
  expect(metrics).toHaveTextContent(translations[language].workoutDetailExtended.averagePace);
  expect(metrics).toHaveTextContent("6:00/km");
  expect(metrics).not.toHaveTextContent("km/h");
});

test.each(["fr", "en", "es"])("cycling without recorded speed omits unavailable metrics in %s", async (language) => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle" },
    analysisPayload: { ...analysis, pacing: { available: false, average_speed_kmh: 25 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1", language);
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).not.toHaveTextContent(translations[language].workoutDetailExtended.speedUnavailable);
  expect(screen.getByTestId("primary-metrics")).not.toHaveTextContent("/km");
});

test.each(["fr", "en", "es"])("running with invalid pace reuses recorded speed before engine speed in %s", async (language) => {
  mockAxios({
    workoutPayload: { ...workout, avg_pace_min_km: 0, avg_speed_kmh: 10 },
    analysisPayload: { ...analysis, pacing: { ...analysis.pacing, average_speed_kmh: 11 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1", language);
  await screen.findByTestId("coach-summary");
  const metrics = screen.getByTestId("primary-metrics");
  expect(metrics).toHaveTextContent(translations[language].workoutDetailExtended.averageSpeed);
  expect(metrics).toHaveTextContent("10.0 km/h");
  expect(metrics).not.toHaveTextContent("/km");
});

test("running does not reuse an engine speed marked unavailable when summary pace is invalid", async () => {
  mockAxios({
    workoutPayload: { ...workout, avg_pace_min_km: null },
    analysisPayload: { ...analysis, pacing: { available: false, average_speed_kmh: 10 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).not.toHaveTextContent(translations.en.workoutDetailExtended.dataUnavailable);
  expect(screen.getByTestId("primary-metrics")).not.toHaveTextContent("km/h");
});

test.each(["fr", "en", "es"])("cycling uses recorded speed, never average min/km, in %s", async (language) => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle", avg_speed_kmh: 24.5 },
    analysisPayload: { ...analysis, pacing: { ...analysis.pacing, average_speed_kmh: 23 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1", language);
  await screen.findByTestId("coach-summary");
  const metrics = screen.getByTestId("primary-metrics");
  expect(metrics).toHaveTextContent(translations[language].workoutDetailExtended.averageSpeed);
  expect(metrics).toHaveTextContent("24.5 km/h");
  expect(metrics).not.toHaveTextContent("/km");
  expect(screen.queryByTestId("primary-metrics")).not.toHaveTextContent("/km");
});

test.each([null, 0, -3, NaN, Infinity, -Infinity, "25"])("cycling rejects unusable speeds %s without deriving speed", async (speed) => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle", avg_speed_kmh: speed },
    analysisPayload: { ...analysis, pacing: { available: true, average_pace_min_km: 6, average_speed_kmh: speed } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).not.toHaveTextContent(translations.en.workoutDetailExtended.speedUnavailable);
  expect(screen.getByTestId("primary-metrics")).not.toHaveTextContent("/km");
  expect(screen.queryByTestId("pacing-summary-card")).not.toBeInTheDocument();
});

test("cycling can reuse an available engine speed when the workout speed is missing", async () => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle", avg_speed_kmh: null },
    analysisPayload: { ...analysis, pacing: { ...analysis.pacing, average_speed_kmh: 25 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("25.0 km/h");
});

test("cycling does not reuse a speed marked unavailable by the engine", async () => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle" },
    analysisPayload: { ...analysis, pacing: { available: false, average_speed_kmh: 25 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).not.toHaveTextContent(translations.en.workoutDetailExtended.speedUnavailable);
});

test.each([null, 0, -2, NaN, Infinity, -Infinity, "6"])("invalid absolute paces %s are omitted and a valid engine speed is used", async (pace) => {
  mockAxios({
    workoutPayload: { ...workout, avg_pace_min_km: pace, km_splits: [{ km: 1, pace_min_km: pace }] },
    analysisPayload: {
      ...analysis,
      pacing: { available: true, average_pace_min_km: pace, average_speed_kmh: 10, fastest_split_min_km: pace, slowest_split_min_km: pace },
      comparison: { ...analysis.comparison, similar: { available: true, avg_pace_min_km: pace, pace_difference_min_km: null } },
    },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  const metrics = screen.getByTestId("primary-metrics");
  expect(metrics).toHaveTextContent(translations.en.workoutDetailExtended.averageSpeed);
  expect(metrics).toHaveTextContent("10.0 km/h");
  expect(metrics).not.toHaveTextContent("/km");
  expect(screen.queryByTestId("pacing-summary-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-pace")).not.toBeInTheDocument();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("NaN");
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("Infinity");
});

test.each([null, 0, -2, NaN, Infinity])("invalid engine pace %s does not replace a valid recorded pace", async (pace) => {
  mockAxios({
    workoutPayload: { ...workout, avg_pace_min_km: 6 },
    analysisPayload: { ...analysis, pacing: { available: true, average_pace_min_km: pace, average_speed_kmh: 0 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("pacing-summary-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("6:00/km");
});

test.each([null, {}, { z1: null, z2: NaN, z3: Infinity, z4: -1, z5: 101 }, { z1: 0, z2: 0 }, { unknown: 50 }])(
  "zones with no usable recorded distribution %s are hidden", async (zones) => {
    mockAxios({
      workoutPayload: { ...workout, avg_heart_rate: null, max_heart_rate: null },
      analysisPayload: { ...analysis, physiology: { available: true, zone_distribution: zones } },
    });
    renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
    await screen.findByTestId("coach-summary");
    expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("heart-response")).not.toBeInTheDocument();
  },
);

test("unavailable zones are hidden even if percentages are present", async () => {
  mockAxios({ analysisPayload: { ...analysis, physiology: { ...analysis.physiology, available: false } } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
});

test("heart-rate zones and provenance diagnostics stay off the workout screen", async () => {
  mockAxios({ analysisPayload: { ...analysis, physiology: { ...analysis.physiology, zone_distribution: { z1: 30, z2: NaN, z3: -2, z4: 101, z5: null } } } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
  expect(screen.queryByText(translations.en.workoutDetailExtended.zonesProvenance)).not.toBeInTheDocument();
});

test("kilometer split tables stay off the workout screen", async () => {
  const splits = Array.from({ length: 30 }, (_, i) => ({ km: i + 1, pace_min_km: 6, pace_str: "6:00" }));
  mockAxios({ workoutPayload: { ...workout, km_splits: [...splits, null, { km: 31, pace_min_km: null }] } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.queryByText(translations.en.workoutDetailExtended.invalidSplits)).not.toBeInTheDocument();
});

test.each([
  [404, "workout.notFound"],
  [503, "workoutDetailExtended.workoutLoadError"],
])("workout HTTP %s is distinguished from missing analysis", async (status, key) => {
  axios.get.mockImplementation((url) => url.includes("/workouts/")
    ? Promise.reject({ response: { status } })
    : new Promise(() => {}));
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  const [group, label] = key.split(".");
  expect(await screen.findByTestId("workout-not-found")).toHaveTextContent(translations.en[group][label]);
});

test("null analysis is not shown as a network failure", async () => {
  mockAxios({ analysisPayload: null });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("workout-detail");
  expect(screen.queryByText(translations.en.workoutDetailExtended.analysisUnavailable)).not.toBeInTheDocument();
  expect(screen.queryByText(translations.en.workoutDetailExtended.analysisLoadError)).not.toBeInTheDocument();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
});

test("late responses are ignored after the workout route changes even if transport ignores abort", async () => {
  let resolveWorkout;
  let resolveAnalysis;
  const delayedWorkout = new Promise((resolve) => { resolveWorkout = resolve; });
  const delayedAnalysis = new Promise((resolve) => { resolveAnalysis = resolve; });
  axios.get.mockImplementation((url) => {
    if (url.includes("/workouts/w1")) return delayedWorkout;
    if (url.includes("/coach/workout-analysis/w1")) return delayedAnalysis;
    if (url.includes("/workouts/w2")) return Promise.resolve({ data: { ...workout, id: "w2", name: "New activity" } });
    return Promise.resolve({ data: {
      ...analysis,
      meaning: { factual_observations: [
        { code: "fact.pace_change", text: "New measured observation", evidence: { pace_drop_min_km: 0.5 }, placement: "summary" },
      ] },
    } });
  });
  renderWithProviders(
    <><Link to="/workout/w2">Next activity</Link><Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes></>,
    "/workout/w1",
  );
  const firstSignals = axios.get.mock.calls.map(([, options]) => options.signal);
  fireEvent.click(screen.getByText("Next activity"));
  expect(firstSignals.every((signal) => signal.aborted)).toBe(true);
  await screen.findByText("New measured observation");
  resolveWorkout({ data: workout });
  resolveAnalysis({ data: analysis });
  await waitFor(() => expect(screen.getByTestId("workout-detail")).toHaveTextContent("New measured observation"));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("New activity");
});

test.each([
  [-0.012, "-0:01/km"],
  [0.2, "+0:12/km"],
  [0, "0:00/km"],
  [-0.001, "0:00/km"],
  [0.001, "0:00/km"],
  [-1.2, "-1:12/km"],
  [1.999, "+2:00/km"],
  [null, "--"],
  [undefined, "--"],
  [NaN, "--"],
])("formats minutes/km delta %s without inventing missing values", (difference, expected) => {
  expect(formatPaceDelta(difference)).toBe(expected);
});

test("absolute pace rounding carries seconds into minutes", () => {
  expect(formatPaceDisplay(5.999)).toBe("6:00/km");
  expect(formatPaceDisplay(null)).toBe("--");
});

const similarReference = {
  available: true,
  comparable: false,
  period_days: 180,
  sample_count: 5,
  avg_distance_km: 10.4,
  avg_pace_min_km: 6.012,
  avg_heart_rate: 148,
  pace_sample_count: 2,
  hr_sample_count: 3,
  pace_difference_min_km: -0.012,
  heart_rate_difference_bpm: 2,
  limitations: ["session_nature_unknown", "pace_sample_too_small"],
  reason_unavailable: null,
};

test.each(["fr", "en", "es"])("WorkoutDetail localizes primary facts and hides historical comparisons in %s", async (language) => {
  const payload = {
    ...analysis,
    meaning: { ...analysis.meaning, text: "Opaque meaning: 999 sessions, 999 days, 999 bpm. Never parse this text." },
    comparison: { ...analysis.comparison, similar: similarReference },
  };
  mockAxios({ analysisPayload: payload });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1", language,
  );
  await screen.findByTestId("coach-summary");
  const metrics = screen.getByTestId("primary-metrics");
  expect(metrics).toHaveTextContent(translations[language].workoutDetailExtended.averagePace);
  expect(metrics).toHaveTextContent(translations[language].workoutDetailExtended.averageHeartRate);
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.queryByText(/999 sessions|999 days|999 bpm/)).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
});

test("French 14-day baseline stays separate from the mandatory 180-day similar fixture", async () => {
  mockAxios({
    analysisPayload: {
      ...analysis,
      comparison: {
        ...analysis.comparison,
        baseline_period_days: 14,
        avg_pace_min_km: { ...analysis.comparison.avg_pace_min_km, baseline: 6.012, difference: -0.012 },
        similar: {
          ...similarReference,
          available: true,
          period_days: 180,
          sample_count: 5,
          avg_pace_min_km: 6.6,
          pace_difference_min_km: 0.2,
          avg_heart_rate: 137.2,
          heart_rate_difference_bpm: 3.8,
        },
      },
    },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1", "fr",
  );
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByText(/14 jours|180 jours|5 séances de référence|Allure moyenne: 6:36\/km/)).not.toBeInTheDocument();
  ["Duration", "HR", "Pace / Speed"].forEach((label) => {
    expect(screen.queryByText(label, { exact: true })).not.toBeInTheDocument();
  });
});

test("similar reference is independent of baseline availability and does not coerce missing deltas", async () => {
  mockAxios({
    analysisPayload: {
      ...analysisMissingEvidence,
      comparison: {
        ...analysisMissingEvidence.comparison,
        similar: { ...similarReference, pace_difference_min_km: null, heart_rate_difference_bpm: null },
      },
    },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
});

test.each([null, 5])("missing evidence counts are omitted, with total %s", async (sampleCount) => {
  mockAxios({
    analysisPayload: {
      ...analysis,
      comparison: {
        ...analysis.comparison,
        baseline_sample_count: null,
        similar: { ...similarReference, sample_count: sampleCount, pace_sample_count: null, hr_sample_count: undefined },
      },
    },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
});

test("similar heart-rate average and delta are rounded to whole bpm", async () => {
  mockAxios({
    analysisPayload: {
      ...analysis,
      comparison: {
        ...analysis.comparison,
        similar: { ...similarReference, avg_heart_rate: 136.8, heart_rate_difference_bpm: 3.8 },
      },
    },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("similar-heart-rate")).not.toBeInTheDocument();
  expect(screen.queryByText("136.8")).not.toBeInTheDocument();
  expect(screen.queryByText("3.8")).not.toBeInTheDocument();
});

test.each([
  [9.68, "9.68 km"],
  [9.6800000004, "9.68 km"],
  [10, "10 km"],
  [1.2, "1.2 km"],
  [1.3900000001, "1.39 km"],
  [2.555, "2.56 km"],
  [0, "0 km"],
  [-0, "0 km"],
  [-0.001, "0 km"],
  [null, "--"],
  [undefined, "--"],
  [NaN, "--"],
  [Infinity, "--"],
  [-Infinity, "--"],
])("formats absolute distance %s as %s", (value, expected) => {
  expect(formatDistance(value)).toBe(expected);
});

test.each([
  [2.55, "+2.55 km"],
  [1, "+1 km"],
  [1.3900000001, "+1.39 km"],
  [2.5500000003, "+2.55 km"],
  [2.555, "+2.56 km"],
  [-1.39, "-1.39 km"],
  [0, "0 km"],
  [-0, "0 km"],
  [-0.001, "0 km"],
  [0.001, "0 km"],
  [null, "--"],
  [undefined, "--"],
  [NaN, "--"],
  [Infinity, "--"],
  [-Infinity, "--"],
])("formats distance delta %s as %s without mutating it", (difference, expected) => {
  const metric = Object.freeze({ difference });
  expect(formatSignedDistance(metric)).toBe(expected);
  expect(metric.difference).toBe(difference);
});

test.each([null, undefined])("missing distance metric %s stays unavailable", (metric) => {
  expect(formatSignedDistance(metric)).toBe("--");
});

test.each([
  [9.6800000004, 2.5500000003, "9.68 km", "+2.55 km"],
  [null, null, "--", "--"],
  [NaN, Infinity, "--", "--"],
  [0, -0.001, "0 km", "0 km"],
])("WorkoutDetail renders recorded distance without displaying historical deltas (%s, %s)", async (
  absolute, delta, absoluteText, deltaText,
) => {
  const workoutPayload = Object.freeze({ ...workout, distance_km: absolute });
  const metric = Object.freeze({ ...analysis.comparison.distance_km, difference: delta });
  const similar = Object.freeze({ ...similarReference, avg_distance_km: absolute });
  mockAxios({
    workoutPayload,
    analysisPayload: {
      ...analysis,
      comparison: { ...analysis.comparison, distance_km: metric, similar },
    },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("coach-summary");
  const metrics = screen.getByTestId("primary-metrics");
  if (Number.isFinite(absolute) && absolute > 0) expect(metrics).toHaveTextContent(absoluteText);
  else expect(metrics).not.toHaveTextContent("Distance");
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-detail").textContent).not.toMatch(/[+-]?\d+\.\d{3,}\s*km/);
  expect(workoutPayload.distance_km).toBe(absolute);
  expect(similar.avg_distance_km).toBe(absolute);
  expect(metric.difference).toBe(delta);
});

test.each([
  ["fr", 0, "0 séances de référence"],
  ["fr", 1, "1 séance de référence"],
  ["fr", 2, "2 séances de référence"],
  ["en", 0, "0 reference sessions"],
  ["en", 1, "1 reference session"],
  ["en", 2, "2 reference sessions"],
  ["es", 0, "0 sesiones de referencia"],
  ["es", 1, "1 sesión de referencia"],
  ["es", 2, "2 sesiones de referencia"],
])("historical reference counts are not rendered in %s for %s", async (language, count, expected) => {
  mockAxios({
    analysisPayload: {
      ...analysis,
      comparison: {
        ...analysis.comparison,
        baseline_sample_count: count,
        similar: { ...similarReference, sample_count: count },
      },
    },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1", language,
  );
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByText(expected)).not.toBeInTheDocument();
});

test.each([
  [42.678, 150.789, 2.789, -3.789, "43m", "151 bpm", "+3 min", "-4 bpm"],
  [59.999, 0, 0, 0, "1h", "0 bpm", "0 min", "0 bpm"],
  [119.999, 136.8, -0.1, 0.1, "2h", "137 bpm", "0 min", "0 bpm"],
  [0, null, null, null, "0m", null, "--", "--"],
  [null, NaN, NaN, Infinity, "--", "--", "--", "--"],
])("WorkoutDetail shows supported current duration and average HR only for %s and %s", async (
  minutes, heartRate, minuteDelta, hrDelta, durationText, hrText, minuteDeltaText, hrDeltaText,
) => {
  const workoutPayload = {
    ...workout,
    avg_heart_rate: heartRate,
    duration_minutes: minutes,
    km_splits: workout.km_splits.map((split) => ({ ...split, avg_hr: heartRate })),
  };
  const analysisPayload = {
    ...analysis,
    physiology: { ...analysis.physiology, avg_hr: heartRate },
    comparison: {
      ...analysis.comparison,
      duration_minutes: { difference: minuteDelta },
      avg_heart_rate: { difference: hrDelta },
    },
  };
  mockAxios({ workoutPayload, analysisPayload });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("coach-summary");
  const metrics = screen.getByTestId("primary-metrics");
  if (Number.isFinite(minutes) && minutes > 0) expect(metrics).toHaveTextContent(durationText);
  else expect(metrics).not.toHaveTextContent("Duration");
  if (Number.isFinite(heartRate) && heartRate > 0) {
    expect(metrics).toHaveTextContent(hrText);
  } else {
    expect(metrics).not.toHaveTextContent("bpm");
  }
  expect(screen.queryByTestId("heart-response")).not.toBeInTheDocument();
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("NaN");
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("Infinity");
  expect(workoutPayload.duration_minutes).toBe(minutes);
  expect(analysisPayload.physiology.avg_hr).toBe(heartRate);
  expect(analysisPayload.comparison.duration_minutes.difference).toBe(minuteDelta);
  expect(analysisPayload.comparison.avg_heart_rate.difference).toBe(hrDelta);
});

test("unavailable similar reference is not surfaced as a comparison panel", async () => {
  mockAxios({
    analysisPayload: {
      ...analysis,
      comparison: {
        ...analysis.comparison,
        similar: {
          available: false, comparable: false, sample_count: 0, period_days: 180,
          avg_pace_min_km: null, avg_heart_rate: null,
          limitations: ["no_comparable_reference"],
          reason_unavailable: "No earlier session of comparable distance was found.",
        },
      },
    },
  });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByText("No earlier session of comparable distance was found.")).not.toBeInTheDocument();
});

test.each(["fr", "en", "es"])("WorkoutDetail business keys are explicitly translated in %s", (language) => {
  const keys = [
    "pace", "speed", "distance", "duration", "heartRate", "recentComparison", "similarComparison",
    "sampleCount", "paceSampleCount", "hrSampleCount", "averageDistance", "averagePace",
    "averageHeartRate", "difference", "descriptiveComparison", "similarUnavailable",
    "analysisDetails", "analysisAdvice", "analysisUnavailable", "evidence", "version",
    "hrZonesEvidence", "splitsEvidence", "baselineEvidence", "cadenceEvidence", "elevationEvidence",
    "yes", "no", "limitations", "unknownSessionNature", "smallSample", "smallPaceSample", "smallHrSample",
    "intensityUnavailable", "analysisPremiumRequired", "unlockAnalysis",
    "recordedSplits", "kilometerNumber",
    "interpretation",
  ];
  keys.forEach((key) => expect(translations[language].workoutDetailExtended[key]).toEqual(expect.any(String)));
});

test("French workout copy stays concise and factual", () => {
  expect(translations.fr.workoutDetailExtended).toMatchObject({
    similarComparison: "Sorties similaires · {days} jours",
    heartRate: "FC",
    descriptiveComparison: "Écart descriptif, pas une conclusion de performance.",
    interpretation: "Interprétation factuelle",
    limitations: "Limites / points de vigilance",
  });
});

test("DetailedAnalysis uses the canonical V2 endpoint", async () => {
  mockAxios();

  renderWithProviders(
    <Routes>
      <Route path="/workout/:id/analysis" element={<DetailedAnalysis />} />
    </Routes>,
    "/workout/w1/analysis",
  );

  const metrics = await screen.findByTestId("primary-metrics");
  expect(metrics).toHaveTextContent("10.0 km");
  expect(metrics).toHaveTextContent("1h 0m");
  expect(screen.queryByTestId("header-context")).not.toBeInTheDocument();
  const urls = axios.get.mock.calls.map(([url]) => url);
  expect(urls).toContainEqual(expect.stringContaining("/coach/workout-analysis/w1"));
  expect(urls).toContainEqual(expect.stringContaining("/workouts/w1"));
  expect(await screen.findByTestId("kilometer-splits")).toBeInTheDocument();
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10.0 km");
  expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
});

test("SessionDetail uses the canonical V2 endpoint", async () => {
  mockAxios();

  renderWithProviders(
    <Routes>
      <Route path="/sessions/:id" element={<SessionDetail />} />
    </Routes>,
    "/sessions/w1",
  );

  expect(await screen.findByTestId("session-detail-page")).toBeInTheDocument();
  const urls = axios.get.mock.calls.map(([url]) => url);
  expect(urls).toContainEqual(expect.stringContaining("/coach/workout-analysis/w1"));
  expect(urls.some((url) => url.includes("/coach/detailed-analysis/"))).toBe(false);
});

test("WorkoutDetail Ask Coach runs analysis in the real Coach page", async () => {
  axios.get.mockImplementation((url) => {
    if (url.includes("/coach/history")) return Promise.resolve({ data: [] });
    if (url.includes("/workouts/w1")) return Promise.resolve({ data: workout });
    if (url.includes("/coach/workout-analysis/w1")) return Promise.resolve({ data: analysis });
    if (url.endsWith("/workouts")) return Promise.resolve({ data: [workout] });
    return Promise.reject(new Error(`unexpected ${url}`));
  });

  axios.post.mockResolvedValue({ data: { response: "Coach analyzed the selected workout." } });
  renderWithProviders(
    <Routes>
      <Route path="/sessions" element={<Sessions />} />
      <Route path="/workout/:id" element={<WorkoutDetail />} />
      <Route path="/coach" element={<Coach />} />
    </Routes>,
    "/sessions",
  );
  const sessionLink = await screen.findByRole("link", { name: /150 bpm/ });
  expect(sessionLink).toHaveAttribute("href", "/workout/w1");
  fireEvent.click(sessionLink);
  await screen.findByTestId("coach-summary");
  fireEvent.click(screen.getByTestId("ask-coach-btn"));
  expect(await screen.findByText("Coach analyzed the selected workout.")).toBeInTheDocument();
  expect(axios.post).toHaveBeenCalledWith(
    expect.stringContaining("/coach/analyze"),
    {
      message: expect.stringContaining("Morning Run"),
      workout_id: "w1",
      language: "en",
    },
  );
});

const editorialPages = [
    ["WorkoutDetail", "/workout/w1", "/workout/:id", WorkoutDetail, "workout-detail"],
    ["DetailedAnalysis", "/workout/w1/analysis", "/workout/:id/analysis", DetailedAnalysis, "detailed-analysis"],
    ["SessionDetail", "/sessions/w1", "/sessions/:id", SessionDetail, "session-detail-page"],
  ];

const factualObservation = (code, text, evidence = { sample_count: 4 }, placement = "summary") => ({
  code, text, evidence, placement,
});

test.each([true, "94", null, undefined, NaN, Infinity, -Infinity, {}, []])(
  "rejects nonnumeric or nonfinite factual evidence %p", (value) => {
    expect(getAnalysisObservations({ meaning: { factual_observations: [
      factualObservation("fact.bad", "Unreliable observation.", { value }),
    ] } })).toEqual([]);
  },
);

test("absent facts never expose mixed legacy observations even with trusted intensity", () => {
  expect(getAnalysisObservations({
    meaning: { code: "meaning.with_hr_high", observations: ["Mixed legacy conclusion."] },
    signals: { intensity: { available: true, code: "high" } },
  })).toEqual([]);
});

test.each(["fact.pacing_consistency", "fact.consistency", "fact.hr_drift_measured", "fact.hr_drift"])(
  "does not display unsupported score or drift fact %s", (code) => {
    expect(getAnalysisObservations({ meaning: { factual_observations: [
      factualObservation(code, "Unsupported score or drift.", { value: 90 }),
    ] } })).toEqual([]);
  },
);

test("ungrounded legacy advice is not a factual observation", () => {
  expect(getDistinctCoachObservation(analysis)).toBeNull();
});

test.each([
  ["advice.high_intensity_observation", "high", true],
  ["advice.low_intensity_observation", "low", true],
  ["advice.high_intensity_observation", "high", false],
])("retains only intensity advice backed by matching zone classification: %s", (code, intensityCode, available) => {
  const adviceText = "Zone-supported intensity observation.";
  expect(getDistinctCoachObservation({
    ...analysis,
    advice: { available: true, code, text: adviceText },
    signals: { ...analysis.signals, intensity: { available, code: intensityCode } },
  })).toBe(available ? adviceText : null);
});

test.each([
  ["advice.even_pacing", { pace_drop_min_km: 0.5 }, "fact.pace_change"],
  ["advice.negative_split_confirmed", { negative_split: true }, "fact.negative_split"],
])("keeps supported legacy pacing advice only when no equivalent fact is visible: %s",
  (code, metric, factCode) => {
    const adviceText = "Supported legacy pacing observation.";
    const base = {
      ...analysis,
      advice: { available: true, code, text: adviceText },
      pacing: { ...analysis.pacing, ...metric },
      signals: { ...analysis.signals, session_structure: { available: true, code: "continuous" } },
      meaning: { factual_observations: [] },
    };
    expect(getDistinctCoachObservation(base)).toBe(adviceText);
    expect(getDistinctCoachObservation({
      ...base,
      meaning: { factual_observations: [factualObservation(factCode, "Equivalent measured fact.")] },
    })).toBeNull();
  });

test.each([
  ["advice.even_pacing", 0.4, "continuous"],
  ["advice.even_pacing", 0.3999, "continuous"],
  ["advice.negative_split_confirmed", null, "intervals"],
  ["advice.even_pacing", 0.5, undefined],
])("rejects legacy global pacing advice for rounded subthreshold or non-continuous data: %s %s %s",
  (code, paceChange, structure) => {
    expect(getDistinctCoachObservation({
      ...analysis,
      advice: { available: true, code, text: "Unsupported global pacing advice." },
      pacing: { ...analysis.pacing, pace_drop_min_km: paceChange, negative_split: code === "advice.negative_split_confirmed" },
      signals: {
        ...analysis.signals,
        session_structure: structure ? { available: true, code: structure } : { available: false, code: null },
      },
    })).toBeNull();
  });

test.each(["advice.maintain_consistency", "advice.monitor_hr_drift", "advice.recover_after_long"])(
  "does not restore score, unverified drift, or recommendation advice: %s", (code) => {
    expect(getDistinctCoachObservation({
      ...analysis,
      advice: { available: true, code, text: "Unsupported observation." },
    })).toBeNull();
  },
);

test.each([
  { code: "   " },
  { text: " \n " },
  { placement: "invalid" },
  { placement: undefined },
  { evidence: {} },
  { evidence: [] },
  { evidence: { valid: 94, invalid: null } },
])("rejects malformed fact fields %p", (fields) => {
  expect(getAnalysisObservations({ meaning: { factual_observations: [
    { ...factualObservation("fact.pacing_consistency", "Measured consistency."), ...fields },
  ] } })).toEqual([]);
});

test("valid facts deduplicate normalized codes and texts without losing zero or signed evidence", () => {
  expect(getAnalysisObservations({ meaning: { factual_observations: [
    factualObservation(" fact.zero ", " Zero drift. ", { drift: 0 }),
    factualObservation("fact.zero", "Duplicate code.", { drift: 0 }),
    factualObservation("fact.other", "Zero drift.", { drift: 0 }),
    factualObservation("fact.change", "Faster measured pace.", { change: -0.5 }),
    factualObservation("fact.bad", "Invalid.", { value: true }),
  ] } })).toEqual(["Zero drift.", "Faster measured pace."]);
});

test.each([[[]], [[factualObservation("fact.pacing_consistency", "Malformed.", { score: null })]]])(
  "legacy advice stays suppressed independently of raw fact codes: %p", (facts) => {
    expect(getDistinctCoachObservation({
      ...analysis, meaning: { factual_observations: facts },
    })).toBeNull();
  },
);

test("structured facts override mixed legacy text without requiring intensity", () => {
  const fact = factualObservation("fact.pace_change", "Measured pace change.", { pace_drop_min_km: 0.5 });
  const payload = {
   ...analysis,
   meaning: { ...analysis.meaning, factual_observations: [fact, fact, { ...fact, code: "duplicate" }] },
  };
  expect(getAnalysisTakeaway(payload)).toBe(fact.text);
  expect(getAnalysisObservations(payload)).toEqual([fact.text]);
  expect(getAnalysisObservations({ ...payload, meaning: {
   ...payload.meaning, factual_observations: [],
  } })).toEqual([]);
});

test.each([null, {}, "invalid", [null, {}, { code: "fact.bad", text: "No proof." }]])(
  "invalid factual contract %p never falls back to mixed legacy meaning", (facts) => {
   expect(getAnalysisObservations({
     ...analysis,
     meaning: { ...analysis.meaning, factual_observations: facts },
   })).toEqual([]);
  },
);

test.each([
  ["advice.even_pacing", "fact.pace_change"],
  ["advice.negative_split_confirmed", "fact.negative_split"],
  ["advice.maintain_consistency", "fact.pacing_consistency"],
  ["advice.monitor_hr_drift", "fact.hr_drift_measured"],
])("does not repeat %s as coach advice when its measured fact is displayed", (adviceCode, factCode) => {
  expect(getDistinctCoachObservation({
    ...analysis,
    advice: { available: true, code: adviceCode, text: "Same measurement, different wording." },
    meaning: { factual_observations: [factualObservation(factCode, "Measured fact.")] },
  })).toBeNull();
});

describe.each(editorialPages)("%s factual observation contract", (_name, route, path, Page, testId) => {
  test("shows supported legacy pacing advice when its factual contract is absent", async () => {
    const adviceText = "The recorded pace change is a useful comparison point.";
    mockAxios({ analysisPayload: {
      ...analysis,
      advice: { available: true, code: "advice.even_pacing", text: adviceText },
      pacing: { ...analysis.pacing, pace_drop_min_km: 0.5 },
      signals: { ...analysis.signals, session_structure: { available: true, code: "continuous" } },
      meaning: { factual_observations: [] },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("advice-text")).toHaveTextContent(adviceText);
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  });

  test("no-fact recovery advice never replaces missing observations or revives legacy mixed text", async () => {
    mockAxios({ analysisPayload: {
      ...analysis,
      meaning: {
        code: "meaning.with_hr_high",
        text: "Legacy mixed meaning.",
        observations: ["Legacy mixed observation."],
        caveats: ["Legacy mixed caveat."],
      },
      advice: { available: true, code: "advice.recover_after_long", text: "Unsupported recovery advice." },
      signals: { ...analysis.signals, intensity: { available: true, code: "high", text: "Supported intensity" } },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("analysis-fallback")).toBeVisible();
    expect(screen.getByTestId(testId)).not.toHaveTextContent(/Legacy mixed|Unsupported recovery advice/);
    expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  });

  test.each(["fr", "en", "es"].flatMap((language) => [
    [language, "absent", undefined],
    [language, "empty", []],
    [language, "invalid", [factualObservation("fact.bad", "Invalid fact must stay hidden.", { value: "94" })]],
  ]))("uses an honest localized fallback in %s for %s facts, never mixed legacy text", async (language, _state, facts) => {
    mockAxios({ analysisPayload: {
      ...analysis,
      meaning: {
        code: "meaning.with_hr_high",
        text: "Mixed legacy meaning.",
        observations: ["Mixed legacy observation."],
        caveats: ["Mixed legacy caveat."],
        ...(facts === undefined ? {} : { factual_observations: facts }),
      },
      signals: { ...analysis.signals, intensity: { available: true, code: "high", text: "Supported intensity" } },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
    const fallback = await screen.findByTestId("analysis-fallback");
    expect(fallback).toHaveTextContent(translations[language].workoutDetailExtended.noReliableObservations);
    expect(fallback).toBeVisible();
    expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
    expect(screen.getByTestId(testId)).not.toHaveTextContent(/Mixed legacy|Invalid fact must stay hidden/);
    expect(screen.queryByText(analysis.advice.text)).not.toBeInTheDocument();
    expect(screen.getAllByTestId("analysis-fallback")).toHaveLength(1);
    expect(screen.getByTestId(testId)).toHaveClass("min-w-0", "break-words");
  });

  test.each([true, null, NaN, Infinity, -Infinity, "94"])("rejects invalid numeric evidence %p on the page", async (value) => {
    mockAxios({ analysisPayload: { ...analysis, meaning: { factual_observations: [
      factualObservation("fact.bad", "Unreliable fact.", { value }),
    ] } } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("analysis-fallback")).toBeVisible();
    expect(screen.queryByText("Unreliable fact.")).not.toBeInTheDocument();
  });

  test("phase-only observations keep actual regularity and rows without a false fallback or duplicate", async () => {
    mockAxios({ analysisPayload: {
      ...analysis,
      phase_analysis: makeStructuredPhaseAnalysis(),
      meaning: { factual_observations: [
        factualObservation("fact.effort_dispersion", "Already represented in phase regularity.", { dispersion: 7.7 }, "phases"),
      ] },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("effort-regularity")).toHaveTextContent("7.7 s/km");
    expect(screen.getAllByTestId("phase-effort-row")).toHaveLength(4);
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
    expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
    expect(screen.queryByText("Already represented in phase regularity.")).not.toBeInTheDocument();
  });

  test.each([
    [[]],
    [[null, "invalid"]],
    [[{}]],
    [[{ phase_type: "unknown" }]],
    [[{ phase_type: "effort", duration_s: null, distance_m: null, pace_sec_per_km: "94", average_hr: true }]],
    [[{ phase_type: "effort", distance_m: 800 }]],
    [[{ phase_type: "effort", duration_s: -1, distance_m: NaN, pace_sec_per_km: Infinity, average_hr: -Infinity }]],
  ])("phase rows without useful measured data %p do not hide the fallback", async (phases) => {
    mockAxios({ analysisPayload: { ...analysis,
      phase_analysis: { available: true, phases, effort_regularity: { available: true } },
      meaning: { factual_observations: [
        factualObservation("fact.effort_dispersion", "Invisible phase fact.", { dispersion: 0 }, "phases"),
      ] },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("analysis-fallback")).toBeVisible();
    expect(screen.queryByTestId("effort-regularity")).not.toBeInTheDocument();
  });

  test.each([
    { duration_s: 240 },
    { duration_s: 0 },
    { pace_sec_per_km: 300 },
    { average_hr: 151 },
  ])("actually rendered finite phase measurement %p prevents a false fallback", async (metric) => {
    mockAxios({ analysisPayload: { ...analysis,
      meaning: { factual_observations: [] },
      phase_analysis: { available: true, phases: [{ phase_type: "effort", ...metric }] },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  });

  test("actually rendered average effort pace prevents a false fallback", async () => {
    mockAxios({ analysisPayload: { ...analysis,
      meaning: { factual_observations: [] },
      phase_analysis: {
        available: true, phases: [{ phase_type: "effort" }],
        effort_statistics: { average_pace_sec_per_km: 300 },
      },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("phase-summary")).toHaveTextContent("5:00/km");
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  });

  test.each(["fr", "en", "es"].flatMap((language) => [
    [language, { pace_sec_per_km: 300 }, "5:00/km"],
    [language, { average_hr: 151 }, "151 bpm"],
    [language, { duration_s: 0, average_hr: 151 }, "151 bpm"],
    [language, { pace_sec_per_km: 300, average_hr: 151 }, "5:00/km · 151 bpm"],
  ]))("recovery measurements without duration remain accessible in %s: %p", async (language, metric, text) => {
    mockAxios({ analysisPayload: { ...analysis,
      meaning: { factual_observations: [] },
      phase_analysis: {
        available: true,
        phases: [{ phase_type: "recovery", ...metric }],
      },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
    const recovery = await screen.findByTestId("phase-recovery-row");
    fireEvent.click(within(recovery).getByText(translations[language].workoutDetailExtended.phaseRecoveryNumber.replace("{number}", "1"), { exact: false }));
    expect(within(recovery).getByText(text)).toBeVisible();
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  });

  test("actually rendered zero phase dispersion is an observation, not missing evidence", async () => {
    mockAxios({ analysisPayload: { ...analysis,
      meaning: { factual_observations: [] },
      phase_analysis: {
        available: true, phases: [{ phase_type: "effort" }],
        effort_regularity: { available: true, pace_dispersion_sec_per_km: 0 },
      },
    } });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("effort-regularity")).toHaveTextContent("0 s/km");
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  });

  test("pace-only evidence needs no HR or intensity and deduplicates valid observations", async () => {
    const fact = factualObservation("fact.pace_change", "Measured pace change.", { pace_drop_min_km: 0.5 });
    mockAxios({
      workoutPayload: { ...workout, avg_heart_rate: null, max_heart_rate: null },
      analysisPayload: { ...analysisMissingEvidence, meaning: { factual_observations: [
        fact, { ...fact, code: " fact.pace_change ", text: "Duplicate measurement." }, { ...fact, code: "another" },
      ] } },
    });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    expect(await screen.findByTestId("meaning-text")).toHaveTextContent(fact.text);
    expect(screen.getAllByText(fact.text)).toHaveLength(1);
    expect(screen.queryByText("Duplicate measurement.")).not.toBeInTheDocument();
    expect(screen.getByTestId(testId)).not.toHaveTextContent(/bpm|High intensity/);
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
  });

  test.each([["FREE", false], ["active TRIAL", true], ["PREMIUM", true]])(
    "%s uses the feature entitlement for successful empty analysis", async (_tier, allowed) => {
      setAnalysisAccess({ allowed });
      mockAxios();
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      if (allowed) {
        expect(await screen.findByTestId("analysis-fallback")).toBeVisible();
        expect(axios.get.mock.calls.filter(([url]) => url.includes("/coach/workout-analysis/"))).toHaveLength(1);
      } else {
        expect(await screen.findByTestId("analysis-upgrade-notice")).toBeVisible();
        expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
        expect(axios.get.mock.calls.some(([url]) => url.includes("/coach/workout-analysis/"))).toBe(false);
      }
    },
  );

  test("unresolved entitlement never exposes the empty-analysis fallback", async () => {
    setAnalysisAccess({ loading: true, allowed: true });
    mockAxios();
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    await waitFor(() => expect(useSubscription).toHaveBeenCalled());
    expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
    expect(axios.get.mock.calls.some(([url]) => url.includes("/coach/workout-analysis/"))).toBe(false);
  });

  test.each(["fr", "en", "es"])("shows backend-localized pace and descriptive HR facts without zones in %s", async (language) => {
   const texts = {
     fr: ["Tu as accéléré de 30 secondes par kilomètre.", "FC observée : 151 à 159 bpm."],
     en: ["You ran 30 seconds per kilometre faster.", "Observed HR: 151 to 159 bpm."],
     es: ["Aceleraste 30 segundos por kilómetro.", "FC observada: 151 a 159 bpm."],
   }[language];
   mockAxios({ analysisPayload: {
     ...analysis,
     meaning: {
       ...analysis.meaning,
       caveats: ["Intensity cannot be classified."],
       factual_observations: [
         factualObservation("fact.pace_change", texts[0], { pace_drop_min_km: -0.5 }),
         factualObservation("fact.effort_hr", texts[1], { first_hr: 151, last_hr: 159 }),
       ],
     },
     advice: { available: false },
   } });
   renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
   const meaning = await screen.findByTestId("meaning-text");
   texts.forEach((text) => expect(within(meaning).getByText(text)).toBeVisible());
   expect(screen.getByTestId(testId)).not.toHaveTextContent(analysis.meaning.text);
   expect(screen.queryByText("Intensity cannot be classified.")).not.toBeInTheDocument();
   expect(screen.queryByTestId("available-intensity")).not.toBeInTheDocument();
   expect(screen.queryByTestId("session-classification")).not.toBeInTheDocument();
  });

  test("retains phase rows but does not duplicate phase regularity in the takeaway", async () => {
   mockAxios({ analysisPayload: {
     ...analysis,
     phase_analysis: makeStructuredPhaseAnalysis(),
     meaning: { ...analysis.meaning, factual_observations: [
       factualObservation("fact.effort_dispersion", "Dispersion already shown in phases.", { dispersion: 7.7 }, "phases"),
       factualObservation("fact.effort_hr", "Measured HR increases from 151 to 159 bpm."),
     ] },
   } });
   renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
   expect(await screen.findByTestId("effort-regularity")).toBeVisible();
   expect(screen.getByTestId("meaning-text")).toHaveTextContent("Measured HR increases from 151 to 159 bpm.");
   expect(screen.queryByText("Dispersion already shown in phases.")).not.toBeInTheDocument();
  });

  test("renders a comparable historical fact without restoring historical panels", async () => {
   mockAxios({ analysisPayload: {
     ...analysis,
     meaning: { ...analysis.meaning, factual_observations: [
       factualObservation("fact.similar_pace", "Measured pace gap against 3 comparable sessions: -0:06/km.", { pace_sample_count: 3 }),
     ] },
   } });
   renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
   expect(await screen.findByTestId("meaning-text")).toHaveTextContent("3 comparable sessions");
   expect(screen.queryByTestId("history-section")).not.toBeInTheDocument();
  });

  test("no factual evidence and no splits produces no artificial conclusion", async () => {
   mockAxios({
     workoutPayload: { ...workout, km_splits: [] },
     analysisPayload: {
       ...analysisMissingEvidence,
       meaning: { ...analysis.meaning, factual_observations: [] },
       advice: { available: false },
     },
   });
   renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
   await screen.findByTestId("ask-coach-btn");
   expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
   expect(screen.queryByTestId("session-classification")).not.toBeInTheDocument();
   expect(screen.queryByTestId("splits-section")).not.toBeInTheDocument();
   expect(screen.getByTestId("analysis-fallback")).toBeVisible();
  });

  test("FREE cannot request or expose structured factual observations", async () => {
   setAnalysisAccess({ allowed: false });
   mockAxios({ analysisPayload: {
     ...analysis,
     meaning: { factual_observations: [factualObservation("fact.pace_change", "Premium factual observation.", { pace_drop_min_km: 0.5 })] },
   } });
   renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
   await screen.findByTestId("analysis-upgrade-notice");
   expect(screen.queryByText("Premium factual observation.")).not.toBeInTheDocument();
   expect(axios.get.mock.calls.some(([url]) => url.includes("/coach/workout-analysis/"))).toBe(false);
  });
});

  test.each(editorialPages)("FREE cannot load V2 through %s", async (_name, route, path, Page, testId) => {
    setAnalysisAccess({ allowed: false });
    mockAxios();
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);

    if (_name === "DetailedAnalysis") {
      expect(await screen.findByTestId("analysis-access-denied")).toBeVisible();
    } else {
      expect(await screen.findByTestId(testId)).toBeVisible();
    }
    expect(axios.get.mock.calls.map(([url]) => url).some((url) => url.includes("/coach/workout-analysis/"))).toBe(false);
    expect(screen.queryByText(analysis.summary.text)).not.toBeInTheDocument();
    expect(screen.queryByText(analysis.meaning.text)).not.toBeInTheDocument();
    expect(screen.queryByText(analysis.advice.text)).not.toBeInTheDocument();
    expect(screen.getByTestId("analysis-upgrade-notice")).toBeVisible();
    if (_name === "SessionDetail") {
      const facts = screen.getByTestId("session-detail-page");
      expect(facts).toHaveTextContent("Morning Run");
      expect(facts.textContent).toMatch(/10(?:\.0)? km|6\.21 mi/);
      expect(facts).toHaveTextContent("1h");
    }
  });

  test.each(["fr", "en", "es"])("FREE analysis upgrade link is localized in %s", async (language) => {
    setAnalysisAccess({ allowed: false });
    mockAxios();
    renderWithProviders(
      <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
      "/workout/w1",
      language,
    );
    const notice = await screen.findByTestId("analysis-upgrade-notice");
    expect(notice).toHaveTextContent(translations[language].workoutDetailExtended.analysisPremiumRequired);
    expect(within(notice).getByRole("link", { name: translations[language].workoutDetailExtended.unlockAnalysis })).toHaveAttribute("href", "/subscription");
    expect(axios.get.mock.calls.map(([url]) => url).some((url) => url.includes("/coach/workout-analysis/"))).toBe(false);
  });

  test.each(editorialPages)("unavailable intensity and history stay hidden through %s", async (_name, route, path, Page, testId) => {
    mockAxios({
      analysisPayload: {
        ...analysis,
        comparison: { ...analysis.comparison, similar: { ...similarReference, comparable: true } },
        signals: { ...analysis.signals, intensity: { ...analysis.signals.intensity, available: false } },
      },
    });
    renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
    const page = await screen.findByTestId(testId);
    expect(page).not.toHaveTextContent(analysis.signals.intensity.reason_unavailable);
    expect(page).not.toHaveTextContent("14 days");
    expect(page).not.toHaveTextContent("180 days");
    expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("comparison-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("available-intensity")).not.toBeInTheDocument();
    expect(page).not.toHaveTextContent(/High intensity|Low intensity/);
  });

  test.each(editorialPages)("Coach navigation preserves the exact workout ID through %s", async (_name, route, path, Page, testId) => {
    mockAxios();
    renderWithProviders(
      <Routes>
        <Route path={path} element={<Page />} />
        <Route path="/coach" element={<LocationDisplay />} />
      </Routes>,
      route,
    );
    await screen.findByTestId(testId);
    fireEvent.click(screen.getByTestId("ask-coach-btn"));
    expect(await screen.findByTestId("current-location")).toHaveTextContent("/coach?analyze=w1");
  });

  describe.each(editorialPages)("%s PR320 contract", (name, route, path, Page, testId) => {
    test.each(["fr", "en", "es"])("unexplained consistency score is suppressed in %s", async (language) => {
      const text = {
        fr: "L’allure est restée régulière sur les portions mesurées.",
        en: "Pace remained consistent across the measured splits.",
        es: "El ritmo se mantuvo regular en los parciales medidos.",
      }[language];
      mockAxios({ analysisPayload: { ...analysis, meaning: { factual_observations: [
        factualObservation("fact.pacing_consistency", text, { consistency_score: 90 }),
      ] } } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
      await screen.findByTestId(testId);
      const labels = translations[language].workoutDetailExtended;
      expect(await screen.findByTestId(testId)).toBeVisible();
      expect(screen.queryByText(text)).not.toBeInTheDocument();
      expect(screen.queryByText(labels.coachObservation)).not.toBeInTheDocument();
      expect(screen.queryByText(analysis.advice.text)).not.toBeInTheDocument();
      expect(screen.queryByText(analysis.meaning.text)).not.toBeInTheDocument();
      expect(screen.queryByText(translations[language].sessions.nextSession)).not.toBeInTheDocument();
      expect(screen.queryByText(labels.adviceUnavailable)).not.toBeInTheDocument();
    });

    test.each(["fr", "en", "es"].flatMap((language) =>
      [false, undefined, "true", null].map((available) => [language, available]),
    ))("unavailable or legacy observation in %s (%s) cannot become advice", async (language, available) => {
      mockAxios({ analysisPayload: { ...analysis, advice: { available, text: "Do not prescribe this legacy text." } } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
      await screen.findByTestId(testId);
      expect(screen.queryByText(translations[language].workoutDetailExtended.adviceUnavailable)).not.toBeInTheDocument();
      expect(screen.queryByText("Do not prescribe this legacy text.")).not.toBeInTheDocument();
      expect(screen.getByTestId(testId)).not.toHaveTextContent("undefined");
      expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
    });

    test.each(["", "   ", null, undefined])("empty available observation (%s) uses a conservative fallback", async (text) => {
      mockAxios({ analysisPayload: { ...analysis, advice: { available: true, text } } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      await screen.findByTestId(testId);
      expect(screen.queryByText(translations.en.workoutDetailExtended.adviceUnavailable)).not.toBeInTheDocument();
      expect(screen.getByTestId(testId)).not.toHaveTextContent("undefined");
    });

    test.each(["fr", "en", "es"])("technical limitations stay hidden from the workout screen in %s", async (language) => {
      const localized = {
        fr: ["Zones non vérifiées.", "Comparaison limitée.", "Fractions manquantes."],
        en: ["Unverified zones.", "Limited comparison.", "Missing splits."],
        es: ["Zonas no verificadas.", "Comparación limitada.", "Faltan parciales."],
      }[language];
      const limitations = [
        { code: "limitations.intensity", text: localized[0] },
        { code: "limitations.intensity", text: "Duplicate code must not appear." },
        { code: "limitations.comparability", text: localized[1] },
        { code: "limitations.splits", text: localized[2] },
        { code: "limitations.other", text: localized[2] },
      ];
      mockAxios({ analysisPayload: { ...analysis, limitations } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
      await screen.findByTestId(testId);
      localized.forEach((text) => expect(screen.queryByText(text)).not.toBeInTheDocument());
      expect(screen.queryByText("Duplicate code must not appear.")).not.toBeInTheDocument();
      expect(screen.queryByText(analysis.signals.intensity.reason_unavailable)).not.toBeInTheDocument();
      expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
      expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
      expect(screen.queryByText(analysis.advice.text)).not.toBeInTheDocument();
      expect(screen.getByTestId("analysis-fallback")).toBeVisible();
    });

    test.each([undefined, [], null])("absent or empty limitations (%s) do not create an empty section", async (limitations) => {
      mockAxios({ analysisPayload: { ...analysis, limitations, signals: { ...analysis.signals, intensity: { available: true, text: "Observed intensity" } } } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      await screen.findByTestId(testId);
      expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
    });

    test.each([null, "api-error"])("empty or failed analysis (%s) preserves the secondary route", async (payload) => {
      mockAxios({ analysisPayload: payload === "api-error" ? null : payload, rejectAnalysis: payload === "api-error" });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      if (name === "DetailedAnalysis") {
        expect(await screen.findByTestId("analysis-not-found")).toHaveTextContent(translations.en.workout.notFound);
      } else {
        await screen.findByTestId(testId);
        expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
        expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
        expect(screen.getByTestId(testId)).not.toHaveTextContent("undefined");
      }
      expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
    });

    test("loading analysis does not prematurely expose an observation", async () => {
      let resolveAnalysis;
      mockAxios({ delayedAnalysis: new Promise((resolve) => { resolveAnalysis = resolve; }) });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      expect(screen.queryByText(analysis.advice.text)).not.toBeInTheDocument();
      expect(screen.queryByTestId("analysis-fallback")).not.toBeInTheDocument();
      resolveAnalysis({ data: analysis });
      expect(await screen.findByTestId("analysis-fallback")).toBeVisible();
      expect(screen.queryByText(analysis.advice.text)).not.toBeInTheDocument();
    });
  });

  test("technical limitations and historical data stay hidden while workout facts remain visible", async () => {
    mockAxios({
      analysisPayload: {
        ...analysis,
        meaning: { text: "Recorded steady running." },
        comparison: { ...analysis.comparison, similar: similarReference },
        limitations: [
          { code: "limitations.session_nature_unknown", text: "Localized session nature caveat." },
          { code: "limitations.intensity", text: "Localized intensity caveat." },
        ],
      },
    });
    renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
    await screen.findByTestId("coach-summary");
    expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
    expect(screen.queryByText("Localized session nature caveat.")).not.toBeInTheDocument();
    expect(screen.queryByText("Localized intensity caveat.")).not.toBeInTheDocument();
    expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
    expect(screen.getByTestId("primary-metrics")).toHaveTextContent("150 bpm");
    expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  });

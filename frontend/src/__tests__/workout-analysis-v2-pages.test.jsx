import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, Link } from "react-router-dom";
import axios from "axios";

import WorkoutDetail, { formatDistance, formatSignedDistance } from "@/pages/WorkoutDetail";
import Sessions from "@/pages/Sessions";
import Coach from "@/pages/Coach";
import DetailedAnalysis from "@/pages/DetailedAnalysis";
import SessionDetail from "@/pages/SessionDetail";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";
import { AuthProvider } from "@/context/AuthContext";
import { SubscriptionProvider } from "@/context/SubscriptionContext";
import { translations, LANGUAGE_STORAGE_KEY } from "@/lib/i18n";
import { formatPaceDisplay, formatPaceDelta } from "@/lib/workoutAnalysis";

jest.mock("axios");

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

function renderWithProviders(ui, route, language = "en") {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
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

function renderWithSubscriptionPlan(ui, route, plan) {
  window.localStorage.setItem("access_token", "test-access-token");
  return render(
    <LanguageProvider>
      <AuthProvider>
        <SubscriptionProvider>
          <UnitProvider>
            <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
          </UnitProvider>
        </SubscriptionProvider>
      </AuthProvider>
    </LanguageProvider>,
  );
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
  expect(await screen.findByTestId("coach-summary")).toHaveTextContent("Standard-duration session completed.");

  const analysisCalls = axios.get.mock.calls
    .map(([url]) => url)
    .filter((url) => url.includes("/coach/") || url.includes("/rag/"));

  expect(analysisCalls).toEqual([expect.stringContaining("/coach/workout-analysis/w1")]);
  expect(analysisCalls.some((url) => url.includes("/coach/detailed-analysis/"))).toBe(false);
  expect(analysisCalls.some((url) => url.includes("/rag/workout/"))).toBe(false);
  expect(screen.getByTestId("meaning-text")).toBeInTheDocument();
  expect(screen.getByTestId("advice-text")).toBeInTheDocument();
  expect(screen.getByTestId("meaning-text")).toBeVisible();
  expect(screen.getByTestId("advice-text")).toBeVisible();
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10 km");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("1h");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("6:00/km");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("150 bpm");
  expect(screen.getByTestId("evidence-card")).not.toBeVisible();
  expect(screen.getByTestId("analysis-details")).not.toHaveAttribute("open");
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Coach observation" })).toBeVisible();
  expect(screen.queryByTestId("similar-comparison-card")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  expect(screen.getByTestId("analysis-details")).toHaveAttribute("open");
  expect(screen.getByTestId("meaning-text")).toBeVisible();
  expect(screen.getByTestId("advice-text")).toBeVisible();
  expect(screen.getByTestId("evidence-card")).toBeVisible();
  expect(screen.getByTestId("hr-zones-card")).toBeVisible();
  expect(screen.queryByText("Easy effort")).not.toBeInTheDocument();
  expect(screen.queryByText("High intensity")).not.toBeInTheDocument();
  expect(screen.queryByText("Balanced")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  expect(screen.getByTestId("meaning-text")).toBeVisible();
  expect(within(screen.getByTestId("analysis-details")).queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(within(screen.getByTestId("analysis-details")).queryByTestId("advice-text")).not.toBeInTheDocument();
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
  expect(screen.getByTestId("intensity-card-unavailable")).toHaveTextContent(translations.en.workoutDetailExtended.intensityUnavailable);
  expect(screen.getByTestId("intensity-card-unavailable")).not.toHaveTextContent("Moderate intensity");
  expect(screen.getByText(/Moderate session volume/)).toBeInTheDocument();
  expect(screen.getByText(/Standard session/)).toBeInTheDocument();
  expect(screen.getByTestId("intensity-card-unavailable")).not.toHaveTextContent(
    analysisMissingEvidence.signals.intensity.reason_unavailable,
  );
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  expect(screen.getByTestId("analysis-limitations")).toHaveTextContent(analysisMissingEvidence.signals.intensity.reason_unavailable);
  expect(screen.getByText("Pacing evidence is unavailable.")).toBeVisible();
  expect(screen.getByText("No prior same-type workouts in the last 14 days.")).toBeVisible();
  expect(screen.getByTestId("heart-response")).toHaveTextContent("150 bpm");
});

test("structured phases show four efforts, four recoveries, statistics, and chronological details", async () => {
  const phaseAnalysis = makeStructuredPhaseAnalysis();
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: phaseAnalysis } });

  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );

  const section = await screen.findByTestId("structured-phase-analysis");
  expect(within(screen.getByTestId("phase-summary")).getAllByText("4")).toHaveLength(2);
  expect(section).toHaveTextContent("16:00");
  expect(section).toHaveTextContent("3.39 km");
  expect(section).toHaveTextContent("4:43/km");
  expect(section).toHaveTextContent("7.7 s/km");
  expect(section).toHaveTextContent("+8 bpm");
  expect(within(section).getAllByRole("listitem")).toHaveLength(4);
  expect(section.querySelectorAll("h5")).toHaveLength(4);
  expect(section).toHaveTextContent("4:48/km");
  expect(section).toHaveTextContent("832 m");
  expect(section).toHaveTextContent("151 bpm");
  expect(section).toHaveTextContent("175 bpm");
  expect(screen.getByTestId("coach-summary")).toHaveTextContent("Standard-duration session completed.");
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
  const effortRows = within(section).getAllByRole("listitem").slice(0, 4);
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
    expect(screen.getByTestId("splits-chart-card")).toBeVisible();
    unmount();
  }
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
  const effortRows = within(section).getAllByTestId("phase-effort-card");
  expect(within(effortRows[0]).queryByText("Following recovery")).not.toBeInTheDocument();
  expect(section).toHaveTextContent("Other phase");
  expect(section).toHaveTextContent("Recovery 1");
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
  expect(within(screen.getByTestId("phase-summary")).getByText("0")).toBeInTheDocument();
  expect(section).not.toHaveTextContent("Following recovery");
  expect(screen.queryByTestId("phase-recovery-card")).not.toBeInTheDocument();
});

test("missing heart-rate values are marked unavailable rather than fabricated", async () => {
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
  expect(section).toHaveTextContent("Not recorded");
  expect(section).toHaveTextContent(translations.en.workoutDetailExtended.phaseMissingHeartRate);
  expect(section).not.toHaveTextContent("undefined");
});

test("missing effort paces hide only unavailable pace indicators and translate limitations", async () => {
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
  expect(section).toHaveTextContent(translations.en.workoutDetailExtended.phaseMissingPace);
  expect(section).toHaveTextContent(translations.en.workoutDetailExtended.phaseLimitationIncompletePaces);
  expect(section).toHaveTextContent(translations.en.workoutDetailExtended.phaseLimitationGeneric);
  expect(section).not.toHaveTextContent("effort_paces_incomplete");
  expect(section).not.toHaveTextContent("future_internal_code");
  expect(section).not.toHaveTextContent("Average effort pace");
});

test("available regularity shows descriptive values and partial comparison is explicit", async () => {
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
  expect(regularity).toHaveTextContent("3 comparable efforts");
  expect(regularity).toHaveTextContent(translations.en.workoutDetailExtended.partialEffortComparison);
  expect(regularity).toHaveTextContent("+2.6 s/km");
  expect(regularity).toHaveTextContent("Average HR change across repetitions");
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
  expect(screen.getByText(translations.en.workoutDetailExtended.splitsUnavailable)).toBeVisible();
});

test("structured phases and kilometer splits remain independently visible", async () => {
  mockAxios({ analysisPayload: { ...analysis, phase_analysis: makeStructuredPhaseAnalysis() } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
  expect(screen.getByTestId("splits-chart-card")).toBeVisible();
  expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("5:54");
});

test.each(["free", "trial", "premium"])(
  "phase analysis remains at the existing Workout Detail access level for %s users",
  async (plan) => {
    const phaseAnalysis = makeStructuredPhaseAnalysis();
    axios.get.mockImplementation((url) => {
      if (url.endsWith("/auth/me")) return Promise.resolve({ data: { id: "synthetic-user" } });
      if (url.endsWith("/user/features")) return Promise.resolve({
        data: { has_premium_access: plan !== "free", trial_active: plan === "trial", feature_access: {} },
      });
      if (url.includes("/subscription/info")) return Promise.resolve({ data: { status: plan } });
      if (url.includes("/workouts/w1")) return Promise.resolve({ data: workout });
      if (url.includes("/coach/workout-analysis/w1")) return Promise.resolve({ data: { ...analysis, phase_analysis: phaseAnalysis } });
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    renderWithSubscriptionPlan(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1", plan);

    expect(await screen.findByTestId("structured-phase-analysis")).toBeVisible();
    await waitFor(() => expect(axios.get.mock.calls.some(([url]) => url.endsWith("/user/features"))).toBe(true));
    expect(screen.queryByText(/subscribe|upgrade/i)).not.toBeInTheDocument();
    window.localStorage.removeItem("access_token");
  },
);

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
  expect(screen.getByTestId("splits-chart-card")).toBeVisible();
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.getByTestId("splits-chart-card")).toBeVisible();
  expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("5:54");
  expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("6:06");
  expect(axios.get).toHaveBeenCalledTimes(2);
});

test("WorkoutDetail keeps factual splits accessible while canonical analysis is pending", async () => {
  let resolveAnalysis;
  const delayedAnalysis = new Promise((resolve) => { resolveAnalysis = resolve; });
  mockAxios({ delayedAnalysis });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1",
  );
  await screen.findByTestId("workout-detail");
  expect(screen.queryByTestId("analysis-details")).not.toBeInTheDocument();
  expect(screen.getByTestId("splits-chart-card")).toBeVisible();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.queryByTestId("coach-summary")).not.toBeInTheDocument();
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("10 km");
  expect(screen.getByTestId("splits-chart-card")).toBeVisible();
  expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("5:54");
  expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("6:06");
  resolveAnalysis({ data: analysis });
  await screen.findByTestId("coach-summary");
  expect(axios.get).toHaveBeenCalledTimes(2);
});

test.each(["fr", "en", "es"])("seven sections have translated headings in order in %s", async (language) => {
  mockAxios({ analysisPayload: { ...analysis, comparison: { ...analysis.comparison, similar: similarReference } } });
  renderWithProviders(
    <Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>,
    "/workout/w1", language,
  );
  await screen.findByTestId("coach-summary");
  const labels = translations[language].workoutDetailExtended;
  const headings = screen.getAllByRole("heading", { level: 2 });
  expect(headings.map((heading) => heading.textContent)).toEqual([
    labels.sessionSummary, labels.takeaways, labels.pacingSection, labels.heartResponse,
    labels.historyComparison, labels.coachObservation,
  ]);
  expect(screen.getByTestId("advanced-toggle")).toHaveTextContent(labels.advancedDetails);
  expect(screen.getByTestId("hr-zones-card")).toHaveTextContent(labels.zonesProvenance);
  expect(screen.getByTestId("hr-zones-card")).not.toHaveTextContent(translations[language].zones.threshold);
  expect(screen.getByTestId("heart-response")).not.toHaveTextContent(labels.hrDrift);
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("--");
});

test("missing metrics, HR, splits, history and analysis text have explicit empty states", async () => {
  mockAxios({
    workoutPayload: { ...workout, date: null, distance_km: null, duration_minutes: null, avg_pace_min_km: null, avg_heart_rate: null, max_heart_rate: null, km_splits: null },
    analysisPayload: { ...analysisMissingEvidence, summary: null, meaning: null, advice: null, evidence: null },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("workout-detail");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent("Not recorded");
  expect(screen.getByTestId("heart-response")).toHaveTextContent(analysisMissingEvidence.physiology.reason_unavailable);
  expect(screen.getByTestId("meaning-text")).toHaveTextContent(translations.en.workoutDetailExtended.meaningUnavailable);
  expect(screen.getByTestId("advice-unavailable")).toHaveTextContent(translations.en.workoutDetailExtended.adviceUnavailable);
  expect(screen.getByText(translations.en.workoutDetailExtended.splitsUnavailable)).toBeVisible();
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("--");
});

test.each([null, {}, { available: "true", text: "Untrustworthy intensity" }, { available: false, text: "Untrustworthy intensity" }])(
  "intensity requires a strictly true available flag: %s", async (intensity) => {
    mockAxios({ analysisPayload: { ...analysis, signals: { intensity } } });
    renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
    await screen.findByTestId("coach-summary");
    expect(screen.getByTestId("intensity-card-unavailable")).toBeVisible();
    expect(screen.queryByText(/Untrustworthy intensity/)).not.toBeInTheDocument();
  },
);

test("available intensity is displayed without reclassification", async () => {
  mockAxios({ analysisPayload: { ...analysis, signals: { intensity: { available: true, code: "low", text: "Engine supplied intensity" } } } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByText(/Engine supplied intensity/)).toBeVisible();
  expect(screen.queryByTestId("intensity-card-unavailable")).not.toBeInTheDocument();
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

test.each(["fr", "en", "es"])("cycling without recorded speed has a translated unavailable state in %s", async (language) => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle" },
    analysisPayload: { ...analysis, pacing: { available: false, average_speed_kmh: 25 } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1", language);
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent(translations[language].workoutDetailExtended.speedUnavailable);
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
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent(translations.en.workoutDetailExtended.dataUnavailable);
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
  expect(screen.getByTestId("pacing-summary-card")).toHaveTextContent("23.0 km/h");
  expect(within(screen.getByTestId("pacing-summary-card")).queryByText("6:00/km")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: translations[language].workoutDetailExtended.speedSection })).toBeVisible();
});

test.each([null, 0, -3, NaN, Infinity, -Infinity, "25"])("cycling rejects unusable speeds %s without deriving speed", async (speed) => {
  mockAxios({
    workoutPayload: { ...workout, type: "cycle", avg_speed_kmh: speed },
    analysisPayload: { ...analysis, pacing: { available: true, average_pace_min_km: 6, average_speed_kmh: speed } },
  });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent(translations.en.workoutDetailExtended.speedUnavailable);
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
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent(translations.en.workoutDetailExtended.speedUnavailable);
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
  const card = screen.getByTestId("pacing-summary-card");
  expect(card).toHaveTextContent("10.0 km/h");
  expect(card).not.toHaveTextContent("/km");
  expect(screen.queryByTestId("similar-pace")).not.toBeInTheDocument();
  expect(screen.queryByTestId("splits-chart-card")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("NaN");
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("Infinity");
});

test.each([null, 0, -2, NaN, Infinity])("an invalid pace %s without a usable speed produces an explicit pacing empty state", async (pace) => {
  mockAxios({ analysisPayload: { ...analysis, pacing: { available: true, average_pace_min_km: pace, average_speed_kmh: 0 } } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("pacing-summary-card")).not.toBeInTheDocument();
  expect(screen.getByText(translations.en.workoutDetailExtended.pacingUnavailable)).toBeVisible();
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
    expect(screen.getByTestId("heart-response")).toHaveTextContent(translations.en.workoutDetailExtended.heartRateUnavailable);
  },
);

test("unavailable zones are hidden even if percentages are present", async () => {
  mockAxios({ analysisPayload: { ...analysis, physiology: { ...analysis.physiology, available: false } } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  expect(screen.queryByTestId("hr-zones-card")).not.toBeInTheDocument();
});

test("valid zone rows retain a mobile-readable provenance warning and omit invalid percentages", async () => {
  mockAxios({ analysisPayload: { ...analysis, physiology: { ...analysis.physiology, zone_distribution: { z1: 30, z2: NaN, z3: -2, z4: 101, z5: null } } } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  const zones = screen.getByTestId("hr-zones-card");
  expect(within(zones).getByText(translations.en.workoutDetailExtended.zonesProvenance)).toHaveClass("text-sm");
  expect(zones).toHaveTextContent("Z1");
  ["Z2", "Z3", "Z4", "Z5", "NaN", "Infinity"].forEach((label) => expect(within(zones).queryByText(label, { exact: true })).not.toBeInTheDocument());
});

test("invalid splits are omitted and all valid long-activity splits remain accessible", async () => {
  const splits = Array.from({ length: 30 }, (_, i) => ({ km: i + 1, pace_min_km: 6, pace_str: "6:00" }));
  mockAxios({ workoutPayload: { ...workout, km_splits: [...splits, null, { km: 31, pace_min_km: null }] } });
  renderWithProviders(<Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes>, "/workout/w1");
  await screen.findByTestId("coach-summary");
  const region = within(screen.getByTestId("splits-chart-card")).getByRole("region");
  expect(region).toHaveAttribute("tabindex", "0");
  expect(within(region).getByText("30", { exact: true })).toBeVisible();
  expect(within(region).getByText("2", { exact: true })).toBeVisible();
  expect(screen.getByText(translations.en.workoutDetailExtended.invalidSplits)).toBeVisible();
  expect(screen.getByTestId("splits-chart-card")).not.toHaveTextContent("NaN");
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
  expect(screen.getByText(translations.en.workoutDetailExtended.analysisUnavailable)).toBeVisible();
  expect(screen.queryByText(translations.en.workoutDetailExtended.analysisLoadError)).not.toBeInTheDocument();
  expect(screen.getByTestId("splits-chart-card")).toBeVisible();
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
    return Promise.resolve({ data: { ...analysis, summary: { text: "New analysis" } } });
  });
  renderWithProviders(
    <><Link to="/workout/w2">Next activity</Link><Routes><Route path="/workout/:id" element={<WorkoutDetail />} /></Routes></>,
    "/workout/w1",
  );
  const firstSignals = axios.get.mock.calls.map(([, options]) => options.signal);
  fireEvent.click(screen.getByText("Next activity"));
  expect(firstSignals.every((signal) => signal.aborted)).toBe(true);
  await screen.findByText("New analysis");
  resolveWorkout({ data: workout });
  resolveAnalysis({ data: analysis });
  await waitFor(() => expect(screen.getByTestId("coach-summary")).toHaveTextContent("New analysis"));
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

test.each([
  ["fr", "Allure", "Durée", "FC", "Comparaison récente · 14 jours", "Sorties similaires · 180 jours"],
  ["en", "Pace", "Duration", "HR", "Recent comparison · 14 days", "Similar sessions · 180 days"],
  ["es", "Ritmo", "Duración", "FC", "Comparación reciente · 14 días", "Salidas similares · 180 días"],
])("WorkoutDetail localizes facts and separates recent and similar references in %s", async (
  language, pace, duration, hr, recentTitle, similarTitle,
) => {
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
  const pacing = screen.getByTestId("pacing-summary-card");
  const recent = screen.getByTestId("comparison-card");
  const similar = screen.getByTestId("similar-comparison-card");
  expect(within(pacing).getByText(pace)).toBeVisible();
  expect(within(pacing).getByText("+0:12/km")).toBeVisible();
  expect(within(recent).getByText(recentTitle)).toBeVisible();
  expect(within(recent).getByText(duration)).toBeVisible();
  expect(within(recent).getByText(hr)).toBeVisible();
  expect(within(recent).getByText("-0:06/km")).toBeVisible();
  expect(recent).toHaveTextContent(translations[language].workoutDetailExtended.sampleCount.replace("{count}", "2"));
  expect(within(similar).getByText(similarTitle)).toBeVisible();
  expect(similar).toHaveTextContent("6:01/km");
  expect(similar).toHaveTextContent("-0:01/km");
  expect(similar).toHaveTextContent("148 bpm");
  expect(similar).toHaveTextContent("+2 bpm");
  expect(similar).toHaveTextContent(translations[language].workoutDetailExtended.sampleCount.replace("{count}", "5"));
  expect(similar).toHaveTextContent(translations[language].workoutDetailExtended.paceSampleCount.replace("{count}", "2").replace("{total}", "5"));
  expect(similar).toHaveTextContent(translations[language].workoutDetailExtended.hrSampleCount.replace("{count}", "3").replace("{total}", "5"));
  expect(screen.getByTestId("similar-comparability-caveat")).toHaveTextContent(translations[language].workoutDetailExtended.limitedComparability);
  expect(screen.getByTestId("history-section")).toHaveTextContent(translations[language].workoutDetailExtended.descriptiveComparison);
  expect(similar).not.toHaveTextContent("999");
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.getByTestId("meaning-text")).toBeVisible();
  expect(screen.getByTestId("intensity-card-unavailable")).toHaveTextContent(translations[language].workoutDetailExtended.intensityUnavailable);
  expect(screen.getByTestId("intensity-card-unavailable")).not.toHaveTextContent(analysis.signals.intensity.reason_unavailable);
  expect(pacing.compareDocumentPosition(recent) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(recent.compareDocumentPosition(similar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(similar.compareDocumentPosition(screen.getByTestId("ask-coach-btn")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByTestId("ask-coach-btn").compareDocumentPosition(screen.getByTestId("analysis-details")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  expect(within(screen.getByTestId("analysis-details")).queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(within(screen.getByTestId("analysis-details")).getByText(translations[language].workoutDetailExtended.limitations)).toBeVisible();
  expect(similar).not.toHaveTextContent(translations[language].workoutDetailExtended.unknownSessionNature);
  expect(screen.getByTestId("analysis-limitations")).toHaveTextContent(translations[language].workoutDetailExtended.unknownSessionNature);
  expect(screen.getByTestId("analysis-limitations")).not.toHaveTextContent("session_nature_unknown");
  expect(screen.queryByText(translations[language].zones.dominant_easy)).not.toBeInTheDocument();
  expect(screen.queryByText(translations[language].zones.dominant_hard)).not.toBeInTheDocument();
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
  const recent = screen.getByTestId("comparison-card");
  const similar = screen.getByTestId("similar-comparison-card");
  const pacing = screen.getByTestId("pacing-summary-card");
  expect(within(recent).getByText("Comparaison récente · 14 jours")).toBeVisible();
  expect(within(recent).getByText("-0:01/km")).toBeVisible();
  expect(recent).not.toHaveTextContent("+0:12/km");
  expect(within(similar).getByText("Sorties similaires · 180 jours")).toBeVisible();
  expect(similar).toHaveTextContent("5 séances de référence");
  expect(similar).toHaveTextContent("Allure moyenne: 6:36/km");
  expect(similar).toHaveTextContent("Écart: +0:12/km");
  expect(similar).not.toHaveTextContent("-0:01/km");
  expect(similar).toHaveTextContent("FC moyenne: 137 bpm");
  expect(similar).toHaveTextContent("Écart: +4 bpm");
  expect(screen.getByTestId("history-section")).toHaveTextContent("Écart descriptif, pas une conclusion de performance.");
  expect(within(pacing).getByText("Allure")).toBeVisible();
  expect(within(pacing).queryByText(/Comparaison/)).not.toBeInTheDocument();
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
  expect(screen.getByTestId("similar-comparison-card")).toBeVisible();
  expect(screen.getByTestId("similar-pace")).not.toHaveTextContent("Difference:");
  expect(screen.getByTestId("similar-heart-rate")).not.toHaveTextContent("Difference:");
  expect(screen.getByTestId("similar-pace")).not.toHaveTextContent("0:00/km");
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
  expect(screen.getByTestId("comparison-card")).not.toHaveTextContent("reference session");
  expect(screen.getByTestId("similar-pace")).not.toHaveTextContent("Pace evidence");
  expect(screen.getByTestId("similar-heart-rate")).not.toHaveTextContent("Heart-rate evidence");
  expect(screen.getByTestId("similar-comparison-card")).not.toHaveTextContent("-- of");
  if (sampleCount == null) expect(screen.getByTestId("similar-comparison-card")).not.toHaveTextContent("reference session");
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
  expect(screen.getByTestId("similar-heart-rate")).toHaveTextContent("Average heart rate: 137 bpm");
  expect(screen.getByTestId("similar-heart-rate")).toHaveTextContent("Difference: +4 bpm");
  expect(screen.getByTestId("similar-heart-rate")).not.toHaveTextContent("136.8");
  expect(screen.getByTestId("similar-heart-rate")).not.toHaveTextContent("3.8");
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
])("WorkoutDetail renders formatted distances in recent, similar and volume cards (%s, %s)", async (
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
  const recent = screen.getByTestId("comparison-card");
  if (Number.isFinite(delta)) {
    expect(within(recent).getByText("Distance").nextSibling.textContent).toBe(deltaText);
  } else {
    expect(within(recent).queryByText("Distance")).not.toBeInTheDocument();
  }
  if (Number.isFinite(absolute)) {
    expect(screen.getByTestId("similar-comparison-card")).toHaveTextContent(`Average distance: ${absoluteText}`);
  } else {
    expect(screen.getByTestId("similar-comparison-card")).not.toHaveTextContent("Average distance:");
  }
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent(absoluteText === "--" ? "Not recorded" : absoluteText);
  expect(screen.getByTestId("workout-detail").textContent).not.toMatch(/[+-]?\d+\.\d{3,}\s*km/);
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("-0 km");
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("+0 km");
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
])("reference counts use human plurals in %s for %s", async (language, count, expected) => {
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
  expect(screen.getByTestId("comparison-card")).toHaveTextContent(expected);
  expect(screen.getByTestId("similar-comparison-card")).toHaveTextContent(expected);
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("(s)");
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("(es)");
});

test.each([
  [42.678, 150.789, 2.789, -3.789, "43m", "151 bpm", "+3 min", "-4 bpm"],
  [59.999, 0, 0, 0, "1h", "0 bpm", "0 min", "0 bpm"],
  [119.999, 136.8, -0.1, 0.1, "2h", "137 bpm", "0 min", "0 bpm"],
  [0, null, null, null, "0m", null, "--", "--"],
  [null, NaN, NaN, Infinity, "--", "--", "--", "--"],
])("WorkoutDetail formats duration %s and HR %s without raw decimals or fabricated data", async (
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
  expect(screen.getByTestId("primary-metrics")).toHaveTextContent(durationText === "--" ? "Not recorded" : durationText);
  const recent = screen.getByTestId("comparison-card");
  if (Number.isFinite(minuteDelta)) {
    expect(within(recent).getByText("Duration").nextSibling).toHaveTextContent(minuteDeltaText);
  } else {
    expect(within(recent).queryByText("Duration")).not.toBeInTheDocument();
  }
  if (Number.isFinite(hrDelta)) {
    expect(within(recent).getByText("HR").nextSibling).toHaveTextContent(hrDeltaText);
  } else {
    expect(within(recent).queryByText("HR")).not.toBeInTheDocument();
  }
  const intensity = screen.getByTestId("intensity-card-unavailable");
  expect(intensity).not.toHaveTextContent("bpm");
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  if (Number.isFinite(heartRate) && heartRate > 0) {
    expect(screen.getByTestId("heart-response")).toHaveTextContent(hrText);
    expect(screen.getByTestId("splits-chart-card")).toHaveTextContent(hrText);
  } else {
    expect(screen.getByTestId("splits-chart-card")).not.toHaveTextContent("bpm");
  }
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("NaN");
  expect(screen.getByTestId("workout-detail")).not.toHaveTextContent("Infinity");
  expect(workoutPayload.duration_minutes).toBe(minutes);
  expect(analysisPayload.physiology.avg_hr).toBe(heartRate);
  expect(analysisPayload.comparison.duration_minutes.difference).toBe(minuteDelta);
  expect(analysisPayload.comparison.avg_heart_rate.difference).toBe(hrDelta);
});

test("unavailable similar reference gives a human caveat without fabricated metrics", async () => {
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
  expect(screen.getByTestId("similar-comparison-card")).toHaveTextContent("No earlier session of comparable distance was found.");
  expect(screen.queryByTestId("similar-pace")).not.toBeInTheDocument();
  expect(screen.queryByTestId("similar-heart-rate")).not.toBeInTheDocument();
});

test.each(["fr", "en", "es"])("WorkoutDetail business keys are explicitly translated in %s", (language) => {
  const keys = [
    "pace", "speed", "distance", "duration", "heartRate", "recentComparison", "similarComparison",
    "sampleCount", "paceSampleCount", "hrSampleCount", "averageDistance", "averagePace",
    "averageHeartRate", "difference", "descriptiveComparison", "similarUnavailable",
    "analysisDetails", "analysisAdvice", "analysisUnavailable", "evidence", "version",
    "hrZonesEvidence", "splitsEvidence", "baselineEvidence", "cadenceEvidence", "elevationEvidence",
    "yes", "no", "limitations", "unknownSessionNature", "smallSample", "smallPaceSample", "smallHrSample",
    "intensityUnavailable",
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

  expect(await screen.findByTestId("header-context")).toHaveTextContent("Standard-duration session completed.");
  const urls = axios.get.mock.calls.map(([url]) => url);
  expect(urls).toEqual([expect.stringContaining("/coach/workout-analysis/w1")]);
  expect(screen.getByText("Type")).toBeInTheDocument();
  expect(screen.queryByText("Regularity")).not.toBeInTheDocument();
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

  describe.each(editorialPages)("%s PR320 contract", (name, route, path, Page, testId) => {
    test.each(["fr", "en", "es"])("available observation is factual and localized in %s", async (language) => {
      mockAxios();
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
      await screen.findByTestId(testId);
      const labels = translations[language].workoutDetailExtended;
      expect(screen.getByText(labels.coachObservation)).toBeVisible();
      expect(screen.getByText(analysis.advice.text)).toBeVisible();
      expect(screen.getByText(analysis.meaning.text)).toBeVisible();
      expect(screen.queryByText(translations[language].sessions.nextSession)).not.toBeInTheDocument();
      expect(screen.queryByText(labels.adviceUnavailable)).not.toBeInTheDocument();
    });

    test.each(["fr", "en", "es"].flatMap((language) =>
      [false, undefined, "true", null].map((available) => [language, available]),
    ))("unavailable or legacy observation in %s (%s) cannot become advice", async (language, available) => {
      mockAxios({ analysisPayload: { ...analysis, advice: { available, text: "Do not prescribe this legacy text." } } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route, language);
      await screen.findByTestId(testId);
      expect(screen.getByText(translations[language].workoutDetailExtended.adviceUnavailable)).toBeVisible();
      expect(screen.queryByText("Do not prescribe this legacy text.")).not.toBeInTheDocument();
      expect(screen.getByTestId(testId)).not.toHaveTextContent("undefined");
      if (name !== "SessionDetail") expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
    });

    test.each(["", "   ", null, undefined])("empty available observation (%s) uses a conservative fallback", async (text) => {
      mockAxios({ analysisPayload: { ...analysis, advice: { available: true, text } } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      await screen.findByTestId(testId);
      expect(screen.getByText(translations.en.workoutDetailExtended.adviceUnavailable)).toBeVisible();
      expect(screen.getByTestId(testId)).not.toHaveTextContent("undefined");
    });

    test.each(["fr", "en", "es"])("localized limitations are deduplicated and never appended to meaning in %s", async (language) => {
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
      if (name === "SessionDetail") fireEvent.click(screen.getByText(translations[language].workoutDetailExtended.advancedDetails));
      else fireEvent.click(screen.getByTestId("advanced-toggle"));
      const section = screen.getByTestId("analysis-limitations");
      localized.forEach((text) => {
        expect(within(section).getByText(text)).toBeVisible();
        expect(screen.getAllByText(text)).toHaveLength(1);
      });
      expect(screen.queryByText("Duplicate code must not appear.")).not.toBeInTheDocument();
      expect(screen.queryByText(analysis.signals.intensity.reason_unavailable)).not.toBeInTheDocument();
      expect(screen.getAllByText(analysis.meaning.text)).toHaveLength(1);
      expect(section).not.toHaveTextContent(analysis.meaning.text);
    });

    test.each([undefined, [], null])("absent or empty limitations (%s) do not create an empty section", async (limitations) => {
      mockAxios({ analysisPayload: { ...analysis, limitations, signals: { ...analysis.signals, intensity: { available: true, text: "Observed intensity" } } } });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      await screen.findByTestId(testId);
      if (name !== "SessionDetail") fireEvent.click(screen.getByTestId("advanced-toggle"));
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
    });

    test("loading analysis does not prematurely expose an observation", async () => {
      let resolveAnalysis;
      mockAxios({ delayedAnalysis: new Promise((resolve) => { resolveAnalysis = resolve; }) });
      renderWithProviders(<Routes><Route path={path} element={<Page />} /></Routes>, route);
      expect(screen.queryByText(analysis.advice.text)).not.toBeInTheDocument();
      resolveAnalysis({ data: analysis });
      expect(await screen.findByText(analysis.advice.text)).toBeVisible();
    });
  });

  test("limitations link opens advanced details without repeating the historical caveat", async () => {
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
    fireEvent.click(screen.getByRole("link", { name: translations.en.workoutDetailExtended.viewLimitations }));
    expect(screen.getByTestId("analysis-details")).toHaveAttribute("open");
    expect(screen.getAllByText("Localized session nature caveat.")).toHaveLength(1);
    expect(screen.getByTestId("similar-comparison-card")).not.toHaveTextContent("Localized session nature caveat.");
    expect(screen.getByTestId("meaning-text").textContent).toBe("Recorded steady running.");
    expect(screen.getByTestId("primary-metrics")).toHaveTextContent("150 bpm");
    expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("5:54");
  });

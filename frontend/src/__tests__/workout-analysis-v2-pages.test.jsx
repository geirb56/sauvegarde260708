import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import axios from "axios";

import WorkoutDetail from "@/pages/WorkoutDetail";
import Coach from "@/pages/Coach";
import DetailedAnalysis from "@/pages/DetailedAnalysis";
import SessionDetail from "@/pages/SessionDetail";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";
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
  advice: { code: "advice.hr_without_intensity", text: "Use individualized heart-rate zones on future sessions before treating raw heart-rate values as intensity evidence." },
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

function mockAxios({ analysisPayload = analysis, delayedAnalysis = null, rejectAnalysis = false } = {}) {
  axios.get.mockImplementation((url) => {
    if (url.includes("/workouts/w1")) {
      return Promise.resolve({ data: workout });
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
  expect(screen.getByTestId("meaning-text")).not.toBeVisible();
  expect(screen.getByTestId("advice-text")).not.toBeVisible();
  expect(screen.getByTestId("evidence-card")).not.toBeVisible();
  expect(screen.getByTestId("analysis-details")).not.toHaveAttribute("open");
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.queryByText("Coach advice")).not.toBeInTheDocument();
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
  expect(screen.getByTestId("meaning-text")).not.toBeVisible();
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
  expect(screen.getByText("Moderate session volume")).toBeInTheDocument();
  expect(screen.getByText("Standard session")).toBeInTheDocument();
  expect(screen.getByTestId("intensity-card-unavailable")).not.toHaveTextContent(
    analysisMissingEvidence.signals.intensity.reason_unavailable,
  );
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  expect(screen.getByTestId("analysis-limitations")).toHaveTextContent(analysisMissingEvidence.signals.intensity.reason_unavailable);
  expect(screen.getByTestId("analysis-limitations")).toHaveTextContent("Heart-rate evidence is unavailable.");
  expect(screen.getByTestId("analysis-limitations")).toHaveTextContent("Pacing evidence is unavailable.");
  expect(screen.getByTestId("analysis-limitations")).toHaveTextContent("No prior same-type workouts in the last 14 days.");
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
  expect(screen.getByText("Analysis unavailable")).toBeVisible();
  expect(screen.getByTestId("analysis-details")).not.toHaveAttribute("open");
  expect(screen.getByTestId("splits-chart-card")).not.toBeVisible();
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  fireEvent.click(screen.getByTestId("advanced-toggle"));
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
  expect(screen.getByTestId("analysis-details")).not.toHaveAttribute("open");
  expect(screen.getByTestId("splits-chart-card")).not.toBeVisible();
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.queryByTestId("coach-summary")).not.toBeInTheDocument();
  expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("advice-text")).not.toBeInTheDocument();
  expect(screen.queryByTestId("evidence-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("analysis-limitations")).not.toBeInTheDocument();
  expect(screen.getByTestId("ask-coach-btn").compareDocumentPosition(screen.getByTestId("analysis-details")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  expect(screen.getByTestId("splits-chart-card")).toBeVisible();
  expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("5:54");
  expect(screen.getByTestId("splits-chart-card")).toHaveTextContent("6:06");
  resolveAnalysis({ data: analysis });
  await screen.findByTestId("coach-summary");
  expect(axios.get).toHaveBeenCalledTimes(2);
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
  expect(screen.getByTestId("similar-comparability-caveat")).toHaveTextContent(translations[language].workoutDetailExtended.descriptiveComparison);
  expect(similar).not.toHaveTextContent("999");
  expect(screen.getByTestId("ask-coach-btn")).toBeVisible();
  expect(screen.getByTestId("meaning-text")).not.toBeVisible();
  expect(screen.getByTestId("intensity-card-unavailable")).toHaveTextContent(translations[language].workoutDetailExtended.intensityUnavailable);
  expect(screen.getByTestId("intensity-card-unavailable")).not.toHaveTextContent(analysis.signals.intensity.reason_unavailable);
  expect(pacing.compareDocumentPosition(recent) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(recent.compareDocumentPosition(similar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(similar.compareDocumentPosition(screen.getByTestId("ask-coach-btn")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByTestId("ask-coach-btn").compareDocumentPosition(screen.getByTestId("analysis-details")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(screen.getByTestId("advanced-toggle"));
  expect(within(screen.getByTestId("analysis-details")).getByText(translations[language].workoutDetailExtended.interpretation)).toBeVisible();
  expect(within(screen.getByTestId("analysis-details")).getByText(translations[language].workoutDetailExtended.limitations)).toBeVisible();
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
  expect(similar).toHaveTextContent("5 séance(s) de référence");
  expect(similar).toHaveTextContent("Allure moyenne: 6:36/km");
  expect(similar).toHaveTextContent("Écart: +0:12/km");
  expect(similar).not.toHaveTextContent("-0:01/km");
  expect(similar).toHaveTextContent("FC moyenne: 137 bpm");
  expect(similar).toHaveTextContent("Écart: +4 bpm");
  expect(similar).toHaveTextContent("Écart descriptif, pas une conclusion de performance.");
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
  expect(screen.getByTestId("similar-pace")).toHaveTextContent("Difference: --");
  expect(screen.getByTestId("similar-heart-rate")).toHaveTextContent("Difference: --");
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
    return Promise.reject(new Error(`unexpected ${url}`));
  });
  axios.post.mockResolvedValue({ data: { response: "Coach analyzed the selected workout." } });

  renderWithProviders(
    <Routes>
      <Route path="/workout/:id" element={<WorkoutDetail />} />
      <Route path="/coach" element={<Coach />} />
    </Routes>,
    "/workout/w1",
  );

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

import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import axios from "axios";

import WorkoutDetail from "@/pages/WorkoutDetail";
import DetailedAnalysis from "@/pages/DetailedAnalysis";
import SessionDetail from "@/pages/SessionDetail";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";

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
  summary: { code: "summary.moderate_with_hr", text: "Moderate aerobic session with controlled cardiovascular load." },
  signals: {
    intensity: { code: "moderate", text: "Moderate intensity" },
    volume: { code: "usual", text: "Close to recent volume" },
    session_type: { code: "steady", text: "Steady session" },
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
  meaning: { code: "meaning.with_hr_moderate", text: "Heart-rate evidence points to a balanced aerobic load with meaningful work but no clear overload signal." },
  advice: { code: "advice.build_progressively", text: "Progress volume gradually and use heart-rate evidence on future sessions before drawing stronger conclusions." },
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

function renderWithProviders(ui, route) {
  window.localStorage.setItem("runindex-language", "en");
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
  expect(await screen.findByTestId("coach-summary")).toHaveTextContent("Moderate aerobic session");

  const analysisCalls = axios.get.mock.calls
    .map(([url]) => url)
    .filter((url) => url.includes("/coach/") || url.includes("/rag/"));

  expect(analysisCalls).toEqual([expect.stringContaining("/coach/workout-analysis/w1")]);
  expect(analysisCalls.some((url) => url.includes("/coach/detailed-analysis/"))).toBe(false);
  expect(analysisCalls.some((url) => url.includes("/rag/workout/"))).toBe(false);
  expect(screen.getByTestId("meaning-text")).toBeInTheDocument();
  expect(screen.getByTestId("advice-text")).toBeInTheDocument();
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
  await waitFor(() => expect(screen.getAllByText(/analyse indisponible|analysis unavailable/i).length).toBeGreaterThan(0));
});

test("DetailedAnalysis uses the canonical V2 endpoint", async () => {
  mockAxios();

  renderWithProviders(
    <Routes>
      <Route path="/workout/:id/analysis" element={<DetailedAnalysis />} />
    </Routes>,
    "/workout/w1/analysis",
  );

  expect(await screen.findByTestId("header-context")).toHaveTextContent("Moderate aerobic session");
  const urls = axios.get.mock.calls.map(([url]) => url);
  expect(urls).toEqual([expect.stringContaining("/coach/workout-analysis/w1")]);
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

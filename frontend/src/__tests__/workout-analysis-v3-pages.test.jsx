import React from "react";
import "@testing-library/jest-dom";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import axios from "axios";

import WorkoutDetail from "@/pages/WorkoutDetail";
import SessionDetail from "@/pages/SessionDetail";
import DetailedAnalysis from "@/pages/DetailedAnalysis";
import { LanguageProvider, useLanguage } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { LANGUAGE_STORAGE_KEY, translations } from "@/lib/i18n";

jest.mock("axios");
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(),
}));

const pages = [
  ["WorkoutDetail", "/workout/w1", "/workout/:id", WorkoutDetail],
  ["SessionDetail", "/sessions/w1", "/sessions/:id", SessionDetail],
  ["DetailedAnalysis", "/workout/w1/analysis", "/workout/:id/analysis", DetailedAnalysis],
];
const languages = ["fr", "en", "es"];
const legacyText = "Legacy Coach V1 conclusion.";
const legacyMeaning = "Legacy meaning must not duplicate the narrative.";
const legacyAdvice = "Legacy advice must not duplicate the narrative.";
const legacySynthesis = "Legacy synthesis must not duplicate the narrative.";
const copy = {
  fr: {
    headline: "Une séance de fractionné observée.",
    analysis: "Six efforts et cinq récupérations ont été enregistrés.",
    interpretation: "Ces observations ne déterminent pas une zone physiologique.",
    unknownAnalysis: "Aucune phase structurée ni aucun détail kilométrique n’est disponible.",
    unknownInterpretation: "Le type de séance ne peut pas être déterminé.",
    probable: /probab/i,
    unknown: /indétermin|inconn|non détermin/i,
    improvement: /amélioration|progression/i,
    insufficient: /insuffisan|indisponible|pas assez/i,
  },
  en: {
    headline: "An observed interval session.",
    analysis: "Six efforts and five recoveries were recorded.",
    interpretation: "These observations do not establish a physiological zone.",
    unknownAnalysis: "No structured phases or kilometer splits are available.",
    unknownInterpretation: "The session type cannot be determined.",
    probable: /probab/i,
    unknown: /unknown|undetermined|not determined/i,
    improvement: /improvement|improving/i,
    insufficient: /insufficient|unavailable|not enough/i,
  },
  es: {
    headline: "Una sesión de intervalos observada.",
    analysis: "Se registraron seis esfuerzos y cinco recuperaciones.",
    interpretation: "Estas observaciones no determinan una zona fisiológica.",
    unknownAnalysis: "No hay fases estructuradas ni parciales por kilómetro disponibles.",
    unknownInterpretation: "No se puede determinar el tipo de sesión.",
    probable: /probab/i,
    unknown: /desconocid|indeterminad|no determinad/i,
    improvement: /mejora|progreso/i,
    insufficient: /insuficien|no disponible|no hay suficientes/i,
  },
};

const workout = {
  id: "w1", name: "Morning Run", type: "run", date: "2024-01-10T07:00:00Z",
  distance_km: 10, duration_minutes: 60, avg_pace_min_km: 6,
  avg_heart_rate: 150, max_heart_rate: 170,
  km_splits: [
    { km: 1, pace_min_km: 5.9, pace_str: "5:54" },
    { km: 2, pace_min_km: 6.1, pace_str: "6:06" },
  ],
};

function makePhases(regularityAvailable = true) {
  const efforts = Array.from({ length: 6 }, (_, index) => ({
    order: index * 2 + 1, phase_type: "effort", effort_number: index + 1,
    duration_s: 180, distance_m: 600, pace_sec_per_km: 300 + index,
    average_hr: 150 + index, max_hr: 165 + index,
  }));
  const recoveries = Array.from({ length: 5 }, (_, index) => ({
    order: index * 2 + 2, phase_type: "recovery", recovery_number: index + 1,
    duration_s: 120, distance_m: 200, pace_sec_per_km: 600,
    average_hr: 130, max_hr: 145,
  }));
  return {
    available: true, analysis_type: "structured_phases",
    phases: efforts.flatMap((effort, index) => (
      recoveries[index] ? [effort, recoveries[index]] : [effort]
    )),
    efforts, recoveries,
    effort_statistics: {
      count: 6, total_duration_s: 1080, total_distance_m: 3600,
      average_pace_sec_per_km: 302.5, average_hr: 152.5, max_hr: 170,
    },
    recovery_statistics: { count: 5, total_duration_s: 600, total_distance_m: 1000 },
    effort_regularity: {
      available: regularityAvailable, effort_count: 6, comparable_effort_count: regularityAvailable ? 6 : 0,
      comparability_basis: regularityAvailable ? "duration" : null,
      pace_sample_count: regularityAvailable ? 6 : 0, partial_comparison: false,
      pace_dispersion_sec_per_km: regularityAvailable ? 6.6 : null,
      first_to_last_pace_change_sec_per_km: null, average_hr_change_bpm: null,
    },
    missing_data: [], limitations: [],
  };
}

function makeAnalysis(regularityAvailable = true) {
  return {
    version: "v2",
    workout: { id: workout.id, name: workout.name, date: workout.date, type: workout.type },
    summary: { code: "summary.standard_structural", text: "Recorded session." },
    signals: {
      intensity: { available: false, code: null, text: null, reason_unavailable: "No personal thresholds." },
      volume: { available: true, code: "usual_recent", text: "Usual volume." },
      session_type: { available: true, code: "standard", text: "Standard session." },
      session_structure: { available: true, code: "intervals" },
    },
    physiology: {
      available: true, avg_hr: 150, max_hr: 170, zone_distribution: null,
      hr_drift: null, reason_unavailable: null,
    },
    pacing: {
      available: true, average_pace_min_km: 6, average_speed_kmh: null,
      fastest_split_min_km: 5.9, slowest_split_min_km: 6.1, pace_drop_min_km: 0.2,
      negative_split: false, consistency_score: 90, variability: 0.1,
    },
    comparison: {
      available: false, baseline_period_days: 14, baseline_sample_count: 0,
      distance_km: { current: 10, baseline: null, difference: null, percent_change: null },
      duration_minutes: { current: 60, baseline: null, difference: null, percent_change: null },
      avg_heart_rate: null, avg_pace_min_km: null, avg_speed_kmh: null,
      reason_unavailable: "No comparable history.",
    },
    meaning: {
      text: legacyMeaning,
      factual_observations: [
        { code: "fact.recorded_hr", placement: "summary", text: legacyMeaning, evidence: { avg_hr: 150 } },
      ],
    },
    advice: { available: true, code: "advice.recorded", text: legacyAdvice },
    coach_language: {
      version: "v1",
      conclusions: [{
        code: "coach.pacing", text: legacyText, category: "pacing", priority: 30,
        available: true, kind: "conclusion", evidence: { split_count: 2 },
        replaces_factual_codes: [],
      }],
    },
    phase_analysis: makePhases(regularityAvailable),
    evidence: {
      has_heart_rate: true, has_hr_zones: false, has_splits: true,
      has_baseline: false, has_cadence: false, has_elevation: false,
    },
  };
}

function makeIntelligence(language = "en", updates = {}) {
  return {
    workout_id: "w1",
    narrative_coach_v3: {
      headline: copy[language].headline, analysis: copy[language].analysis,
      interpretation: copy[language].interpretation, recommendation: null,
      limitations: [], language, generation_mode: "deterministic_fallback",
      evidence_refs: ["session_classification.evidence.effort_count"],
    },
    workout_intelligence_v3: {
      version: "v3", workout_id: "w1", analyzed_date: workout.date, data_used: [],
      session_classification: {
        type: "intervals", confidence: "medium", decision_tier: "garmin_phases",
        evidence: { effort_count: 6, recovery_count: 5 },
        relative_effort: { status: "not_evaluated" },
      },
      intensity_assessment: { position: "unknown", confidence: "none" },
      historical_comparison: {
        status: "insufficient", reference_count: 0, window_days: 90,
        pace_at_comparable_hr: { reference_count: 0, hr_tolerance_bpm: 5 },
        hr_at_comparable_pace: { reference_count: 0, pace_tolerance_sec_per_km: 15 },
        v2_similar_reference: { available: false, sample_count: 0, workout_ids: [] },
      },
      performance_trend: { status: "insufficient_data", confidence: "none" },
      prescription_assessment: { status: "unavailable" },
      coach_assessment: {
        language,
        diagnosis: { code: "diagnosis.intervals", text: "Private deterministic diagnosis.", evidence: {}, source_paths: [] },
        evidence: [], limitations: [], advice: null,
      },
      ...updates,
    },
  };
}

function setAccess({ loading = false, allowed = true, plan = "PREMIUM" } = {}) {
  useSubscription.mockReturnValue({
    loading, plan,
    hasFeature: jest.fn((feature) => feature === "coach_workout_analysis" && allowed),
  });
}

function mockRequests({ analysis = makeAnalysis(), workoutPayload = workout, intelligence, rejectV3 = false, v3Request, v2Request, workoutRequest } = {}) {
  axios.get.mockImplementation((url, options) => {
    const parsed = new URL(url, "http://localhost");
    const id = parsed.pathname.split("/").pop();
    const language = parsed.searchParams.get("language") || "en";
    if (parsed.pathname.includes("/coach/workout-intelligence/")) {
      if (v3Request) return v3Request({ id, language, options });
      return rejectV3
        ? Promise.reject(Object.assign(new Error("Private upstream diagnostics must not be exposed."), { response: { status: 500 } }))
        : Promise.resolve({ data: intelligence === undefined ? makeIntelligence(language) : intelligence });
    }
    if (parsed.pathname.includes("/coach/workout-analysis/")) {
      if (v2Request) return v2Request({ id, language, options });
      return Promise.resolve({ data: { ...analysis, workout: { ...analysis.workout, id } } });
    }
    if (parsed.pathname.includes("/workouts/")) {
      if (workoutRequest) return workoutRequest({ id, language, options });
      return Promise.resolve({ data: { ...workoutPayload, id } });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
}

function Controls({ nextRoute }) {
  const { setLang } = useLanguage();
  return <>
    <button onClick={() => setLang("es")}>Switch test language</button>
    <Link to={nextRoute}>Next test workout</Link>
  </>;
}

function renderPage(route, path, Page, language = "en") {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  window.localStorage.setItem("runindex_unit_system", "metric");
  const tree = () => (
    <LanguageProvider>
      <UnitProvider>
        <MemoryRouter initialEntries={[route]}>
          <Controls nextRoute={route.replace("w1", "w2")} />
          <Routes><Route path={path} element={<Page />} /></Routes>
        </MemoryRouter>
      </UnitProvider>
    </LanguageProvider>
  );
  const result = render(tree());
  return { ...result, refresh: () => result.rerender(tree()) };
}

function expectNoLegacyNarrative() {
  ["coach-language", "session-synthesis", "synthesis-abstention", "meaning-text", "advice-text", "analysis-fallback"]
    .forEach((id) => expect(screen.queryByTestId(id)).not.toBeInTheDocument());
  [legacyText, legacyMeaning, legacyAdvice, legacySynthesis]
    .forEach((text) => expect(screen.queryByText(text)).not.toBeInTheDocument());
}

function expectIndependentRequests(id = "w1", language = "en") {
  const urls = axios.get.mock.calls.map(([url]) => url);
  expect(urls.filter((url) => url.includes(`/coach/workout-intelligence/${id}?language=${language}`))).toHaveLength(1);
  expect(urls.filter((url) => url.includes(`/coach/workout-analysis/${id}?language=${language}`))).toHaveLength(1);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  jest.resetAllMocks();
  window.localStorage.clear();
  setAccess();
});

describe.each(pages)("%s narrative V3 integration", (_, route, path, Page) => {
  test.each(languages)("renders the untouched %s narrative above collapsible measured evidence", async (language) => {
    const intelligence = makeIntelligence(language);
    const original = JSON.stringify(intelligence);
    const analysis = makeAnalysis();
    analysis.session_synthesis = {
      version: "v2", status: "available",
      primary: {
        code: "synthesis.execution", text: legacySynthesis, evidence: { count: 6 },
        source_paths: ["phase_analysis.efforts"], replaces_factual_codes: [],
      },
      supporting: [], limitations: [], abstention: null,
    };
    mockRequests({ analysis, intelligence });
    renderPage(route, path, Page, language);

    const narrative = await screen.findByTestId("narrative-coach");
    expect(within(narrative).getByRole("heading", { name: copy[language].headline })).toBeVisible();
    expect(within(narrative).getByText(copy[language].analysis, { exact: true })).toBeVisible();
    expect(within(narrative).getByText(copy[language].interpretation, { exact: true })).toBeVisible();
    expect(screen.getAllByText(copy[language].headline, { exact: true })).toHaveLength(1);
    expectNoLegacyNarrative();
    expect(narrative).not.toHaveTextContent(/deterministic_fallback|llm_validated|evidence_refs|session_classification\.evidence/);
    expect(narrative).not.toHaveTextContent("Private deterministic diagnosis.");
    expect(narrative).not.toHaveTextContent(/recommendation|recommandation|recomendación/i);
    expect(screen.queryByTestId("narrative-recommendation")).not.toBeInTheDocument();
    expect(narrative.querySelector("ul")).toBeNull();

    const evidence = screen.getByTestId("workout-evidence");
    expect(evidence).toHaveTextContent("6");
    expect(evidence).toHaveTextContent("5");
    expect(evidence).not.toHaveTextContent(/6[,.]6|standard deviation|Écart-type|Desviación estándar/);
    expect(narrative.compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const phases = screen.getByTestId("structured-phase-analysis");
    const phaseDetails = phases.closest("details");
    expect(phaseDetails).not.toBeNull();
    expect(phaseDetails).not.toHaveAttribute("open");
    const phaseSummary = phaseDetails.querySelector("summary");
    expect(phaseSummary).toHaveTextContent(/\S/);
    fireEvent.click(phaseSummary);
    expect(phaseDetails).toHaveAttribute("open");
    expect(within(phases).getAllByTestId("phase-effort-row")).toHaveLength(6);
    expect(within(phases).getAllByTestId("phase-recovery-row")).toHaveLength(5);
    expect(within(phases).getByTestId("effort-regularity"))
      .toHaveTextContent(language === "en" ? "6.6 s/km" : "6,6 s/km");
    expect(within(phases).getByTestId("effort-regularity"))
      .toHaveTextContent(translations[language].workoutNarrative.regularity);

    const splits = screen.getByTestId("kilometer-splits");
    expect(splits.tagName).toBe("DETAILS");
    expect(splits).not.toHaveAttribute("open");
    fireEvent.click(splits.querySelector("summary"));
    expect(splits).toHaveAttribute("open");
    expect(within(splits).getAllByTestId("kilometer-split-row")).toHaveLength(2);
    expect(screen.getByTestId("ask-coach-btn")).toBeInTheDocument();
    expect(JSON.stringify(intelligence)).toBe(original);
    expectIndependentRequests("w1", language);
  });

  test.each(languages)("does not invent interval regularity when unavailable in %s", async (language) => {
    mockRequests({ analysis: makeAnalysis(false) });
    renderPage(route, path, Page, language);
    await screen.findByTestId("narrative-coach");
    const evidence = screen.getByTestId("workout-evidence");
    expect(evidence).toHaveTextContent("6");
    expect(evidence).toHaveTextContent("5");
    expect(evidence).not.toHaveTextContent(/6[,.]6/);
    expect(evidence).not.toHaveTextContent(/\b0(?:[,.]0)?\s*s\/km/);
    expect(screen.queryByTestId("effort-regularity")).not.toBeInTheDocument();
  });

  test.each(languages.flatMap((language) => [null, NaN, Infinity, -1, undefined].map((value) => [language, value])))("does not display invalid %s regularity %s as a recorded measurement", async (language, dispersion) => {
    const analysis = makeAnalysis();
    analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km = dispersion;
    mockRequests({ analysis });
    renderPage(route, path, Page, language);
    await screen.findByTestId("narrative-coach");
    expect(screen.getByTestId("workout-evidence"))
      .not.toHaveTextContent(translations[language].workoutNarrative.regularity);
    expect(screen.queryByTestId("effort-regularity")).not.toBeInTheDocument();
  });

  test("preserves a recorded zero dispersion instead of treating it as missing", async () => {
    const analysis = makeAnalysis();
    analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km = 0;
    mockRequests({ analysis });
    renderPage(route, path, Page);
    await screen.findByTestId("narrative-coach");
    expect(screen.getByTestId("workout-evidence")).not.toHaveTextContent("0 s/km");
    expect(screen.getByTestId("effort-regularity")).toHaveTextContent("0 s/km");
  });

  test.each(languages)("preserves probable easy classification without claiming a physiological zone in %s", async (language) => {
    mockRequests({ intelligence: makeIntelligence(language, {
      session_classification: {
        type: "easy_run_probable", confidence: "medium", decision_tier: "individual_history",
        evidence: {}, relative_effort: { status: "used", relative_position: "low", reference_count: 8 },
      },
    }) });
    renderPage(route, path, Page, language);
    await screen.findByTestId("narrative-coach");
    const evidence = screen.getByTestId("workout-evidence");
    expect(evidence).toHaveTextContent(copy[language].probable);
    expect(evidence).toHaveTextContent(translations[language].workoutNarrative.easy_run_probable);
    expect(evidence).not.toHaveTextContent(/\bZ[1-5]\b|below_LT1|between_LT1_LT2|above_LT2|easy_run_probable/);
  });

  test.each(languages)("shows honest unknown classification in %s", async (language) => {
    mockRequests({ intelligence: makeIntelligence(language, {
      session_classification: {
        type: "unknown", confidence: "none", evidence: {}, relative_effort: { status: "not_evaluated" },
      },
    }) });
    renderPage(route, path, Page, language);
    await screen.findByTestId("narrative-coach");
    const evidence = screen.getByTestId("workout-evidence");
    expect(evidence).toHaveTextContent(copy[language].unknown);
    expect(evidence).toHaveTextContent(translations[language].workoutNarrative.unknown);
    expect(evidence).not.toHaveTextContent(/\bZ[1-5]\b|easy_run_probable/);
  });

  test.each(languages)("does not offer an empty details disclosure for an unknown treadmill workout in %s", async (language) => {
    const analysis = makeAnalysis();
    analysis.phase_analysis = { available: false, phases: [], efforts: [], recoveries: [] };
    analysis.evidence.has_splits = false;
    const intelligence = makeIntelligence(language, {
      session_classification: {
        type: "unknown", confidence: "none", evidence: {}, relative_effort: { status: "not_evaluated" },
      },
    });
    intelligence.narrative_coach_v3.headline = translations[language].workoutNarrative.unknown;
    intelligence.narrative_coach_v3.analysis = copy[language].unknownAnalysis;
    intelligence.narrative_coach_v3.interpretation = copy[language].unknownInterpretation;
    mockRequests({
      analysis, intelligence,
      workoutPayload: { ...workout, name: "Treadmill Run", km_splits: [] },
    });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("narrative-coach")).toBeVisible();
    expect(screen.getByTestId("workout-evidence"))
      .toHaveTextContent(translations[language].workoutNarrative.unknown);
    expect(screen.queryByTestId("workout-analysis-details")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kilometer-splits")).not.toBeInTheDocument();
    expectNoLegacyNarrative();
  });

  test.each(languages)("distinguishes a reliable performance trend from a single observation in %s", async (language) => {
    mockRequests({ intelligence: makeIntelligence(language, {
      performance_trend: {
        status: "probable_improvement", confidence: "high", observation_count: 8,
        span_days: 42, earlier_median_pace_min_km: 6.2, later_median_pace_min_km: 6,
        median_change_sec_per_km: -12, variation_confirmed: true,
      },
    }) });
    renderPage(route, path, Page, language);
    await screen.findByTestId("narrative-coach");
    expect(screen.getByTestId("workout-evidence")).toHaveTextContent(copy[language].improvement);
    expect(screen.getByTestId("workout-evidence")).toHaveTextContent(translations[language].workoutNarrative.probable_improvement);
    expect(screen.getByTestId("workout-evidence")).not.toHaveTextContent("probable_improvement");
  });

  test.each(languages)("does not fabricate progress from insufficient history in %s", async (language) => {
    mockRequests();
    renderPage(route, path, Page, language);
    await screen.findByTestId("narrative-coach");
    const evidence = screen.getByTestId("workout-evidence");
    expect(evidence).toHaveTextContent(copy[language].insufficient);
    expect(evidence).toHaveTextContent(translations[language].workoutNarrative.insufficientHistory);
    expect(evidence).not.toHaveTextContent(copy[language].improvement);
    expect(evidence).not.toHaveTextContent(/insufficient_data|NaN|undefined/);
  });

  test("does not promote a low-confidence trend to reliable progress", async () => {
    mockRequests({ intelligence: makeIntelligence("en", {
      performance_trend: { status: "probable_improvement", confidence: "low" },
    }) });
    renderPage(route, path, Page);
    await screen.findByTestId("narrative-coach");
    expect(screen.getByTestId("workout-evidence"))
      .not.toHaveTextContent(translations.en.workoutNarrative.probable_improvement);
  });

  test.each(languages)("retains the V1 fallback when the %s V3 response has no narrative", async (language) => {
    const intelligence = makeIntelligence(language);
    delete intelligence.narrative_coach_v3;
    mockRequests({ intelligence });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("coach-primary")).toHaveTextContent(legacyText);
    await waitFor(() => expectIndependentRequests("w1", language));
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
    expect(screen.queryByText("Private deterministic diagnosis.")).not.toBeInTheDocument();
    expect(screen.getByTestId("kilometer-splits")).toBeInTheDocument();
  });

  test.each([
    ["null narrative", null],
    ["wrong language", { language: "fr" }],
    ["no generation", { generation_mode: "none" }],
    ["blank headline", { headline: " " }],
    ["missing analysis", { analysis: "" }],
    ["missing interpretation", { interpretation: "" }],
  ])("retains V1 when V3 has %s", async (_, update) => {
    const intelligence = makeIntelligence();
    intelligence.narrative_coach_v3 = update === null
      ? null : { ...intelligence.narrative_coach_v3, ...update };
    mockRequests({ intelligence });
    renderPage(route, path, Page);
    expect(await screen.findByTestId("coach-primary")).toHaveTextContent(legacyText);
    await waitFor(() => expectIndependentRequests());
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
  });

  test.each(languages)("keeps the V1 fallback and a discreet localized status after a V3 error in %s", async (language) => {
    mockRequests({ rejectV3: true });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("coach-primary")).toHaveTextContent(legacyText);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(translations[language].workoutNarrative.unavailable);
    expect(status).not.toHaveTextContent(/Private upstream|Error:|workout-intelligence|HTTP/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
    expect(screen.getByTestId("structured-phase-analysis")).toBeInTheDocument();
    expectIndependentRequests("w1", language);
  });

  test.each([
    ["FREE", { allowed: false, plan: "FREE" }],
    ["pending subscription", { loading: true, allowed: true }],
  ])("never starts the new API request with %s access", async (_, access) => {
    setAccess(access);
    mockRequests();
    renderPage(route, path, Page);
    await act(async () => {});
    expect(axios.get.mock.calls.some(([url]) => url.includes("/coach/workout-intelligence/"))).toBe(false);
    expect(axios.get.mock.calls.some(([url]) => url.includes("/coach/workout-analysis/"))).toBe(false);
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workout-evidence")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
  });

  test.each(["TRIAL", "PREMIUM"])("uses feature entitlement rather than a plan-name restriction for %s", async (plan) => {
    setAccess({ plan, allowed: true });
    mockRequests();
    renderPage(route, path, Page);
    expect(await screen.findByTestId("narrative-coach")).toBeInTheDocument();
    expect(useSubscription().hasFeature).toHaveBeenCalledWith("coach_workout_analysis");
    expectIndependentRequests();
  });

  test.each(languages)("keeps only factual V2 evidence and a local %s placeholder while V3 is pending", async (language) => {
    const pending = deferred();
    mockRequests({ v3Request: () => pending.promise });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("coach-pending")).toHaveTextContent(translations[language].workoutNarrative.pending);
    expectNoLegacyNarrative();
    expect(screen.queryByText("Recorded session.")).not.toBeInTheDocument();
    expect(screen.getByTestId("structured-phase-analysis")).toBeInTheDocument();
    expect(screen.getAllByText(/150 bpm/).length).toBeGreaterThan(0);
    expectIndependentRequests("w1", language);
    await act(async () => { pending.resolve({ data: makeIntelligence(language) }); });
    expect(await screen.findByTestId("narrative-coach")).toBeInTheDocument();
    expectNoLegacyNarrative();
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
  });

  test("ignores a late response for a previous workout route", async () => {
    const stale = deferred();
    const current = makeIntelligence();
    current.workout_id = "w2";
    current.workout_intelligence_v3.workout_id = "w2";
    current.narrative_coach_v3.headline = "Current workout narrative.";
    mockRequests({ v3Request: ({ id }) => (
      id === "w1" ? stale.promise : Promise.resolve({ data: current })
    ) });
    renderPage(route, path, Page);
    await waitFor(() => expectIndependentRequests());
    fireEvent.click(screen.getByRole("link", { name: "Next test workout" }));
    expect(await screen.findByRole("heading", { name: "Current workout narrative." })).toBeVisible();
    await act(async () => { stale.resolve({ data: makeIntelligence() }); });
    expect(screen.getByTestId("narrative-coach")).toHaveTextContent("Current workout narrative.");
    expect(screen.queryByText(copy.en.headline)).not.toBeInTheDocument();
    expectIndependentRequests("w2");
  });

  test("ignores a late narrative in the previous language", async () => {
    const stale = deferred();
    mockRequests({ v3Request: ({ language }) => (
      language === "en" ? stale.promise : Promise.resolve({ data: makeIntelligence(language) })
    ) });
    renderPage(route, path, Page);
    await waitFor(() => expectIndependentRequests());
    fireEvent.click(screen.getByRole("button", { name: "Switch test language" }));
    expect(await screen.findByRole("heading", { name: copy.es.headline })).toBeVisible();
    await act(async () => { stale.resolve({ data: makeIntelligence("en") }); });
    expect(screen.getByTestId("narrative-coach")).toHaveTextContent(copy.es.headline);
    expect(screen.queryByText(copy.en.headline)).not.toBeInTheDocument();
    expectIndependentRequests("w1", "es");
  });

  test.each(languages)("keeps backend MAD narrative distinct from the detailed standard deviation in %s", async (language) => {
    const intelligence = makeIntelligence(language);
    const mad = language === "en" ? "MAD 6.6 s/km" : "MAD 6,6 s/km";
    intelligence.narrative_coach_v3.analysis = `${copy[language].analysis} ${mad}`;
    const analysis = makeAnalysis();
    Object.assign(analysis.phase_analysis.effort_regularity, {
      pace_dispersion_sec_per_km: 7.7, pace_sample_count: 4,
      comparable_effort_count: 4, effort_count: 6, partial_comparison: true,
    });
    mockRequests({ intelligence, analysis });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("narrative-coach")).toHaveTextContent(mad);
    expect(screen.getByTestId("workout-evidence")).not.toHaveTextContent(/6[,.]6|7[,.]7/);
    const details = screen.getByTestId("workout-analysis-details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(details.querySelector("summary"));
    const deviation = within(details).getByTestId("effort-regularity");
    expect(deviation).toBeVisible();
    expect(deviation).toHaveTextContent(translations[language].workoutNarrative.regularity);
    expect(deviation).toHaveTextContent(language === "en" ? "7.7 s/km" : "7,7 s/km");
    expect(deviation).toHaveTextContent("4/6");
    expect(deviation).toHaveTextContent(translations[language].workoutDetailExtended.partialEffortComparison);
    expect(screen.getAllByText(/7[,.]7 s\/km/)).toHaveLength(1);
    expectNoLegacyNarrative();
  });

  test.each(languages)("renders valid %s V3 and factual workout before slow V2", async (language) => {
    const pending = deferred();
    mockRequests({ v2Request: () => pending.promise });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("narrative-coach")).toBeVisible();
    expect(screen.getByText("Morning Run")).toBeVisible();
    expect(screen.getAllByText(/150 bpm/).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
    expectNoLegacyNarrative();
    expectIndependentRequests("w1", language);
    await act(async () => { pending.resolve({ data: makeAnalysis() }); });
    expect(screen.getByTestId("narrative-coach")).toBeVisible();
    expect(screen.getByTestId("structured-phase-analysis").closest("details")).toBeInTheDocument();
    expectNoLegacyNarrative();
  });

  test("shows factual workout and a local Coach placeholder while both analysis requests are pending", async () => {
    const v2 = deferred();
    const v3 = deferred();
    mockRequests({ v2Request: () => v2.promise, v3Request: () => v3.promise });
    renderPage(route, path, Page);
    expect(await screen.findByText("Morning Run")).toBeVisible();
    expect(screen.getByTestId("coach-pending")).toBeVisible();
    expect(screen.getAllByText(/150 bpm/).length).toBeGreaterThan(0);
    expectNoLegacyNarrative();
    await act(async () => {
      v2.resolve({ data: makeAnalysis() });
      v3.resolve({ data: makeIntelligence() });
    });
    expect(screen.getByTestId("narrative-coach")).toBeVisible();
  });

  test("does not declare missing factual data while its request is pending after analysis errors", async () => {
    const pendingWorkout = deferred();
    mockRequests({
      rejectV3: true, v2Request: () => Promise.reject(new Error("V2 unavailable")),
      workoutRequest: () => pendingWorkout.promise,
    });
    renderPage(route, path, Page);
    await act(async () => {});
    expect(screen.queryByTestId("analysis-not-found")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workout-not-found")).not.toBeInTheDocument();
    await act(async () => { pendingWorkout.resolve({ data: workout }); });
    expect(screen.getByText("Morning Run")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(translations.en.workoutNarrative.unavailable);
  });

  test.each(languages.flatMap((language) => ["absent", "error"].map((outcome) => [language, outcome])))(
    "does not show a V2 load error before V2 finishes after %s V3 is terminal %s",
    async (language, outcome) => {
      const pendingV2 = deferred();
      mockRequests({ intelligence: {}, rejectV3: outcome === "error", v2Request: () => pendingV2.promise });
      renderPage(route, path, Page, language);
      expect(await screen.findByText("Morning Run")).toBeVisible();
      await waitFor(() => expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument());
      expect(screen.queryByText(translations[language].workoutDetailExtended.analysisLoadError)).not.toBeInTheDocument();
      expect(screen.queryByTestId("analysis-not-found")).not.toBeInTheDocument();
      expect(screen.getAllByText(/150 bpm/).length).toBeGreaterThan(0);
      expectNoLegacyNarrative();
      await act(async () => { pendingV2.reject(new Error("V2 now terminal unavailable")); });
      if (Page !== SessionDetail) {
        expect(screen.getByText(translations[language].workoutDetailExtended.analysisLoadError)).toBeVisible();
      }
      expect(screen.getByText("Morning Run")).toBeVisible();
      expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
    },
  );

  test.each(languages)("does not flash older conclusions during a 2500ms %s V3 request", async (language) => {
    jest.useFakeTimers();
    try {
      mockRequests({ v3Request: () => new Promise((resolve) => {
        setTimeout(() => resolve({ data: makeIntelligence(language) }), 2500);
      }) });
      renderPage(route, path, Page, language);
      await act(async () => {});
      expect(screen.getByTestId("coach-pending")).toBeVisible();
      expect(screen.getByText("Morning Run")).toBeVisible();
      expectNoLegacyNarrative();
      await act(async () => { jest.advanceTimersByTime(2499); });
      expect(screen.getByTestId("coach-pending")).toBeVisible();
      expectNoLegacyNarrative();
      await act(async () => { jest.advanceTimersByTime(1); });
      expect(screen.getByTestId("narrative-coach")).toBeVisible();
      expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
      expectNoLegacyNarrative();
      expectIndependentRequests("w1", language);
    } finally {
      jest.useRealTimers();
    }
  });

  test.each(languages)("omits missing and nonfinite %s factual metrics without inventing zeros", async (language) => {
    const analysis = makeAnalysis();
    analysis.pacing = {};
    analysis.physiology = {};
    analysis.comparison = {};
    analysis.phase_analysis = { available: false };
    mockRequests({
      analysis,
      workoutPayload: { ...workout, distance_km: null, duration_minutes: undefined,
        avg_pace_min_km: NaN, avg_speed_kmh: Infinity, avg_heart_rate: null, km_splits: [] },
    });
    const { container } = renderPage(route, path, Page, language);
    expect(await screen.findByTestId("narrative-coach")).toBeVisible();
    expect(container).not.toHaveTextContent(/NaN|Infinity|undefined|0 bpm|0 s\/km/);
    expect(screen.queryByTestId("workout-analysis-details")).not.toBeInTheDocument();
    expectNoLegacyNarrative();
  });

  test.each(languages)("does not flash a legacy header summary with missing %s metrics while V3 is pending", async (language) => {
    const pending = deferred();
    const analysis = makeAnalysis();
    delete analysis.coach_language;
    analysis.summary.text = "Legacy header summary must stay hidden.";
    analysis.pacing = {};
    analysis.physiology = {};
    analysis.comparison = {};
    analysis.phase_analysis = { available: false };
    mockRequests({
      analysis, v3Request: () => pending.promise,
      workoutPayload: { ...workout, distance_km: null, duration_minutes: undefined,
        avg_pace_min_km: NaN, avg_speed_kmh: Infinity, avg_heart_rate: null, km_splits: [] },
    });
    const { container } = renderPage(route, path, Page, language);
    expect(await screen.findByTestId("coach-pending")).toBeVisible();
    expect(screen.getByText("Morning Run")).toBeVisible();
    expect(screen.queryByTestId("header-context")).not.toBeInTheDocument();
    expect(screen.queryByText(analysis.summary.text)).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent(/NaN|Infinity|undefined|0 bpm|0 s\/km/);
    expectNoLegacyNarrative();
    await act(async () => { pending.resolve({ data: makeIntelligence(language) }); });
    expect(screen.getByTestId("narrative-coach")).toBeVisible();
    expect(screen.queryByText(analysis.summary.text)).not.toBeInTheDocument();
    expectNoLegacyNarrative();
  });

  test("aborts every owned request on unmount and ignores late results", async () => {
    const pending = deferred();
    mockRequests({
      v3Request: () => pending.promise, v2Request: () => pending.promise,
      workoutRequest: () => pending.promise,
    });
    const { unmount } = renderPage(route, path, Page);
    const signals = axios.get.mock.calls.map(([, options]) => options.signal);
    expect(signals).toHaveLength(3);
    unmount();
    signals.forEach((signal) => expect(signal.aborted).toBe(true));
    await act(async () => { pending.resolve({ data: makeIntelligence() }); });
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
  });

  test("uses a finite real HTTP timeout and terminal error fallback", async () => {
    let fail;
    mockRequests({ v3Request: ({ options }) => {
      expect(options.timeout).toBe(15000);
      expect(options.signal).toBeInstanceOf(AbortSignal);
      return new Promise((resolve, reject) => { fail = reject; });
    } });
    renderPage(route, path, Page);
    await screen.findByTestId("coach-pending");
    await act(async () => { fail(Object.assign(new Error("timeout"), { code: "ECONNABORTED" })); });
    expect(screen.getByTestId("coach-primary")).toHaveTextContent(legacyText);
    expect(screen.getByRole("status")).toHaveTextContent(translations.en.workoutNarrative.unavailable);
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
  });

  test.each(languages.flatMap((language) => ["absent", "incomplete", "HTTP500"].map((outcome) => [language, outcome])))(
    "waits for the %s V3 terminal %s response before revealing legacy fallback",
    async (language, outcome) => {
      const pending = deferred();
      mockRequests({ v3Request: () => pending.promise });
      renderPage(route, path, Page, language);
      await screen.findByTestId("coach-pending");
      expectNoLegacyNarrative();
      await act(async () => {
        if (outcome === "HTTP500") {
          pending.reject(Object.assign(new Error("private"), { response: { status: 500 } }));
        } else if (outcome === "absent") {
          pending.resolve({ data: null });
        } else {
          const incomplete = makeIntelligence(language);
          incomplete.narrative_coach_v3.analysis = "";
          pending.resolve({ data: incomplete });
        }
      });
      expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
      expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
      expect(screen.getAllByText(legacyText)).toHaveLength(1);
      if (outcome === "HTTP500") {
        expect(screen.getByRole("status")).toHaveTextContent(translations[language].workoutNarrative.unavailable);
      } else {
        expect(screen.queryByRole("status")).not.toBeInTheDocument();
      }
      expectIndependentRequests("w1", language);
    },
  );

  test.each(languages)("does not mislabel a first-to-last pace change as standard deviation in %s", async (language) => {
    const analysis = makeAnalysis();
    analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km = null;
    analysis.phase_analysis.effort_regularity.first_to_last_pace_change_sec_per_km = 12;
    mockRequests({ analysis });
    renderPage(route, path, Page, language);
    await screen.findByTestId("narrative-coach");
    const details = screen.getByTestId("workout-analysis-details");
    fireEvent.click(details.querySelector("summary"));
    expect(screen.getByTestId("effort-regularity")).toHaveTextContent(translations[language].workoutDetailExtended.firstToLastPace);
    expect(screen.getByTestId("effort-regularity")).toHaveTextContent("+12 s/km");
    expect(screen.getByTestId("effort-regularity")).not.toHaveTextContent(translations[language].workoutNarrative.regularity);
  });

  test("revocation hides completed Premium data and restoration starts a fresh scope", async () => {
    mockRequests();
    const { refresh } = renderPage(route, path, Page);
    await screen.findByTestId("narrative-coach");
    const previousSignals = axios.get.mock.calls.filter(([url]) => url.includes("/coach/")).map(([, options]) => options.signal);
    setAccess({ allowed: false, plan: "FREE" });
    refresh();
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
    previousSignals.forEach((signal) => expect(signal.aborted).toBe(true));

    const current = deferred();
    mockRequests({ v3Request: () => current.promise, v2Request: () => current.promise });
    setAccess();
    refresh();
    await screen.findByTestId("coach-pending");
    expectNoLegacyNarrative();
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    await act(async () => { current.resolve({ data: makeIntelligence() }); });
    expect(screen.getByTestId("narrative-coach")).toBeVisible();
    expect(axios.get.mock.calls.filter(([url]) => url.includes("/coach/workout-intelligence/"))).toHaveLength(2);
  });

  test("ignores stale V2 and V3 results through a rapid revoke/restore cycle", async () => {
    const staleV2 = deferred();
    const staleV3 = deferred();
    mockRequests({ v2Request: () => staleV2.promise, v3Request: () => staleV3.promise });
    const { refresh } = renderPage(route, path, Page);
    await screen.findByTestId("coach-pending");
    const oldSignals = axios.get.mock.calls.filter(([url]) => url.includes("/coach/")).map(([, options]) => options.signal);
    setAccess({ allowed: false, plan: "FREE" });
    refresh();
    const freshV2 = deferred();
    const freshV3 = deferred();
    mockRequests({ v2Request: () => freshV2.promise, v3Request: () => freshV3.promise });
    setAccess();
    refresh();
    await screen.findByTestId("coach-pending");
    oldSignals.forEach((signal) => expect(signal.aborted).toBe(true));
    await act(async () => {
      staleV2.resolve({ data: makeAnalysis() });
      staleV3.resolve({ data: makeIntelligence() });
    });
    expect(screen.getByTestId("coach-pending")).toBeVisible();
    expect(screen.queryByTestId("narrative-coach")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expectNoLegacyNarrative();
    await act(async () => { freshV3.resolve({ data: {} }); });
    expect(screen.queryByTestId("coach-primary")).not.toBeInTheDocument();
    await act(async () => { freshV2.resolve({ data: makeAnalysis() }); });
    expect(screen.getByTestId("coach-primary")).toHaveTextContent(legacyText);
  });

  test("aborts stale session and V2 route requests without replacing current facts or fallback", async () => {
    const staleV2 = deferred();
    const staleWorkout = deferred();
    mockRequests({
      intelligence: {},
      v2Request: ({ id }) => id === "w1" ? staleV2.promise
        : Promise.resolve({ data: { ...makeAnalysis(), workout: { ...makeAnalysis().workout, id, name: "Current workout." }, coach_language: {
          version: "v1", conclusions: [{ ...makeAnalysis().coach_language.conclusions[0], text: "Current fallback." }],
        } } }),
      workoutRequest: ({ id }) => id === "w1" ? staleWorkout.promise
        : Promise.resolve({ data: { ...workout, id, name: "Current workout." } }),
    });
    renderPage(route, path, Page);
    const oldSignals = axios.get.mock.calls.map(([, options]) => options.signal);
    fireEvent.click(screen.getByRole("link", { name: "Next test workout" }));
    expect(await screen.findByText("Current workout.")).toBeVisible();
    expect(await screen.findByTestId("coach-primary")).toHaveTextContent("Current fallback.");
    oldSignals.forEach((signal) => expect(signal.aborted).toBe(true));
    await act(async () => {
      staleV2.resolve({ data: makeAnalysis() });
      staleWorkout.resolve({ data: workout });
    });
    expect(screen.getByTestId("coach-primary")).toHaveTextContent("Current fallback.");
    expect(screen.queryByText("Morning Run")).not.toBeInTheDocument();
    expect(screen.queryByText(legacyText)).not.toBeInTheDocument();
  });

  test("aborts stale V2 language requests and keeps localized terminal fallback", async () => {
    const stale = deferred();
    mockRequests({
      intelligence: {},
      v2Request: ({ language }) => language === "en" ? stale.promise
        : Promise.resolve({ data: { ...makeAnalysis(), coach_language: {
          version: "v1", conclusions: [{ ...makeAnalysis().coach_language.conclusions[0], text: "Conclusión actual." }],
        } } }),
    });
    renderPage(route, path, Page);
    await waitFor(() => expectIndependentRequests());
    const oldSignal = axios.get.mock.calls.find(([url]) => url.includes("/coach/workout-analysis/"))[1].signal;
    fireEvent.click(screen.getByRole("button", { name: "Switch test language" }));
    expect(await screen.findByTestId("coach-primary")).toHaveTextContent("Conclusión actual.");
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { stale.resolve({ data: makeAnalysis() }); });
    expect(screen.getByTestId("coach-primary")).toHaveTextContent("Conclusión actual.");
    expect(screen.queryByText(legacyText)).not.toBeInTheDocument();
  });
});

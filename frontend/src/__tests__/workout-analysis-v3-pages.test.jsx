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

// C416: the long Narrative V3 prose never renders on the session page; interpretation lives in the Coach chat.
function expectNoNarrativeProse() {
  languages.forEach((language) => ["headline", "analysis", "interpretation"].forEach((field) =>
    expect(screen.queryByText(copy[language][field], { exact: true })).not.toBeInTheDocument()));
  ["narrative-coach", "narrative-recommendation", "coach-session-comment", "narrative-deterministic-facts"]
    .forEach((id) => expect(screen.queryByTestId(id)).not.toBeInTheDocument());
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

    const narrative = await screen.findByTestId("workout-facts");
    expect(screen.queryByRole("heading", { name: copy[language].headline })).not.toBeInTheDocument();
    if (Page === WorkoutDetail) expect(screen.getByText(legacySynthesis)).toBeVisible();
    expectNoNarrativeProse();
    expect(narrative).not.toHaveTextContent(/deterministic_fallback|llm_validated|evidence_refs|session_classification\.evidence/);
    expect(narrative).not.toHaveTextContent("Private deterministic diagnosis.");
    expect(narrative).not.toHaveTextContent(/recommendation|recommandation|recomendación/i);
    expect(screen.queryByTestId("narrative-recommendation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workout-limitations")).toBeNull();

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
    await screen.findByTestId("workout-facts");
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
    await screen.findByTestId("workout-facts");
    expect(screen.getByTestId("workout-evidence"))
      .not.toHaveTextContent(translations[language].workoutNarrative.regularity);
    expect(screen.queryByTestId("effort-regularity")).not.toBeInTheDocument();
  });

  test("preserves a recorded zero dispersion instead of treating it as missing", async () => {
    const analysis = makeAnalysis();
    analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km = 0;
    mockRequests({ analysis });
    renderPage(route, path, Page);
    await screen.findByTestId("workout-facts");
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
    await screen.findByTestId("workout-facts");
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
    await screen.findByTestId("workout-facts");
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
    expect(await screen.findByTestId("workout-facts")).toBeVisible();
    expect(screen.getByTestId("workout-evidence"))
      .toHaveTextContent(translations[language].workoutNarrative.unknown);
    expect(screen.queryByTestId("workout-analysis-details")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kilometer-splits")).not.toBeInTheDocument();
    expectNoNarrativeProse();
  });

  test.each(languages)("keeps the multi-session trend off the session sheet in %s", async (language) => {
    mockRequests({ intelligence: makeIntelligence(language, {
      performance_trend: {
        status: "probable_improvement", confidence: "high", observation_count: 8,
        span_days: 42, median_change_sec_per_km: -12, variation_confirmed: true,
      },
    }) });
    renderPage(route, path, Page, language);
    await screen.findByTestId("workout-facts");
    const w = translations[language].workoutNarrative;
    const text = document.body.textContent;
    [w.trend, w.probable_improvement, w.stable, w.possible_decline].forEach((label) => expect(text).not.toContain(label));
    expect(screen.getByTestId("workout-evidence")).not.toHaveTextContent(copy[language].improvement);
  });

  test.each(languages)("does not fabricate progress from insufficient history in %s", async (language) => {
    mockRequests();
    renderPage(route, path, Page, language);
    await screen.findByTestId("workout-facts");
    const evidence = screen.getByTestId("workout-evidence");
    fireEvent.click(screen.getByTestId("workout-analysis-details").querySelector("summary"));
    expect(screen.getByTestId("reference-populations")).toHaveTextContent(translations[language].workoutNarrative.insufficientHistory);
    expect(evidence).not.toHaveTextContent(copy[language].improvement);
    expect(evidence).not.toHaveTextContent(/insufficient_data|NaN|undefined/);
  });

  test.each(languages)("keeps V3 facts and V2 observations when the %s V3 response has no narrative", async (language) => {
    const intelligence = makeIntelligence(language);
    delete intelligence.narrative_coach_v3;
    mockRequests({ intelligence });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("meaning-text")).toHaveTextContent(legacyMeaning);
    await waitFor(() => expectIndependentRequests("w1", language));
    expect(await screen.findByTestId("workout-facts")).toBeInTheDocument();
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
  ])("keeps facts and V2 observations when V3 prose has %s", async (_, update) => {
    const intelligence = makeIntelligence();
    intelligence.narrative_coach_v3 = update === null
      ? null : { ...intelligence.narrative_coach_v3, ...update };
    mockRequests({ intelligence });
    renderPage(route, path, Page);
    expect(await screen.findByTestId("meaning-text")).toHaveTextContent(legacyMeaning);
    await waitFor(() => expectIndependentRequests());
    expect(await screen.findByTestId("workout-facts")).toBeInTheDocument();
  });

  test.each(languages)("keeps the V1 fallback and a discreet localized status after a V3 error in %s", async (language) => {
    mockRequests({ rejectV3: true });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("meaning-text")).toHaveTextContent(legacyMeaning);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(translations[language].workoutNarrative.unavailable);
    expect(status).not.toHaveTextContent(/Private upstream|Error:|workout-intelligence|HTTP/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workout-facts")).not.toBeInTheDocument();
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
    expect(screen.queryByTestId("workout-facts")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workout-evidence")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
  });

  test.each(["TRIAL", "PREMIUM"])("uses feature entitlement rather than a plan-name restriction for %s", async (plan) => {
    setAccess({ plan, allowed: true });
    mockRequests();
    renderPage(route, path, Page);
    expect(await screen.findByTestId("workout-facts")).toBeInTheDocument();
    expect(useSubscription().hasFeature).toHaveBeenCalledWith("coach_workout_analysis");
    expectIndependentRequests();
  });

  test.each(languages)("keeps only factual V2 evidence and a local %s placeholder while V3 is pending", async (language) => {
    const pending = deferred();
    mockRequests({ v3Request: () => pending.promise });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("coach-pending")).toHaveTextContent(translations[language].workoutNarrative.pending);
    expectNoNarrativeProse();
    expect(screen.queryByText("Recorded session.")).not.toBeInTheDocument();
    expect(screen.getByTestId("structured-phase-analysis")).toBeInTheDocument();
    expect(screen.getAllByText(/150 bpm/).length).toBeGreaterThan(0);
    expectIndependentRequests("w1", language);
    await act(async () => { pending.resolve({ data: makeIntelligence(language) }); });
    expect(await screen.findByTestId("workout-facts")).toBeInTheDocument();
    expectNoNarrativeProse();
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
  });

  test("never requests an AI comment when a session opens, even with a stored coach_comment", async () => {
    const intelligence = makeIntelligence();
    intelligence.coach_comment = { status: "generated", language: "en", source: "coach_c396", text: "Stored AI comment." };
    mockRequests({ intelligence });
    renderPage(route, path, Page);
    await screen.findByTestId("workout-facts");
    expect(axios.get.mock.calls.some(([url]) => url.includes("workout-comment"))).toBe(false);
    expect(axios.get.mock.calls.filter(([url]) => url.includes("/coach/workout-intelligence/")).every(([url]) => url.includes("deterministic=true"))).toBe(true);
    expect(axios.post).not.toHaveBeenCalled();
    expect(screen.queryByText("Stored AI comment.")).not.toBeInTheDocument();
    expect(screen.getByTestId("ask-coach-btn")).toBeInTheDocument();
  });

  test("keeps four efforts, three recoveries and limitations of a 4x interval session", async () => {
    const analysis = makeAnalysis();
    const phases = analysis.phase_analysis;
    phases.efforts = phases.efforts.slice(0, 4);
    phases.recoveries = phases.recoveries.slice(0, 3);
    phases.phases = phases.phases.slice(0, 7);
    phases.effort_regularity.effort_count = 4;
    const intelligence = makeIntelligence();
    intelligence.workout_intelligence_v3.session_classification.evidence = { effort_count: 4, recovery_count: 3 };
    intelligence.narrative_coach_v3.limitations = ["Only four recorded efforts."];
    mockRequests({ analysis, intelligence });
    renderPage(route, path, Page);
    const evidence = await screen.findByTestId("workout-evidence");
    expect(evidence).toHaveTextContent("4");
    expect(evidence).toHaveTextContent("3");
    expect(screen.getByTestId("workout-limitations")).toHaveTextContent("Only four recorded efforts.");
    fireEvent.click(screen.getByTestId("workout-analysis-details").querySelector("summary"));
    expect(screen.getAllByTestId("phase-effort-row")).toHaveLength(4);
    expect(screen.getAllByTestId("phase-recovery-row")).toHaveLength(3);
  });

  test("keeps Garmin facts and the comparison population of a continuous run", async () => {
    const analysis = makeAnalysis();
    analysis.phase_analysis = { available: false, phases: [], efforts: [], recoveries: [] };
    const intelligence = makeIntelligence("en", {
      session_classification: { type: "easy_run_probable", confidence: "medium", relative_effort: { status: "not_evaluated" } },
      historical_comparison: {
        status: "available", comparability: "strong", reference_count: 7, window_days: 90,
        pace_at_comparable_hr: { reference_count: 7, pace_difference_sec_per_km: -5 },
        hr_at_comparable_pace: { reference_count: 7, hr_difference_bpm: 2 },
      },
    });
    mockRequests({ analysis, intelligence });
    renderPage(route, path, Page);
    expect(await screen.findByTestId("workout-evidence")).toHaveTextContent(translations.en.workoutNarrative.easy_run_probable);
    expect(document.body.textContent).toMatch(/150/);
    fireEvent.click(screen.getByTestId("workout-analysis-details").querySelector("summary"));
    expect(screen.getByTestId("reference-populations")).toHaveTextContent("7 comparable sessions");
    expect(screen.getByTestId("narrative-comparisons")).toHaveTextContent("5");
  });

  test("ignores a late response for a previous workout route", async () => {
    const stale = deferred();
    const current = makeIntelligence();
    current.workout_id = "w2";
    current.workout_intelligence_v3.workout_id = "w2";
    current.narrative_coach_v3.limitations = ["Current workout limit."];
    mockRequests({ v3Request: ({ id }) => (
      id === "w1" ? stale.promise : Promise.resolve({ data: current })
    ) });
    renderPage(route, path, Page);
    await waitFor(() => expectIndependentRequests());
    fireEvent.click(screen.getByRole("link", { name: "Next test workout" }));
    expect(await screen.findByText("Current workout limit.")).toBeVisible();
    const stalePayload = makeIntelligence();
    stalePayload.narrative_coach_v3.limitations = ["Stale workout limit."];
    await act(async () => { stale.resolve({ data: stalePayload }); });
    expect(screen.getByTestId("workout-facts")).toHaveTextContent("Current workout limit.");
    expect(screen.queryByText("Stale workout limit.")).not.toBeInTheDocument();
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
    expect(await screen.findByText(translations.es.workoutNarrative.structure)).toBeVisible();
    await act(async () => { stale.resolve({ data: makeIntelligence("en") }); });
    expect(screen.getByTestId("workout-facts")).toHaveTextContent(translations.es.workoutNarrative.structure);
    expect(screen.queryByText(translations.en.workoutNarrative.structure)).not.toBeInTheDocument();
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
    expect(await screen.findByTestId("workout-facts")).not.toHaveTextContent("MAD");
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
    expectNoNarrativeProse();
  });

  test.each(languages)("renders valid %s V3 and factual workout before slow V2", async (language) => {
    const pending = deferred();
    mockRequests({ v2Request: () => pending.promise });
    renderPage(route, path, Page, language);
    expect(await screen.findByTestId("workout-facts")).toBeVisible();
    expect(screen.getByText("Morning Run")).toBeVisible();
    expect(screen.getAllByText(/150 bpm/).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
    expectNoNarrativeProse();
    expectIndependentRequests("w1", language);
    await act(async () => { pending.resolve({ data: makeAnalysis() }); });
    expect(screen.getByTestId("workout-facts")).toBeVisible();
    expect(screen.getByTestId("structured-phase-analysis").closest("details")).toBeInTheDocument();
    expectNoNarrativeProse();
  });

  test("shows factual workout and a local Coach placeholder while both analysis requests are pending", async () => {
    const v2 = deferred();
    const v3 = deferred();
    mockRequests({ v2Request: () => v2.promise, v3Request: () => v3.promise });
    renderPage(route, path, Page);
    expect(await screen.findByText("Morning Run")).toBeVisible();
    expect(screen.getByTestId("coach-pending")).toBeVisible();
    expect(screen.getAllByText(/150 bpm/).length).toBeGreaterThan(0);
    expectNoNarrativeProse();
    await act(async () => {
      v2.resolve({ data: makeAnalysis() });
      v3.resolve({ data: makeIntelligence() });
    });
    expect(screen.getByTestId("workout-facts")).toBeVisible();
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
      expectNoNarrativeProse();
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
      expectNoNarrativeProse();
      await act(async () => { jest.advanceTimersByTime(2499); });
      expect(screen.getByTestId("coach-pending")).toBeVisible();
      expectNoNarrativeProse();
      await act(async () => { jest.advanceTimersByTime(1); });
      expect(screen.getByTestId("workout-facts")).toBeVisible();
      expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
      expectNoNarrativeProse();
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
    expect(await screen.findByTestId("workout-facts")).toBeVisible();
    expect(container).not.toHaveTextContent(/NaN|Infinity|undefined|0 bpm|0 s\/km/);
    expect(screen.queryByTestId("workout-analysis-details")).not.toBeInTheDocument();
    expectNoNarrativeProse();
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
    expectNoNarrativeProse();
    await act(async () => { pending.resolve({ data: makeIntelligence(language) }); });
    expect(screen.getByTestId("workout-facts")).toBeVisible();
    expect(screen.queryByText(analysis.summary.text)).not.toBeInTheDocument();
    expectNoNarrativeProse();
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
    expect(screen.queryByTestId("workout-facts")).not.toBeInTheDocument();
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
    expect(screen.getByTestId("meaning-text")).toHaveTextContent(legacyMeaning);
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
      expectNoNarrativeProse();
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
      // C416: facts come from workout_intelligence_v3, so incomplete prose alone keeps them.
      expect(Boolean(screen.queryByTestId("workout-facts"))).toBe(outcome === "incomplete");
      expect(screen.getAllByText(legacyMeaning)).toHaveLength(1);
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
    await screen.findByTestId("workout-facts");
    const details = screen.getByTestId("workout-analysis-details");
    fireEvent.click(details.querySelector("summary"));
    expect(screen.getByTestId("effort-regularity")).toHaveTextContent(translations[language].workoutDetailExtended.firstToLastPace);
    expect(screen.getByTestId("effort-regularity")).toHaveTextContent("+12 s/km");
    expect(screen.getByTestId("effort-regularity")).not.toHaveTextContent(translations[language].workoutNarrative.regularity);
  });

  test("revocation hides completed Premium data and restoration starts a fresh scope", async () => {
    mockRequests();
    const { refresh } = renderPage(route, path, Page);
    await screen.findByTestId("workout-facts");
    const previousSignals = axios.get.mock.calls.filter(([url]) => url.includes("/coach/")).map(([, options]) => options.signal);
    setAccess({ allowed: false, plan: "FREE" });
    refresh();
    expect(screen.queryByTestId("workout-facts")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expect(screen.queryByTestId("coach-pending")).not.toBeInTheDocument();
    previousSignals.forEach((signal) => expect(signal.aborted).toBe(true));

    const current = deferred();
    mockRequests({ v3Request: () => current.promise, v2Request: () => current.promise });
    setAccess();
    refresh();
    await screen.findByTestId("coach-pending");
    expectNoNarrativeProse();
    expect(screen.queryByTestId("workout-facts")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    await act(async () => { current.resolve({ data: makeIntelligence() }); });
    expect(screen.getByTestId("workout-facts")).toBeVisible();
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
    expect(screen.queryByTestId("workout-facts")).not.toBeInTheDocument();
    expect(screen.queryByTestId("structured-phase-analysis")).not.toBeInTheDocument();
    expectNoNarrativeProse();
    await act(async () => { freshV3.resolve({ data: {} }); });
    expect(screen.queryByTestId("meaning-text")).not.toBeInTheDocument();
    await act(async () => { freshV2.resolve({ data: makeAnalysis() }); });
    expect(screen.getByTestId("meaning-text")).toHaveTextContent(legacyMeaning);
  });

  test("aborts stale session and V2 route requests without replacing current facts or fallback", async () => {
    const staleV2 = deferred();
    const staleWorkout = deferred();
    mockRequests({
      intelligence: {},
      v2Request: ({ id }) => id === "w1" ? staleV2.promise
        : Promise.resolve({ data: { ...makeAnalysis(), workout: { ...makeAnalysis().workout, id, name: "Current workout." }, meaning: {
          text: "Current fallback.",
          factual_observations: [{ code: "fact.recorded_hr", placement: "summary", text: "Current fallback.", evidence: { avg_hr: 150 } }],
        } } }),
      workoutRequest: ({ id }) => id === "w1" ? staleWorkout.promise
        : Promise.resolve({ data: { ...workout, id, name: "Current workout." } }),
    });
    renderPage(route, path, Page);
    const oldSignals = axios.get.mock.calls.map(([, options]) => options.signal);
    fireEvent.click(screen.getByRole("link", { name: "Next test workout" }));
    expect(await screen.findByText("Current workout.")).toBeVisible();
    expect(await screen.findByTestId("meaning-text")).toHaveTextContent("Current fallback.");
    oldSignals.forEach((signal) => expect(signal.aborted).toBe(true));
    await act(async () => {
      staleV2.resolve({ data: makeAnalysis() });
      staleWorkout.resolve({ data: workout });
    });
    expect(screen.getByTestId("meaning-text")).toHaveTextContent("Current fallback.");
    expect(screen.queryByText("Morning Run")).not.toBeInTheDocument();
    expect(screen.queryByText(legacyText)).not.toBeInTheDocument();
  });

  test("aborts stale V2 language requests and keeps localized terminal fallback", async () => {
    const stale = deferred();
    mockRequests({
      intelligence: {},
      v2Request: ({ language }) => language === "en" ? stale.promise
        : Promise.resolve({ data: { ...makeAnalysis(), meaning: {
          text: "Conclusión actual.",
          factual_observations: [{ code: "fact.recorded_hr", placement: "summary", text: "Conclusión actual.", evidence: { avg_hr: 150 } }],
        } } }),
    });
    renderPage(route, path, Page);
    await waitFor(() => expectIndependentRequests());
    const oldSignal = axios.get.mock.calls.find(([url]) => url.includes("/coach/workout-analysis/"))[1].signal;
    fireEvent.click(screen.getByRole("button", { name: "Switch test language" }));
    expect(await screen.findByTestId("meaning-text")).toHaveTextContent("Conclusión actual.");
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { stale.resolve({ data: makeAnalysis() }); });
    expect(screen.getByTestId("meaning-text")).toHaveTextContent("Conclusión actual.");
    expect(screen.queryByText(legacyMeaning)).not.toBeInTheDocument();
  });
});

// C417: consolidated WorkoutDetail presentation (markers, one limitation, Coach access, details).
describe("WorkoutDetail C417 consolidation", () => {
  const paceText = "21.4 s/km faster than five earlier sessions. Recorded average pace: 6:06/km, versus 6:27/km for these references.";
  const historyLimitEn = "This difference describes these sessions; it cannot alone establish a change in fitness or judge execution.";
  const traceLimitEn = "Historical comparisons are observational, not proof of a physiological change.";
  const synthesisWith = (limitations = []) => ({
    version: "v2", status: "available",
    primary: {
      code: "coach.history.pace", text: paceText, kind: "observation",
      evidence: { pace_sample_count: 5, pace_difference_sec_per_km: -21.4, baseline_pace_min_km: 6.45, current_pace_min_km: 6.1 },
      source_paths: ["coach_language.conclusions[0]"], replaces_factual_codes: [],
    },
    supporting: [], limitations, abstention: null,
  });
  const continuousIntelligence = (limitations = []) => {
    const intelligence = makeIntelligence("en", {
      session_classification: {
        type: "easy_run_probable", confidence: "medium", evidence: {},
        relative_effort: { status: "used", relative_position: "low", reference_count: 25 },
      },
      historical_comparison: {
        status: "available", comparability: "moderate", reference_count: 3, window_days: 90,
        pace_at_comparable_hr: { reference_count: 0 }, hr_at_comparable_pace: { reference_count: 0 },
      },
    });
    intelligence.narrative_coach_v3.limitations = limitations;
    return intelligence;
  };
  const open = async (analysis, intelligence, language = "en") => {
    mockRequests({ analysis, intelligence });
    renderPage("/workout/w1", "/workout/:id", WorkoutDetail, language);
    await screen.findByTestId("workout-facts");
    await screen.findByTestId("ask-coach-btn");
  };
  const analysisWith = (synthesis) => ({ ...makeAnalysis(), session_synthesis: synthesis });

  test("shows an equivalent V2/V3 limitation once, with both provenances kept", async () => {
    await open(
      analysisWith(synthesisWith([{ code: "synthesis.history_descriptive", text: historyLimitEn, source_paths: ["coach_language.conclusions[0]"] }])),
      continuousIntelligence([traceLimitEn]),
    );
    expect(screen.getByTestId("workout-limitations")).toHaveTextContent(historyLimitEn);
    expect(screen.queryByText(traceLimitEn)).not.toBeInTheDocument();
    expect(screen.queryByTestId("workout-limitations-details")).not.toBeInTheDocument();
    expect(screen.queryByTestId("session-synthesis")).not.toBeInTheDocument();
  });

  test("shows a strictly identical limitation once", async () => {
    await open(analysisWith(synthesisWith([{ code: "x.same", text: "Same limit.", source_paths: [] }])), continuousIntelligence(["Same limit."]));
    expect(screen.getAllByText("Same limit.")).toHaveLength(1);
  });

  test("keeps different limitations: one in the main flow, the rest in the details", async () => {
    await open(
      analysisWith(synthesisWith([{ code: "synthesis.hr_observation", text: "HR limit.", source_paths: [] }])),
      continuousIntelligence(["Different V3 limit."]),
    );
    expect(screen.getByTestId("workout-limitations")).toHaveTextContent("HR limit.");
    const details = screen.getByTestId("workout-analysis-details");
    expect(within(details).getByTestId("workout-limitations-details")).toHaveTextContent("Different V3 limit.");
    expect(screen.getAllByText("HR limit.")).toHaveLength(1);
  });

  test("never repeats the primary observation and keeps it out of any synthesis card", async () => {
    await open(analysisWith(synthesisWith()), continuousIntelligence());
    expect(screen.getAllByText(paceText)).toHaveLength(1);
    expect(screen.getByTestId("workout-evidence")).toHaveTextContent(paceText);
    expect(screen.getAllByTestId("session-marker").length).toBeLessThanOrEqual(3);
    expect(screen.queryByTestId("synthesis-primary")).not.toBeInTheDocument();
  });

  test("places the Coach button before the long technical sections and keeps its URL", async () => {
    await open(analysisWith(synthesisWith()), continuousIntelligence());
    const button = screen.getByTestId("ask-coach-btn");
    expect(screen.getAllByTestId("ask-coach-btn")).toHaveLength(1);
    const details = screen.getByTestId("workout-analysis-details");
    expect(details).not.toHaveAttribute("open");
    expect(button.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByTestId("workout-evidence").compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(details).toContainElement(screen.getByTestId("kilometer-splits"));
  });

  test("keeps reference populations distinct and unchanged in the details", async () => {
    await open(analysisWith(synthesisWith()), continuousIntelligence());
    fireEvent.click(screen.getByTestId("workout-analysis-details").querySelector("summary"));
    const references = screen.getByTestId("reference-populations");
    expect(references).toHaveTextContent("25 reference sessions");
    expect(references).toHaveTextContent("3 comparable sessions");
    expect(references).toHaveTextContent("5 earlier sessions");
    expect(references).toHaveTextContent(translations.en.workoutNarrative.referencesNote);
    expect(references.textContent).not.toMatch(/33|\b8\b/);
  });

  test("excludes interpretations and narrative prose, and never calls the AI on open", async () => {
    const synthesis = synthesisWith();
    synthesis.supporting = [{
      code: "coach.interpretation", text: "Validated interpretation text.", kind: "interpretation",
      evidence: { value: 1 }, source_paths: ["x"], replaces_factual_codes: [],
    }];
    await open(analysisWith(synthesis), continuousIntelligence());
    expect(screen.queryByText("Validated interpretation text.")).not.toBeInTheDocument();
    expectNoNarrativeProse();
    expect(axios.post).not.toHaveBeenCalled();
    axios.get.mock.calls.forEach(([url]) => expect(url).not.toMatch(/ai|llm|comment/i));
  });

  test("shows limitations without observation, with the Coach button and no empty card", async () => {
    const synthesis = {
      version: "v2", status: "insufficient", primary: null, supporting: [],
      limitations: [{ code: "synthesis.hr_observation", text: "Only limit.", source_paths: [] }],
      abstention: "Nothing relevant to describe.",
    };
    const intelligence = makeIntelligence("en");
    delete intelligence.workout_intelligence_v3;
    delete intelligence.narrative_coach_v3;
    mockRequests({ analysis: analysisWith(synthesis), intelligence });
    renderPage("/workout/w1", "/workout/:id", WorkoutDetail);
    expect(await screen.findByTestId("workout-limitations")).toHaveTextContent("Only limit.");
    expect(screen.getAllByTestId("ask-coach-btn")).toHaveLength(1);
    expect(screen.queryByTestId("workout-evidence")).not.toBeInTheDocument();
    expect(screen.getByTestId("synthesis-abstention")).toBeInTheDocument();
  });

  test.each(languages)("still shows one Coach button when V3 is unavailable in %s", async (language) => {
    mockRequests({ rejectV3: true });
    renderPage("/workout/w1", "/workout/:id", WorkoutDetail, language);
    expect(await screen.findByTestId("ask-coach-btn")).toBeInTheDocument();
    expect(screen.getAllByTestId("ask-coach-btn")).toHaveLength(1);
  });
});

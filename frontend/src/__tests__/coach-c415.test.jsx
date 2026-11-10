import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Coach from "@/pages/Coach";
import { LanguageProvider } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("@/context/AuthContext", () => ({ useAuth: jest.fn() }));

const WORKOUTS = {
  vannes: { name: "Sortie Vannes", distance_km: 9.64, date: "2026-11-01" },
  sene: { name: "Sortie Séné", distance_km: 5.79, date: "2026-11-03" },
};
const HISTORY = [
  { role: "user", content: "Analyse Vannes", workout_id: "vannes" },
  { role: "assistant", content: "Réponse Vannes 9,64 km", workout_id: "vannes" },
  { role: "user", content: "Analyse Séné", workout_id: "sene" },
  { role: "assistant", content: "Réponse Séné 5,79 km", workout_id: "sene" },
];

const mockApi = (history) => axios.get.mockImplementation(url => {
  const u = String(url);
  if (u.includes("/coach/history")) return Promise.resolve({ data: history });
  const id = u.split("/").pop();
  return Promise.resolve({ data: WORKOUTS[id] || { name: id } });
});

const renderCoach = (entry = "/coach") => render(
  <LanguageProvider><MemoryRouter initialEntries={[entry]}><Coach /></MemoryRouter></LanguageProvider>
);

// jsdom has no layout: emulate a scroll box on the real Radix viewport.
const fakeLayout = (viewport, { scrollHeight, clientHeight }) => {
  Object.defineProperty(viewport, "scrollHeight", { configurable: true, get: () => scrollHeight.v });
  Object.defineProperty(viewport, "clientHeight", { configurable: true, get: () => clientHeight });
};
const getViewport = () => document.querySelector("[data-radix-scroll-area-viewport]");

describe("C415 Coach chat", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    useAuth.mockReturnValue({ user: { id: "u1" } });
  });

  test("Vannes → Séné: each sequence is labelled with its own workout, in a single thread", async () => {
    mockApi(HISTORY);
    renderCoach();
    await screen.findByText("Réponse Séné 5,79 km");
    await waitFor(() => expect(screen.getAllByTestId("coach-workout-separator")).toHaveLength(2));
    const [first, second] = screen.getAllByTestId("coach-workout-separator");
    expect(first).toHaveAttribute("data-workout-id", "vannes");
    await waitFor(() => expect(first).toHaveTextContent("Sortie Vannes"));
    expect(first).toHaveTextContent("9,64");
    expect(second).toHaveAttribute("data-workout-id", "sene");
    await waitFor(() => expect(second).toHaveTextContent("Sortie Séné"));
    expect(second).not.toHaveTextContent("Vannes");
    // Order is preserved: Vannes sequence precedes the Séné separator, nothing is dropped.
    const follows = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(first, screen.getByText("Réponse Vannes 9,64 km"))).toBe(true);
    expect(follows(screen.getByText("Réponse Vannes 9,64 km"), second)).toBe(true);
    expect(follows(second, screen.getByText("Réponse Séné 5,79 km"))).toBe(true);
    expect(screen.getAllByTestId("coach-input")).toHaveLength(1);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
  });

  test("consecutive messages of one workout share one separator; A → B → A gives three", async () => {
    mockApi([
      { role: "user", content: "a1", workout_id: "vannes" },
      { role: "assistant", content: "a2", workout_id: "vannes" },
      { role: "user", content: "b1", workout_id: "sene" },
      { role: "assistant", content: "a3", workout_id: "vannes" },
    ]);
    renderCoach();
    await screen.findByText("a3");
    const ids = screen.getAllByTestId("coach-workout-separator").map(el => el.getAttribute("data-workout-id"));
    expect(ids).toEqual(["vannes", "sene", "vannes"]);
    // Each workout metadata is requested once, not once per separator.
    const gets = axios.get.mock.calls.map(([u]) => String(u)).filter(u => u.includes("/workouts/"));
    expect(gets.filter(u => u.endsWith("/vannes"))).toHaveLength(1);
  });

  test("a late reply keeps the workout of the request, not the active one", async () => {
    mockApi([{ role: "user", content: "ancien", workout_id: "vannes" }]);
    let resolveReply;
    axios.post.mockImplementationOnce(() => new Promise(r => { resolveReply = r; }));
    renderCoach("/coach?analyze=sene");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    expect(axios.post.mock.calls[0][1].workout_id).toBe("sene");
    resolveReply({ data: { response: "Réponse tardive Séné" } });
    const reply = await screen.findByText("Réponse tardive Séné");
    await waitFor(() => expect(screen.getAllByTestId("coach-workout-separator")).toHaveLength(2));
    const separators = screen.getAllByTestId("coach-workout-separator");
    expect(separators.map(el => el.getAttribute("data-workout-id"))).toEqual(["vannes", "sene"]);
    const last = separators[1];
    expect(last.compareDocumentPosition(reply) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("scrolls the real viewport to the latest message and keeps the position while reading older ones", async () => {
    mockApi(HISTORY);
    const scrollHeight = { v: 1000 };
    renderCoach();
    await screen.findByText("Réponse Séné 5,79 km");
    const viewport = getViewport();
    expect(viewport).toBeTruthy();
    fakeLayout(viewport, { scrollHeight, clientHeight: 200 });

    let resolveReply;
    axios.post.mockImplementationOnce(() => new Promise(r => { resolveReply = r; }));
    await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
    fireEvent.change(screen.getByTestId("coach-input"), { target: { value: "Et la FC ?" } });
    fireEvent.submit(screen.getByTestId("coach-input").closest("form"));
    await waitFor(() => expect(viewport.scrollTop).toBe(1000));

    // The reader scrolls up to an older message while the answer is pending.
    viewport.scrollTop = 100;
    fireEvent.scroll(viewport);
    scrollHeight.v = 1600;
    resolveReply({ data: { response: "Longue réponse ".repeat(50) } });
    await screen.findByText(/Longue réponse/);
    expect(viewport.scrollTop).toBe(100);

    // Back at the bottom, following resumes.
    viewport.scrollTop = 1400;
    fireEvent.scroll(viewport);
    axios.post.mockResolvedValueOnce({ data: { response: "Suite" } });
    scrollHeight.v = 2000;
    fireEvent.change(screen.getByTestId("coach-input"), { target: { value: "Merci" } });
    fireEvent.submit(screen.getByTestId("coach-input").closest("form"));
    await screen.findByText("Suite");
    expect(viewport.scrollTop).toBe(2000);
  });

  test("history load scrolls to the bottom and the mobile keyboard (input focus) re-anchors", async () => {
    mockApi(HISTORY);
    window.innerWidth = 390;
    jest.useFakeTimers();
    try {
      renderCoach();
      await act0();
      const viewport = getViewport();
      const scrollHeight = { v: 900 };
      fakeLayout(viewport, { scrollHeight, clientHeight: 300 });
      viewport.scrollTop = 0;
      fireEvent.scroll(viewport);
      fireEvent.focus(screen.getByTestId("coach-input"));
      jest.advanceTimersByTime(350);
      expect(viewport.scrollTop).toBe(900);
    } finally {
      jest.useRealTimers();
    }
  });
});

async function act0() {
  const { act } = require("@testing-library/react");
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

// ---- Workout sheet: a single analysis card, no second "Coach" ----
const WorkoutFacts = require("@/components/workout/WorkoutFacts").default;
const { useLanguage } = require("@/context/LanguageContext");

const sheetData = (lang) => ({
  narrative_coach_v3: {
    language: lang, generation_mode: "deterministic_fallback",
    headline: "C388 HEADLINE", analysis: "C388 ANALYSIS", interpretation: "C388 INTERPRETATION",
    recommendation: "C388 RECOMMENDATION", limitations: ["LIMIT ONE", "LIMIT TWO"],
  },
  workout_intelligence_v3: {
    version: "v3",
    session_classification: { type: "intervals", evidence: { effort_count: 6, recovery_count: 5 },
      relative_effort: { status: "used", reference_count: 29 } },
    historical_comparison: { status: "available", comparability: "strong", reference_count: 12,
      pace_at_comparable_hr: { reference_count: 12, pace_difference_sec_per_km: -4 } },
  },
});

function Sheet({ data, lang }) {
  const { t } = useLanguage();
  return <WorkoutFacts data={data} lang={lang} t={t} detailsAvailable={false} />;
}

describe.each([["fr", "Analyse de séance"], ["en", "Session analysis"], ["es", "Análisis de la sesión"]])(
  "workout sheet in %s", (lang, title) => {
    test.each([["with a separate coach comment", true], ["deterministic only", false]])("%s", (_n, withComment) => {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
      const data = sheetData(lang);
      if (withComment) data.coach_comment = { status: "generated", language: lang, source: "coach_c396", text: "Commentaire" };
      render(<LanguageProvider><Sheet data={data} lang={lang} /></LanguageProvider>);
      const card = screen.getByTestId("workout-facts");
      expect(card).not.toHaveTextContent(title);
      // C416: narrative prose and coach comment never render on the sheet; facts, comparisons and limits do.
      const all = document.body.textContent;
      ["C388 HEADLINE", "C388 ANALYSIS", "C388 INTERPRETATION", "C388 RECOMMENDATION", "Commentaire"]
        .forEach(s => expect(all).not.toContain(s));
      expect(screen.queryByTestId("coach-session-comment")).not.toBeInTheDocument();
      expect(screen.getByTestId("workout-evidence")).toHaveTextContent(/29/);
      expect(screen.getByTestId("workout-evidence")).toHaveTextContent(/6/);
      expect(screen.getByTestId("narrative-comparisons")).toHaveTextContent("-4");
      expect(all).toContain("LIMIT ONE");
      expect(all).toContain("LIMIT TWO");
    });
  });

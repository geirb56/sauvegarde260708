import React from "react";
import "@testing-library/jest-dom";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Link } from "react-router-dom";
import axios from "axios";

import Coach from "@/pages/Coach";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";
import { translations } from "@/lib/i18n";

jest.mock("axios");
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const WORKOUTS = {
  wA: { name: "Run A", distance_km: 8, date: "2026-11-01" },
  wB: { name: "Run B", distance_km: 12, date: "2026-11-03" },
};

const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
};

const mockGets = (history = []) => axios.get.mockImplementation(url => {
  if (String(url).includes("/coach/history")) return Promise.resolve({ data: history });
  const id = String(url).split("/workouts/")[1];
  return WORKOUTS[id] ? Promise.resolve({ data: WORKOUTS[id] }) : Promise.reject({ response: { status: 404 } });
});

const renderCoach = (entry, lang = "en") => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  return render(
    <LanguageProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Link to="/coach?analyze=wB" data-testid="go-b">B</Link>
        <Link to="/coach?analyze=wA" data-testid="go-a">A</Link>
        <Coach />
      </MemoryRouter>
    </LanguageProvider>
  );
};

const submit = text => {
  fireEvent.change(screen.getByTestId("coach-input"), { target: { value: text } });
  fireEvent.submit(screen.getByTestId("coach-input").closest("form"));
};

describe("C412 workout / coach flow", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGets();
  });

  test("A → Coach → follow-up keeps workout A", async () => {
    axios.post.mockResolvedValue({ data: { response: "reply" } });
    renderCoach("/coach?analyze=wA");
    expect(await screen.findByText("reply")).toBeInTheDocument();
    expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run A");
    submit("Why did my pace drop?");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1]).toMatchObject({ message: "Why did my pace drop?", workout_id: "wA" });
  });

  test("A → B while mounted switches the active workout and analyzes B once", async () => {
    axios.post.mockResolvedValue({ data: { response: "reply" } });
    renderCoach("/coach?analyze=wA");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run A"));
    fireEvent.click(screen.getByTestId("go-b"));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1].workout_id).toBe("wB");
    await waitFor(() => expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run B"));
    expect(screen.getByTestId("coach-workout-context")).not.toHaveTextContent("Run A");
    expect(screen.getByTestId("back-to-workout")).toHaveAttribute("href", "/workout/wB");
    submit("Compare");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(3));
    expect(axios.post.mock.calls[2][1].workout_id).toBe("wB");
  });

  test("late replies of A never override B's loading state or active context", async () => {
    const a = deferred();
    const b = deferred();
    axios.post.mockImplementation((_u, body) => (body.workout_id === "wA" ? a.promise : b.promise));
    renderCoach("/coach?analyze=wA");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("go-b"));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    await act(async () => { a.resolve({ data: { response: "late A" } }); });
    expect(screen.getByTestId("coach-input")).toBeDisabled();
    expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run B");
    await act(async () => { b.resolve({ data: { response: "reply B" } }); });
    await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
    expect(screen.getByText("reply B")).toBeInTheDocument();
    expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run B");
    const tagged = screen.getAllByTestId(/^message-/).map(n => n.getAttribute("data-workout-id"));
    expect(tagged.filter(id => id === "wB")).toHaveLength(2);
  });

  test("explicit selection wins over a history ending on another workout", async () => {
    mockGets([{ role: "assistant", content: "old", workout_id: "wA", timestamp: "t" }]);
    axios.post.mockResolvedValue({ data: { response: "reply B" } });
    renderCoach("/coach?analyze=wB");
    expect(await screen.findByText("reply B")).toBeInTheDocument();
    expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run B");
    expect(axios.post).toHaveBeenCalledTimes(1);
  });

  test("history restores the active workout on refresh without a new analysis", async () => {
    mockGets([{ role: "assistant", content: "old", workout_id: "wA", timestamp: "t" }]);
    renderCoach("/coach");
    expect(await screen.findByText("old")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run A"));
    expect(axios.post).not.toHaveBeenCalled();
  });

  test("closing context then asking a general question sends no workout_id", async () => {
    axios.post.mockResolvedValue({ data: { response: "reply" } });
    renderCoach("/coach?analyze=wA");
    expect(await screen.findByText("reply")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("close-workout-context"));
    submit("General question");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1]).not.toHaveProperty("workout_id");
  });

  test("unknown or foreign workout (404) shows an explicit message", async () => {
    axios.post.mockRejectedValue({ response: { status: 404 } });
    renderCoach("/coach?analyze=wX");
    expect(await screen.findByText(/not accessible/i)).toBeInTheDocument();
  });

  test("FREE / quota: monthly quota 429 is explicit and keeps the composer usable", async () => {
    axios.post.mockRejectedValue({ response: { status: 429, data: { code: "coach_monthly_quota_exhausted" } } });
    renderCoach("/coach?analyze=wA");
    expect(await screen.findByText(/monthly Coach limit/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
  });

  test.each(["en", "fr", "es"])("context and follow-up labels exist in %s", async lang => {
    axios.post.mockResolvedValue({ data: { response: "reply" } });
    renderCoach("/coach?analyze=wA", lang);
    expect(await screen.findByText("reply")).toBeInTheDocument();
    expect(screen.getAllByRole("button").length).toBeGreaterThan(2);
    const dict = translations[lang].coach;
    for (const key of ["activeWorkout", "backToWorkout", "closeContext", "workoutNotFound", "limitReached", "rateLimited"]) {
      expect(typeof dict[key]).toBe("string");
    }
    expect(Object.keys(dict.followups)).toEqual(expect.arrayContaining(["compare", "takeaway"]));
    expect(screen.getByTestId("back-to-workout")).toHaveAccessibleName(dict.backToWorkout);
  });

  describe("concurrency (shared request sequence)", () => {
    // Every GET /workouts/:id is held until released, in call order.
    const heldWorkoutGets = () => {
      const held = [];
      axios.get.mockImplementation(url => {
        if (String(url).includes("/coach/history")) return Promise.resolve({ data: [] });
        const id = String(url).split("/workouts/")[1];
        const d = deferred();
        held.push({ id, ...d });
        return d.promise;
      });
      return held;
    };
    const ctx = () => screen.getByTestId("coach-workout-context");
    const postIds = () => axios.post.mock.calls.map(c => c[1].workout_id);

    test("A → B → A: late metadata of the first A is ignored, one analysis for the last A", async () => {
      const held = heldWorkoutGets();
      axios.post.mockResolvedValue({ data: { response: "reply A2" } });
      renderCoach("/coach?analyze=wA");
      await waitFor(() => expect(held).toHaveLength(1));
      fireEvent.click(screen.getByTestId("go-b"));
      await waitFor(() => expect(held).toHaveLength(2));
      fireEvent.click(screen.getByTestId("go-a"));
      await waitFor(() => expect(held).toHaveLength(3));
      const [a1, b, a2] = held;
      await act(async () => { a1.resolve({ data: { name: "STALE A1", distance_km: 1, date: "2026-01-01" } }); });
      expect(axios.post).not.toHaveBeenCalled();
      expect(ctx()).not.toHaveTextContent("STALE A1");
      await act(async () => { b.resolve({ data: WORKOUTS.wB }); });
      expect(axios.post).not.toHaveBeenCalled();
      await act(async () => { a2.resolve({ data: WORKOUTS.wA }); });
      expect(await screen.findByText("reply A2")).toBeInTheDocument();
      expect(postIds()).toEqual(["wA"]);
      expect(ctx()).toHaveTextContent("Run A");
      expect(ctx()).not.toHaveTextContent("STALE A1");
      expect(screen.getAllByTestId(/^message-/)).toHaveLength(2);
      await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
    });

    test("A → B → A: rejected stale metadata request does not start or clear anything", async () => {
      const held = heldWorkoutGets();
      axios.post.mockResolvedValue({ data: { response: "reply A2" } });
      renderCoach("/coach?analyze=wA");
      await waitFor(() => expect(held).toHaveLength(1));
      fireEvent.click(screen.getByTestId("go-b"));
      await waitFor(() => expect(held).toHaveLength(2));
      fireEvent.click(screen.getByTestId("go-a"));
      await waitFor(() => expect(held).toHaveLength(3));
      const [a1, , a2] = held;
      await act(async () => { a1.resolve(Promise.reject({ response: { status: 500 } })); });
      expect(axios.post).not.toHaveBeenCalled();
      expect(screen.getByTestId("coach-input")).toBeDisabled();
      await act(async () => { a2.resolve({ data: WORKOUTS.wA }); });
      expect(await screen.findByText("reply A2")).toBeInTheDocument();
      expect(postIds()).toEqual(["wA"]);
    });

    const startPendingQuestionOnA = async () => {
      mockGets();
      const q = deferred();
      const b = deferred();
      axios.post.mockImplementation((_u, body) => {
        if (body.message === "Question on A") return q.promise;
        return b.promise;
      });
      renderCoach("/coach?analyze=wA");
      // first analysis (A) resolves through the default branch of the mock
      await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
      await act(async () => { b.resolve({ data: { response: "analysis A" } }); });
      await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
      submit("Question on A");
      await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
      expect(axios.post.mock.calls[1][1].workout_id).toBe("wA");
      const bAnalysis = deferred();
      axios.post.mockImplementation(() => bAnalysis.promise);
      fireEvent.click(screen.getByTestId("go-b"));
      await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(3));
      expect(axios.post.mock.calls[2][1].workout_id).toBe("wB");
      return { q, bAnalysis };
    };

    test("question on A finishing before analysis of B keeps B loading and active", async () => {
      const { q, bAnalysis } = await startPendingQuestionOnA();
      await act(async () => { q.resolve({ data: { response: "answer A" } }); });
      expect(screen.getByText("answer A")).toBeInTheDocument();
      expect(screen.getByTestId("coach-input")).toBeDisabled();
      expect(screen.getByText("Analyzing...", { exact: false })).toBeInTheDocument();
      expect(ctx()).toHaveTextContent("Run B");
      expect(screen.getByTestId("back-to-workout")).toHaveAttribute("href", "/workout/wB");
      await act(async () => { bAnalysis.resolve({ data: { response: "analysis B" } }); });
      await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
      expect(screen.getByText("analysis B")).toBeInTheDocument();
      const answerA = screen.getByText("answer A").closest("[data-testid^='message-']");
      expect(answerA).toHaveAttribute("data-workout-id", "wA");
    });

    test("question on A failing before analysis of B does not clear B loading or context", async () => {
      const { q, bAnalysis } = await startPendingQuestionOnA();
      await act(async () => { q.resolve(Promise.reject({ response: { status: 500 } })); });
      expect(screen.getByTestId("coach-input")).toBeDisabled();
      expect(ctx()).toHaveTextContent("Run B");
      await act(async () => { bAnalysis.resolve({ data: { response: "analysis B" } }); });
      await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
      expect(ctx()).toHaveTextContent("Run B");
    });

    test("superseded analysis A rejected late does not clear loading of B", async () => {
      mockGets();
      const a = deferred();
      const b = deferred();
      axios.post.mockImplementation((_u, body) => (body.workout_id === "wA" ? a.promise : b.promise));
      renderCoach("/coach?analyze=wA");
      await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByTestId("go-b"));
      await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
      await act(async () => { a.resolve(Promise.reject({ response: { status: 500 } })); });
      expect(screen.getByTestId("coach-input")).toBeDisabled();
      expect(ctx()).toHaveTextContent("Run B");
      await act(async () => { b.resolve({ data: { response: "reply B" } }); });
      await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
    });
  });
});

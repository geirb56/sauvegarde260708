import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Link } from "react-router-dom";
import axios from "axios";

import Coach from "@/pages/Coach";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY, translations } from "@/lib/i18n";

jest.mock("axios");
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const WORKOUTS = {
  wA: { name: "Run A", distance_km: 8, date: "2026-11-01" },
  wB: { name: "Run B", distance_km: 12, date: "2026-11-03" },
};

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

const submit = (text) => {
  fireEvent.change(screen.getByTestId("coach-input"), { target: { value: text } });
  fireEvent.submit(screen.getByTestId("coach-input").closest("form"));
};

describe("C414 unified Coach experience", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    axios.get.mockImplementation((url) => {
      if (String(url).includes("/coach/history")) return Promise.resolve({ data: [] });
      const id = String(url).split("/workouts/")[1];
      return WORKOUTS[id] ? Promise.resolve({ data: WORKOUTS[id] }) : Promise.reject({ response: { status: 404 } });
    });
    axios.post.mockImplementation((_url, body) => Promise.resolve({ data: { response: `reply:${body.workout_id || "general"}:${body.message.slice(0, 12)}` } }));
  });

  test("analysis, two follow-ups and a comparison live in one thread with one composer", async () => {
    renderCoach("/coach?analyze=wA");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    await screen.findByTestId("coach-followup-chips");
    submit("Why did my pace drop?");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    submit("Compare with the previous one");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getAllByTestId(/^message-\d+$/)).toHaveLength(6));
    expect(screen.getAllByTestId("coach-input")).toHaveLength(1);
    expect(screen.getAllByTestId("coach-page")).toHaveLength(1);
    axios.post.mock.calls.forEach(([, body]) => expect(body.workout_id).toBe("wA"));
  });

  test("a follow-up chip only fills the composer and triggers no request", async () => {
    renderCoach("/coach?analyze=wA");
    const chips = await screen.findByTestId("coach-followup-chips");
    fireEvent.click(chips.querySelector("button"));
    expect(screen.getByTestId("coach-input").value).toBe(translations.en.coach.followups.improve);
    expect(axios.post).toHaveBeenCalledTimes(1);
  });

  test("A → B → A keeps every message bound to its own workout, with one analysis per switch", async () => {
    renderCoach("/coach?analyze=wA");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    await screen.findByTestId("coach-followup-chips");
    fireEvent.click(screen.getByTestId("go-b"));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getAllByTestId(/^message-\d+$/)).toHaveLength(4));
    fireEvent.click(screen.getByTestId("go-a"));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getAllByTestId(/^message-\d+$/)).toHaveLength(6));
    const ids = screen.getAllByTestId(/^message-\d+$/).map((node) => node.getAttribute("data-workout-id"));
    expect(ids).toEqual(["wA", "wA", "wB", "wB", "wA", "wA"]);
  });

  test("closing the context returns to the general mode in the same component", async () => {
    renderCoach("/coach?analyze=wA");
    await screen.findByTestId("coach-followup-chips");
    fireEvent.click(screen.getByTestId("close-workout-context"));
    expect(screen.queryByTestId("coach-workout-context")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("coach-input")).toHaveLength(1);
    submit("General question");
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1]).not.toHaveProperty("workout_id");
  });

  test("browser-back style remount with stored history restores context without a new analysis", async () => {
    axios.get.mockImplementation((url) => String(url).includes("/coach/history")
      ? Promise.resolve({ data: [
        { role: "user", content: "q", workout_id: "wA" },
        { role: "assistant", content: "a", workout_id: "wA" },
      ] })
      : Promise.resolve({ data: WORKOUTS.wA }));
    renderCoach("/coach");
    await waitFor(() => expect(screen.getByTestId("coach-workout-context")).toHaveTextContent("Run A"));
    expect(axios.post).not.toHaveBeenCalled();
    expect(screen.getByTestId("back-to-workout")).toHaveAttribute("href", "/workout/wA");
  });

  test.each(["fr", "en", "es"])("localized context, follow-ups and mobile-safe layout (%s)", async (lang) => {
    renderCoach("/coach?analyze=wA", lang);
    const chips = await screen.findByTestId("coach-followup-chips");
    const dict = translations[lang].coach;
    expect(chips).toHaveTextContent(dict.followups.improve);
    expect(chips).toHaveTextContent(dict.followups.takeaway);
    expect(screen.getByTestId("back-to-workout")).toHaveAttribute("aria-label", dict.backToWorkout);
    expect(screen.getByTestId("close-workout-context")).toHaveAttribute("aria-label", dict.closeContext);
    expect(screen.getByTestId("coach-page")).toHaveClass("min-w-0");
    expect(screen.getByTestId("coach-workout-context")).toHaveClass("shrink-0");
    expect(screen.getByTestId("coach-input").closest("div.shrink-0")).toBeInTheDocument();
  });

  test("429 quota on the first analysis is explicit and the composer stays usable", async () => {
    axios.post.mockRejectedValueOnce({ response: { status: 429, data: { code: "coach_monthly_quota_exhausted" } } });
    renderCoach("/coach?analyze=wA");
    expect(await screen.findByText(translations.en.coach.limitReached)).toBeInTheDocument();
    expect(screen.getByTestId("coach-input")).not.toBeDisabled();
  });
});

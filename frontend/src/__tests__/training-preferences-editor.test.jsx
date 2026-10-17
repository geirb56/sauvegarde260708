import React from "react";
import "@testing-library/jest-dom";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axios from "axios";

import TrainingPreferencesEditor from "@/components/training/TrainingPreferencesEditor";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const emptyPreferences = {
  sessions_per_week: null,
  preferred_training_days: null,
  preferred_long_run_day: null,
};

const makeResponse = ({
  sessions_per_week = 4,
  preferred_training_days = null,
  preferred_long_run_day = null,
  effective_from = null,
  active_preferences = {
    sessions_per_week: 4,
    preferred_training_days: null,
    preferred_long_run_day: null,
  },
} = {}) => ({
  status: "ok",
  training_prefs: {
    sessions_per_week,
    preferred_training_days,
    preferred_long_run_day,
    effective_from,
    active_preferences,
  },
});

const renderEditor = (response = makeResponse(), language = "en") => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  axios.get.mockResolvedValue({ data: response });
  return render(<LanguageProvider><TrainingPreferencesEditor /></LanguageProvider>);
};

const waitForEditor = () => screen.findByTestId("training-preferences-editor");

describe("TrainingPreferencesEditor", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("loads desired and active preferences separately and uses the backend application date", async () => {
    renderEditor(makeResponse({
      sessions_per_week: 5,
      preferred_training_days: ["tuesday", "sunday"],
      preferred_long_run_day: "sunday",
      effective_from: "2026-09-21",
      active_preferences: {
        sessions_per_week: 4,
        preferred_training_days: null,
        preferred_long_run_day: null,
      },
    }));

    await waitForEditor();
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/training/v2/preferences"));
    expect(screen.getByTestId("sessions-per-week-btn-5")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("preferred-day-tuesday")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("preferred-day-sunday")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("preferred-long-run-day")).toHaveValue("sunday");
    expect(screen.getByTestId("active-training-preferences")).toHaveTextContent("Sessions per week: 4");
    expect(screen.getByTestId("active-training-preferences")).toHaveTextContent("Preferred days: No preference");
    expect(screen.getByTestId("training-preferences-effective-date"))
      .toHaveTextContent("Your changes will apply starting Monday, September 21, 2026.");
    expect(screen.getByTestId("save-training-preferences")).toBeDisabled();
  });

  test("renders an empty state and offers all seven days without an existing preference", async () => {
    renderEditor(makeResponse({
      ...emptyPreferences,
      active_preferences: emptyPreferences,
    }));
    await waitForEditor();

    expect(screen.getByText("No training preferences are active yet.")).toBeInTheDocument();
    DAYS.forEach((day) => expect(screen.getByTestId(`preferred-day-${day}`)).toBeInTheDocument());
    expect(screen.getByTestId("preferred-long-run-day").options).toHaveLength(8);
    expect(screen.getByTestId("save-training-preferences")).toBeDisabled();
  });

  test("selects and deselects days, and clears a long-run day when it is deselected", async () => {
    renderEditor(makeResponse({
      preferred_training_days: ["tuesday", "sunday"],
      preferred_long_run_day: "sunday",
      active_preferences: {
        sessions_per_week: 4,
        preferred_training_days: ["tuesday", "sunday"],
        preferred_long_run_day: "sunday",
      },
    }));
    await waitForEditor();

    fireEvent.click(screen.getByTestId("preferred-day-sunday"));
    expect(screen.getByTestId("preferred-day-sunday")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("preferred-long-run-day")).toHaveValue("");
    expect(screen.getByTestId("save-training-preferences")).toBeEnabled();

    axios.patch.mockResolvedValue({
      data: makeResponse({
        preferred_training_days: ["tuesday"],
        active_preferences: {
          sessions_per_week: 4,
          preferred_training_days: ["tuesday", "sunday"],
          preferred_long_run_day: "sunday",
        },
        effective_from: "2026-09-21",
      }),
    });
    fireEvent.click(screen.getByTestId("save-training-preferences"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/training/v2/preferences"),
        { preferred_training_days: ["tuesday"], preferred_long_run_day: null }
      );
    });
    expect(screen.getByTestId("active-training-preferences")).toHaveTextContent("Preferred days: Tuesday, Sunday");
  });

  test("selecting a long-run day saves only changed fields and never changes the session count", async () => {
    renderEditor(makeResponse({
      sessions_per_week: 4,
      preferred_training_days: ["tuesday", "thursday"],
      active_preferences: {
        sessions_per_week: 4,
        preferred_training_days: ["tuesday", "thursday"],
        preferred_long_run_day: null,
      },
    }));
    await waitForEditor();

    expect(within(screen.getByTestId("preferred-long-run-day")).queryByRole("option", { name: "Friday" }))
      .not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("preferred-day-sunday"));
    fireEvent.change(screen.getByTestId("preferred-long-run-day"), { target: { value: "sunday" } });
    axios.patch.mockResolvedValue({
      data: makeResponse({
        preferred_training_days: ["tuesday", "thursday", "sunday"],
        preferred_long_run_day: "sunday",
        effective_from: "2026-09-21",
        active_preferences: {
          sessions_per_week: 4,
          preferred_training_days: ["tuesday", "thursday"],
          preferred_long_run_day: null,
        },
      }),
    });
    fireEvent.click(screen.getByTestId("save-training-preferences"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/training/v2/preferences"),
        {
          preferred_training_days: ["tuesday", "thursday", "sunday"],
          preferred_long_run_day: "sunday",
        }
      );
    });
    expect(await screen.findByTestId("training-preferences-effective-date"))
      .toHaveTextContent("Monday, September 21, 2026");
    expect(screen.getByTestId("active-training-preferences")).toHaveTextContent("Preferred days: Tuesday, Thursday");
    expect(screen.getByRole("status")).toHaveTextContent("Training preferences saved.");
  });

  test("clears a long-run choice that becomes invalid when the first training day is selected", async () => {
    renderEditor(makeResponse({
      preferred_long_run_day: "sunday",
      active_preferences: {
        sessions_per_week: 4,
        preferred_training_days: null,
        preferred_long_run_day: "sunday",
      },
    }));
    await waitForEditor();
    fireEvent.click(screen.getByTestId("preferred-day-tuesday"));

    expect(screen.getByTestId("preferred-long-run-day")).toHaveValue("");
    axios.patch.mockResolvedValue({
      data: makeResponse({
        preferred_training_days: ["tuesday"],
        preferred_long_run_day: null,
        effective_from: "2026-09-21",
        active_preferences: {
          sessions_per_week: 4,
          preferred_training_days: null,
          preferred_long_run_day: "sunday",
        },
      }),
    });
    fireEvent.click(screen.getByTestId("save-training-preferences"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/training/v2/preferences"),
        { preferred_training_days: ["tuesday"], preferred_long_run_day: null }
      );
    });
  });

  test("changing sessions sends a minimal PATCH and keeps the response active state authoritative", async () => {
    renderEditor(makeResponse({
      preferred_training_days: ["tuesday"],
      preferred_long_run_day: "tuesday",
      active_preferences: {
        sessions_per_week: 4,
        preferred_training_days: ["tuesday"],
        preferred_long_run_day: "tuesday",
      },
    }));
    await waitForEditor();

    fireEvent.click(screen.getByTestId("sessions-per-week-btn-5"));
    fireEvent.click(screen.getByTestId("save-training-preferences"));
    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/training/v2/preferences"),
        { sessions_per_week: 5 }
      );
    });
    expect(screen.getByTestId("active-training-preferences")).toHaveTextContent("Sessions per week: 4");
    expect(screen.getByTestId("sessions-per-week-btn-5")).toHaveAttribute("aria-pressed", "true");
  });

  test.each([
    [401, "Your session has expired."],
    [409, "Preferences changed elsewhere."],
    [422, "These preferences are not compatible."],
    [0, "Network error."],
  ])("shows an actionable error for status %s", async (status, expectedMessage) => {
    renderEditor();
    await waitForEditor();
    axios.patch.mockRejectedValue(status
      ? { response: { status, data: { detail: "backend detail" } } }
      : new Error("offline"));
    fireEvent.click(screen.getByTestId("preferred-day-monday"));
    fireEvent.click(screen.getByTestId("save-training-preferences"));

    expect(await screen.findByRole("alert")).toHaveTextContent(expectedMessage);
  });

  test("prevents duplicate saves and disables edits while a save is pending", async () => {
    renderEditor();
    await waitForEditor();
    let resolveSave;
    axios.patch.mockReturnValue(new Promise((resolve) => { resolveSave = resolve; }));

    fireEvent.click(screen.getByTestId("preferred-day-monday"));
    fireEvent.click(screen.getByTestId("save-training-preferences"));
    fireEvent.click(screen.getByTestId("save-training-preferences"));
    expect(axios.patch).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("save-training-preferences")).toBeDisabled();
    expect(screen.getByTestId("preferred-day-tuesday")).toBeDisabled();

    await act(async () => {
      resolveSave({
        data: makeResponse({
          preferred_training_days: ["monday"],
          active_preferences: {
            sessions_per_week: 4,
            preferred_training_days: null,
            preferred_long_run_day: null,
          },
          effective_from: "2026-09-21",
        }),
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Training preferences saved.");
  });

  test("keeps the seven-day selector mobile-friendly and translates its controls in FR and ES", async () => {
    const view = renderEditor(makeResponse(), "fr");
    await waitForEditor();
    expect(screen.getByTestId("preferred-training-days").querySelector(".grid-cols-4"))
      .toHaveClass("sm:grid-cols-7");
    expect(screen.getByTestId("preferred-day-monday")).toHaveTextContent("Lundi");

    view.unmount();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "es");
    render(<LanguageProvider><TrainingPreferencesEditor /></LanguageProvider>);
    await waitFor(() => expect(screen.getByTestId("preferred-day-monday")).toHaveTextContent("Lunes"));
    expect(screen.getByTestId("save-training-preferences")).toHaveTextContent("Guardar preferencias");
  });
});

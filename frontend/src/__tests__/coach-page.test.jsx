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
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

describe("Coach page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    useAuth.mockReturnValue({ user: { id: "u1" } });
    axios.get.mockResolvedValue({ data: [] });
  });

  test.each([
    ["en", "What do you want to work on?", "Your RunIndex coach"],
    ["fr", "Sur quoi veux-tu qu’on travaille ?", "Ton entraîneur RunIndex"],
    ["es", "¿En qué quieres que trabajemos?", "Tu entrenador RunIndex"],
  ])("empty state is conversation-first in %s", async (language, emptyState, subtitle) => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    expect(await screen.findByText(emptyState)).toBeInTheDocument();
    expect(screen.getByText(subtitle)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Coach" })).toBeInTheDocument();
    expect(within(screen.getByTestId("coach-empty-state")).getAllByRole("button")).toHaveLength(4);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByTestId("clear-history")).not.toBeInTheDocument();
    expect(screen.getByTestId("coach-page")).not.toHaveTextContent(
      /second prescription|seconde prescription|segunda prescripción|prescription authority|autorité de prescription|autoridad de prescripción|Training V2|canonical|canonique|engine|I use your RunIndex plan|Je m'appuie sur ton plan RunIndex|Me apoyo en tu plan de RunIndex|Helpful questions|Questions utiles|Preguntas útiles/i
    );
    expect(screen.queryByText(/Tempo|Intervals|Long run/i)).not.toBeInTheDocument();
  });

  test.each([
    ["en", [
      ["My next workout", "What is my next workout and how should I approach it?"],
      ["My recent runs", "What stands out from my recent runs?"],
      ["My progress", "What does my recent data show about my progress?"],
      ["My recovery", "What does my recent data show about my recovery?"],
    ]],
    ["fr", [
      ["Ma prochaine séance", "Quelle est ma prochaine séance et comment dois-je l’aborder ?"],
      ["Mes dernières sorties", "Qu’est-ce qui ressort de mes dernières sorties ?"],
      ["Ma progression", "Que montrent mes données récentes sur ma progression ?"],
      ["Ma récupération", "Que montrent mes données récentes sur ma récupération ?"],
    ]],
    ["es", [
      ["Mi próxima sesión", "¿Cuál es mi próxima sesión y cómo debería afrontarla?"],
      ["Mis últimas salidas", "¿Qué destaca de mis últimas salidas?"],
      ["Mi progreso", "¿Qué muestran mis datos recientes sobre mi progreso?"],
      ["Mi recuperación", "¿Qué muestran mis datos recientes sobre mi recuperación?"],
    ]],
  ])("shortcuts fill and focus the composer without sending in %s", async (language, shortcuts) => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    axios.post.mockResolvedValue({ data: { response: "answer" } });
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    await screen.findByTestId("coach-empty-state");
    const input = screen.getByTestId("coach-input");
    for (const [label, question] of shortcuts) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(input).toHaveValue(question);
      expect(input).toHaveFocus();
      expect(axios.post).not.toHaveBeenCalled();
    }

    fireEvent.click(screen.getByTestId("coach-submit"));
    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    expect(axios.post).toHaveBeenCalledWith(expect.stringContaining("/coach/analyze"), {
      message: shortcuts[3][1],
      language,
    });
    expect(await screen.findByText("answer")).toBeInTheDocument();
    expect(screen.queryByTestId("coach-empty-state")).not.toBeInTheDocument();
  });

  test("history load failure renders explicit unavailable state instead of successful empty state", async () => {
    axios.get.mockRejectedValueOnce(new Error("network"));

    render(
      <LanguageProvider>
        <MemoryRouter>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    expect(await screen.findByTestId("coach-history-load-error")).toBeInTheDocument();
    expect(screen.queryByTestId("coach-empty-state")).not.toBeInTheDocument();
    expect(screen.queryByTestId("suggestion-nextWorkout")).not.toBeInTheDocument();
  });

  test("existing history remains visible with workout metadata and a discreet clear action", async () => {
    axios.get.mockResolvedValueOnce({ data: [
      { role: "user", content: "Tell me about my run", workout_id: "past-run" },
      { role: "assistant", content: "You kept a steady effort.", workout_id: "past-run" },
    ] });
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    expect(await screen.findByText("You kept a steady effort.")).toBeInTheDocument();
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/coach/history?limit=50"));
    expect(screen.getByTestId("message-0")).toHaveAttribute("data-workout-id", "past-run");
    expect(screen.getByTestId("message-1")).toHaveAttribute("data-workout-id", "past-run");
    expect(screen.getByRole("button", { name: "Clear history" })).toBeInTheDocument();
    expect(screen.queryByTestId("coach-empty-state")).not.toBeInTheDocument();
    expect(screen.queryByText("Workout analyzed")).not.toBeInTheDocument();
    expect(axios.post).not.toHaveBeenCalled();
  });

  test("composer preserves Enter submission, loading guard, and recoverable errors", async () => {
    let rejectRequest;
    axios.post.mockImplementationOnce(() => new Promise((resolve, reject) => {
      rejectRequest = reject;
    }));
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    await screen.findByTestId("coach-empty-state");
    const input = screen.getByRole("textbox", { name: "Ask about your training..." });
    const submit = screen.getByRole("button", { name: "Send message" });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "  How am I doing?  " } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(axios.post).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(axios.post).toHaveBeenCalledTimes(1);
    expect(axios.post.mock.calls[0][1]).toEqual({ message: "How am I doing?", language: "en" });
    expect(input).toBeDisabled();
    expect(submit).toBeDisabled();
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
    fireEvent.submit(input.closest("form"));
    expect(axios.post).toHaveBeenCalledTimes(1);

    rejectRequest(new Error("network"));
    expect(await screen.findByText("Unable to process request.")).toBeInTheDocument();
    await waitFor(() => expect(input).not.toBeDisabled());
    expect(input).toHaveValue("");
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();

    axios.post.mockResolvedValueOnce({ data: { response: "Back online." } });
    fireEvent.change(input, { target: { value: "Try again" } });
    fireEvent.click(submit);
    expect(await screen.findByText("Back online.")).toBeInTheDocument();
    expect(axios.post).toHaveBeenCalledTimes(2);
  });

  test.each([
    ["en", "Analyze this workout and tell me what matters most: Tempo Run"],
    ["fr", "Analyse cette séance et dis-moi ce qu'il faut retenir : Tempo Run"],
    ["es", "Analiza esta sesión y dime qué es lo más importante: Tempo Run"],
  ])("workout auto-analysis posts takeaway message, workout_id, and language in %s", async (language, message) => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    axios.get.mockImplementation((url) => {
      if (String(url).includes("/coach/history")) {
        return Promise.resolve({ data: [] });
      }
      if (String(url).includes("/workouts/workout-42")) {
        return Promise.resolve({ data: { name: "Tempo Run" } });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
    axios.post.mockResolvedValue({ data: { response: "analysis" } });

    render(
      <LanguageProvider>
        <MemoryRouter initialEntries={["/coach?analyze=workout-42"]}>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining("/coach/analyze"),
      {
        message,
        workout_id: "workout-42",
        language,
      }
    );
    expect(axios.post.mock.calls[0][1]).not.toHaveProperty("deep_analysis");
    expect(message).not.toMatch(/Deep analysis|Analyse approfondie|Análisis profundo/i);
    expect(await screen.findByText("analysis")).toBeInTheDocument();
    expect(screen.getByTestId("message-0")).toHaveAttribute("data-workout-id", "workout-42");
    expect(screen.queryByText(/Workout analyzed|Séance analysée|Sesión analizada/i)).not.toBeInTheDocument();
  });

  test("selected workout context persists through follow-ups", async () => {
    axios.get.mockImplementation((url) => {
      if (String(url).includes("/coach/history")) {
        return Promise.resolve({ data: [] });
      }
      if (String(url).includes("/workouts/w28")) {
        return Promise.resolve({ data: { name: "Easy Run" } });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
    axios.post.mockResolvedValue({ data: { response: "analysis" } });

    render(
      <LanguageProvider>
        <MemoryRouter initialEntries={["/coach?analyze=w28"]}>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
    fireEvent.change(screen.getByTestId("coach-input"), {
      target: { value: "Que retiens-tu de cette séance par rapport à mes sorties similaires ?" },
    });
    fireEvent.submit(screen.getByTestId("coach-input").closest("form"));

    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1]).toEqual({
      message: "Que retiens-tu de cette séance par rapport à mes sorties similaires ?",
      workout_id: "w28",
      language: "en",
    });
    await waitFor(() => {
      const followUpMessages = screen.getAllByTestId(/^message-/).slice(-2);
      expect(followUpMessages).toHaveLength(2);
      expect(followUpMessages[0]).toHaveAttribute("data-workout-id", "w28");
      expect(followUpMessages[1]).toHaveAttribute("data-workout-id", "w28");
    });
  });

  test("general Coach messages do not invent a workout context", async () => {
    axios.post.mockResolvedValue({ data: { response: "general answer" } });
    render(
      <LanguageProvider>
        <MemoryRouter initialEntries={["/coach"]}>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    await screen.findByTestId("coach-empty-state");
    fireEvent.change(screen.getByTestId("coach-input"), {
      target: { value: "What should I know about this week?" },
    });
    fireEvent.submit(screen.getByTestId("coach-input").closest("form"));

    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    expect(axios.post.mock.calls[0][1]).not.toHaveProperty("workout_id");
    await waitFor(() => {
      expect(screen.getByTestId("message-0")).not.toHaveAttribute("data-workout-id");
      expect(screen.getByTestId("message-1")).not.toHaveAttribute("data-workout-id");
    });
  });

  test("clearing history also clears the active workout context", async () => {
    axios.get.mockImplementation((url) => {
      if (String(url).includes("/coach/history")) {
        return Promise.resolve({ data: [] });
      }
      if (String(url).includes("/workouts/w28")) {
        return Promise.resolve({ data: { name: "Easy Run" } });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
    axios.post.mockResolvedValue({ data: { response: "analysis" } });
    axios.delete.mockResolvedValue({ data: { deleted_count: 2 } });

    render(
      <LanguageProvider>
        <MemoryRouter initialEntries={["/coach?analyze=w28"]}>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("coach-input")).not.toBeDisabled());
    fireEvent.click(await screen.findByTestId("clear-history"));
    await waitFor(() => expect(axios.delete).toHaveBeenCalledTimes(1));
    expect(axios.delete).toHaveBeenCalledWith(expect.stringContaining("/coach/history"));
    expect(await screen.findByTestId("coach-empty-state")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("coach-input"), {
      target: { value: "A general follow-up" },
    });
    fireEvent.submit(screen.getByTestId("coach-input").closest("form"));

    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1]).not.toHaveProperty("workout_id");
  });
});

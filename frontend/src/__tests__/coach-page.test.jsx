import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Coach from "@/pages/Coach";
import { LanguageProvider } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";

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
    useAuth.mockReturnValue({ user: { id: "u1" } });
    axios.get.mockResolvedValue({ data: [] });
  });

  test("empty state stays advisory and does not fabricate a prescription", async () => {
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    expect(await screen.findByText(/only prescription authority/i)).toBeInTheDocument();
    expect(screen.getByText(/Open today and training/i)).toBeInTheDocument();
    expect(screen.queryByText(/Tempo|Intervals|Long run/i)).not.toBeInTheDocument();
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
    expect(screen.queryByText(/only prescription authority/i)).not.toBeInTheDocument();
  });

  test("workout auto-analysis posts only message, workout_id, and language", async () => {
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
        message: expect.any(String),
        workout_id: "workout-42",
        language: "en",
      }
    );
    expect(axios.post.mock.calls[0][1]).not.toHaveProperty("deep_analysis");
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

    await screen.findByText(/only prescription authority/i);
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
    fireEvent.change(screen.getByTestId("coach-input"), {
      target: { value: "A general follow-up" },
    });
    fireEvent.submit(screen.getByTestId("coach-input").closest("form"));

    await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
    expect(axios.post.mock.calls[1][1]).not.toHaveProperty("workout_id");
  });
});

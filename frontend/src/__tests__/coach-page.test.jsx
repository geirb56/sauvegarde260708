import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
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
});

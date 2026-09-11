import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Sessions from "@/pages/Sessions";
import { LanguageProvider } from "@/context/LanguageContext";

jest.mock("axios");
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => ({ unitSystem: "metric" }),
}));

const renderSessions = (workouts) => {
  axios.get.mockResolvedValue({ data: workouts });

  return render(
    <LanguageProvider>
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>
    </LanguageProvider>
  );
};

const buildWorkout = (overrides = {}) => ({
  id: "garmin-1",
  name: "Easy run",
  type: "run",
  date: "2026-09-10T07:00:00Z",
  distance_km: 8.5,
  avg_pace_min_km: 5.5,
  avg_heart_rate: 139,
  ...overrides,
});

describe("Sessions page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("renders a known distance metric", async () => {
    renderSessions([buildWorkout({ distance_km: 10 })]);

    expect(await screen.findByText("10.0 km")).toBeInTheDocument();
  });

  test("omits artificial distance when distance_km is null", async () => {
    renderSessions([buildWorkout({ distance_km: null })]);

    await screen.findByText("5:30 /km");
    expect(screen.queryByText("0.00 km")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0 km")).not.toBeInTheDocument();
  });

  test("renders a known pace metric", async () => {
    renderSessions([buildWorkout({ avg_pace_min_km: 5.5 })]);

    expect(await screen.findByText("5:30 /km")).toBeInTheDocument();
  });

  test("omits artificial pace when avg_pace_min_km is null", async () => {
    renderSessions([buildWorkout({ avg_pace_min_km: null })]);

    expect(await screen.findByText("8.50 km")).toBeInTheDocument();
    expect(screen.queryByText("--")).not.toBeInTheDocument();
    expect(screen.queryByText("0:00 /km")).not.toBeInTheDocument();
  });

  test("renders heart rate truthfully with explicit bpm", async () => {
    renderSessions([
      buildWorkout({ id: "garmin-1", avg_heart_rate: 139 }),
      buildWorkout({ id: "garmin-2", distance_km: 10, avg_pace_min_km: null, avg_heart_rate: null }),
    ]);

    expect(await screen.findByText("139 bpm")).toBeInTheDocument();
    expect(screen.queryByText("0 bpm")).not.toBeInTheDocument();
  });

  test("renders mixed metrics without separator artifacts", async () => {
    const { container } = renderSessions([
      buildWorkout({ distance_km: 10, avg_pace_min_km: null, avg_heart_rate: 139 }),
    ]);

    expect(await screen.findByText("10.0 km")).toBeInTheDocument();
    expect(screen.getByText("139 bpm")).toBeInTheDocument();
    expect(screen.queryByText("5:30 /km")).not.toBeInTheDocument();

    const workoutStats = container.querySelector(".workout-stats");
    expect(workoutStats).not.toBeNull();
    expect(workoutStats.querySelectorAll(".dot")).toHaveLength(1);
    expect(Array.from(workoutStats.querySelectorAll("span")).map((node) => node.textContent)).toEqual([
      "10.0 km",
      "",
      "139 bpm",
    ]);
  });
});

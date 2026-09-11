import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Sessions from "@/pages/Sessions";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";

jest.mock("axios");

describe("Sessions page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    axios.get.mockResolvedValue({
      data: [
        {
          id: "garmin-1",
          name: "Easy run",
          type: "run",
          date: "2026-09-10T07:00:00Z",
          distance_km: 8.5,
          avg_pace_min_km: 5.5,
          avg_heart_rate: 139,
        },
      ],
    });
  });

  test("renders heart rate with explicit bpm units", async () => {
    render(
      <UnitProvider>
        <LanguageProvider>
          <MemoryRouter>
            <Sessions />
          </MemoryRouter>
        </LanguageProvider>
      </UnitProvider>
    );

    expect(await screen.findByText("139 bpm")).toBeInTheDocument();
  });
});

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Progress, { buildVisibleChartTicks } from "@/pages/Progress";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";
import { useSubscription } from "@/context/SubscriptionContext";

jest.mock("axios");
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(),
}));

describe("Progress mobile UX", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    axios.get.mockImplementation((url) => {
      if (url.includes("/stats")) return Promise.resolve({ data: { sessions_7_days: 3, km_7_days: 20, km_30_days: 80 } });
      if (url.includes("/training/race-predictions")) return Promise.resolve({ data: null });
      if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: null });
      if (url.includes("/run-index/history")) {
        return Promise.resolve({
          data: {
            has_data: true,
            current_run_index: 612,
            trend: 4,
            granularity: "week",
            history: [
              { date: "2026-07-01", run_index: 590 },
              { date: "2026-07-15", run_index: 598 },
              { date: "2026-08-01", run_index: 603 },
              { date: "2026-08-15", run_index: 608 },
              { date: "2026-09-01", run_index: 612 },
            ],
            pillars: {
              speed: { current: null, evolution: null },
              endurance: { current: 72, evolution: 2 },
              consistency: { current: 68, evolution: 1 },
              efficiency: { current: null, evolution: null },
            },
          },
        });
      }
      if (url.includes("/run-index")) return Promise.resolve({ data: { metrics: { vo2max_running: 52 } } });
      if (url.includes("/garmin/vo2max-history")) return Promise.resolve({ data: { history: [], current: null } });
      if (url.includes("/garmin/daily-metrics")) return Promise.reject(new Error("not connected"));
      return Promise.resolve({ data: null });
    });
  });

  test("keeps missing pillars as em dashes without inventing a causal explanation", async () => {
    render(
      <UnitProvider>
        <LanguageProvider>
          <MemoryRouter>
            <Progress />
          </MemoryRouter>
        </LanguageProvider>
      </UnitProvider>
    );

    const missingPillars = await screen.findAllByText("—");
    expect(missingPillars.length).toBeGreaterThan(0);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText(/treated as zero/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/historical point/i)).not.toBeInTheDocument();
  });

  test("selects renderable tick density for compact and larger mobile widths", () => {
    const points = [
      { date: "2026-07-01" },
      { date: "2026-07-08" },
      { date: "2026-07-15" },
      { date: "2026-07-22" },
      { date: "2026-07-29" },
      { date: "2026-08-05" },
    ];
    expect(buildVisibleChartTicks(points, 3)).toEqual(["2026-07-01", "2026-07-22", "2026-08-05"]);
    expect(buildVisibleChartTicks(points, 4)).toEqual(["2026-07-01", "2026-07-15", "2026-07-29", "2026-08-05"]);
  });
});

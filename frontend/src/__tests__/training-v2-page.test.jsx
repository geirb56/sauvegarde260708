import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import TrainingPlanV2 from "@/pages/TrainingPlanV2";
import { LanguageProvider } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { UnitProvider } from "@/context/UnitContext";
import { API_BASE_URL } from "@/config";
import { UNIT_SYSTEM_KEY, formatDistance } from "@/utils/units";

jest.mock("axios");
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(),
}));
jest.mock("@/components/Paywall", () => function MockPaywall() {
  return <div data-testid="paywall">Paywall</div>;
});

const FORBIDDEN_ENDPOINTS = [
  "/training/plan",
  "/training/full-cycle",
  "/training/metrics",
  "/training/week-plan",
  "/training/refresh",
];

function buildResponse({ targetBasis = "distance", includeRestTss = true } = {}) {
  return {
    reference_date: "2026-08-18",
    goal: {
      goal_type: "MARATHON",
      race_date: "2026-10-05",
      target_time_seconds: 11700,
    },
    state: {
      continuity_state: "normal",
      allow_intensity: true,
    },
    weekly_target: {
      target_basis: targetBasis,
      target_km: targetBasis === "distance" ? 52.5 : null,
      target_duration_minutes: targetBasis === "duration" ? 210 : null,
      session_count: 5,
      confidence: "high",
    },
    week: {
      planned_km: targetBasis === "distance" ? 52.5 : null,
      planned_duration_minutes: targetBasis === "duration" ? 210 : null,
      session_count: 5,
      sessions: [
        { day: "monday", workout_type: "easy", intensity_class: "low", distance_km: targetBasis === "distance" ? 8 : null, duration_minutes: targetBasis === "duration" ? 45 : null, estimated_tss: null, reason_codes: [] },
        { day: "tuesday", workout_type: "quality", intensity_class: "high", distance_km: targetBasis === "distance" ? 10 : null, duration_minutes: targetBasis === "duration" ? 50 : null, estimated_tss: null, reason_codes: [] },
        { day: "wednesday", workout_type: "recovery", intensity_class: "low", distance_km: targetBasis === "distance" ? 6 : null, duration_minutes: targetBasis === "duration" ? 35 : null, estimated_tss: null, reason_codes: [] },
        { day: "thursday", workout_type: "steady", intensity_class: "moderate", distance_km: targetBasis === "distance" ? 8.5 : null, duration_minutes: targetBasis === "duration" ? 40 : null, estimated_tss: null, reason_codes: [] },
        { day: "friday", workout_type: "rest", intensity_class: "rest", distance_km: null, duration_minutes: null, estimated_tss: includeRestTss ? 0 : null, reason_codes: [] },
        { day: "saturday", workout_type: "long_easy", intensity_class: "moderate", distance_km: targetBasis === "distance" ? 20 : null, duration_minutes: targetBasis === "duration" ? 70 : null, estimated_tss: null, reason_codes: [] },
        { day: "sunday", workout_type: "rest", intensity_class: "rest", distance_km: null, duration_minutes: null, estimated_tss: includeRestTss ? 0 : null, reason_codes: [] },
      ],
    },
  };
}

function renderPage({ unitSystem = "metric" } = {}) {
  window.localStorage.setItem(UNIT_SYSTEM_KEY, unitSystem);
  return render(
    <UnitProvider>
      <LanguageProvider>
        <MemoryRouter>
          <TrainingPlanV2 />
        </MemoryRouter>
      </LanguageProvider>
    </UnitProvider>
  );
}

describe("TrainingPlanV2", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    useSubscription.mockReturnValue({
      isFree: false,
      loading: false,
    });
  });

  it("shows the existing paywall for FREE and never fetches V2", () => {
    useSubscription.mockReturnValue({
      isFree: true,
      loading: false,
    });

    renderPage();

    expect(screen.getByTestId("paywall")).toBeInTheDocument();
    expect(axios.get).not.toHaveBeenCalled();
  });

  it("fetches /training/v2/week for TRIAL/PREMIUM", async () => {
    axios.get.mockResolvedValue({ data: buildResponse() });

    renderPage();

    await waitFor(() => {
      expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/week`);
    });
  });

  it("never calls forbidden legacy training endpoints", async () => {
    axios.get.mockResolvedValue({ data: buildResponse() });

    renderPage();

    await waitFor(() => {
      expect(axios.get).toHaveBeenCalledWith(`${API_BASE_URL}/training/v2/week`);
    });

    const calledUrls = axios.get.mock.calls.map(([url]) => url);
    expect(calledUrls).toEqual([`${API_BASE_URL}/training/v2/week`]);
    FORBIDDEN_ENDPOINTS.forEach((endpoint) => {
      expect(calledUrls.some((url) => url.includes(endpoint))).toBe(false);
    });
  });

  it("renders distance basis via UnitContext in metric", async () => {
    axios.get.mockResolvedValue({ data: buildResponse({ targetBasis: "distance" }) });

    renderPage({ unitSystem: "metric" });

    expect(await screen.findByText(formatDistance(52.5, { unitSystem: "metric" }))).toBeInTheDocument();
    expect(screen.getByText(formatDistance(8, { unitSystem: "metric" }))).toBeInTheDocument();
    expect(screen.queryByText("0 min")).not.toBeInTheDocument();
  });

  it("renders duration basis in minutes without converting unknown distance to 0", async () => {
    axios.get.mockResolvedValue({ data: buildResponse({ targetBasis: "duration" }) });

    renderPage();

    expect(await screen.findByText("210 min")).toBeInTheDocument();
    expect(screen.queryByText("0 km")).not.toBeInTheDocument();
  });

  it("renders distance basis via UnitContext in imperial without forcing km", async () => {
    axios.get.mockResolvedValue({ data: buildResponse({ targetBasis: "distance" }) });

    renderPage({ unitSystem: "imperial" });

    expect(await screen.findByText(formatDistance(52.5, { unitSystem: "imperial" }))).toBeInTheDocument();
    expect(screen.getByText(formatDistance(8, { unitSystem: "imperial" }))).toBeInTheDocument();
    expect(screen.queryByText(/\bkm\b/)).not.toBeInTheDocument();
  });

  it("does not render an empty badge for REST days with unknown metrics", async () => {
    axios.get.mockResolvedValue({ data: buildResponse({ includeRestTss: false }) });

    renderPage();

    const fridayCard = await screen.findByTestId("training-v2-day-friday");
    expect(within(fridayCard).queryByText("—")).not.toBeInTheDocument();
    expect(within(fridayCard).queryByText("0 km")).not.toBeInTheDocument();
    expect(within(fridayCard).queryByText("0 min")).not.toBeInTheDocument();
    expect(within(fridayCard).queryByText("0 TSS")).not.toBeInTheDocument();
  });

  it("never shows 0 TSS when estimated_tss is null", async () => {
    axios.get.mockResolvedValue({ data: buildResponse({ includeRestTss: false }) });

    renderPage();

    await screen.findByTestId("training-v2-day-sunday");
    expect(screen.queryByText("0 TSS")).not.toBeInTheDocument();
  });

  it("preserves a valid 0 TSS on REST days when provided", async () => {
    axios.get.mockResolvedValue({ data: buildResponse({ includeRestTss: true }) });

    renderPage();

    const fridayCard = await screen.findByTestId("training-v2-day-friday");
    expect(within(fridayCard).getByText("0 TSS")).toBeInTheDocument();
  });

  it("renders the seven Monday to Sunday day cards", async () => {
    axios.get.mockResolvedValue({ data: buildResponse() });

    renderPage();

    await screen.findByTestId("training-v2-day-sunday");

    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].forEach((day) => {
      expect(screen.getByTestId(`training-v2-day-${day}`)).toBeInTheDocument();
    });
  });
});

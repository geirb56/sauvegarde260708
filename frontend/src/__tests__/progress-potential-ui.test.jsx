import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Progress from "@/pages/Progress";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";
import { useSubscription } from "@/context/SubscriptionContext";

jest.mock("axios");
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(),
}));

const BASE_STATS = { sessions_7_days: 4, km_7_days: 28, km_30_days: 96 };
const BASE_RUN_INDEX = { metrics: { vo2max_running: 52 } };
const BASE_HISTORY = {
  has_data: true,
  current_run_index: 620,
  trend: 6,
  granularity: "week",
  history: [{ date: "2026-09-01", run_index: 620 }],
  pillars: {
    speed: { current: 70, evolution: 3 },
    endurance: { current: 71, evolution: 2 },
    consistency: { current: 68, evolution: 1 },
    efficiency: { current: 69, evolution: 2 },
  },
};

const VALID_PREDICTIONS = {
  has_data: true,
  predictions: [
    { distance: "5K", predicted_time_s: 1500, predicted_time: "24:59", predicted_pace: "5:00/km", confidence: "HIGH" },
    { distance: "10K", predicted_time_s: 3150, predicted_time: "52:29", predicted_pace: "5:15/km", confidence: "MEDIUM" },
    { distance: "Semi", predicted_time_s: 6900, predicted_time: "1:55:00", predicted_pace: "5:27/km", confidence: "LOW" },
    { distance: "Marathon", predicted_time_s: 14500, predicted_time: "4:01:40", predicted_pace: "5:44/km", confidence: "HIGH" },
  ],
};

const renderProgress = ({ lang = "en", width = 390 } = {}) => {
  Object.defineProperty(window, "innerWidth", { value: width, writable: true, configurable: true });
  window.localStorage.setItem("runindex_lang", lang);
  return render(
    <UnitProvider>
      <LanguageProvider>
        <MemoryRouter>
          <Progress />
        </MemoryRouter>
      </LanguageProvider>
    </UnitProvider>,
  );
};

const setupAxios = ({
  predictionsData = VALID_PREDICTIONS,
  predictionsReject = false,
  keepLoading = false,
  keepPredictionsLoading = false,
} = {}) => {
  axios.get.mockImplementation((url) => {
    if (url.includes("/stats")) return keepLoading ? new Promise(() => {}) : Promise.resolve({ data: BASE_STATS });
    if (url.includes("/training/race-predictions")) {
      if (keepPredictionsLoading) return new Promise(() => {});
      return predictionsReject
        ? Promise.reject(new Error("race predictions unavailable"))
        : Promise.resolve({ data: predictionsData });
    }
    if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: { goal: { goal_type: "half_marathon" } } });
    if (url.includes("/run-index/history")) return Promise.resolve({ data: BASE_HISTORY });
    if (url.includes("/run-index")) return Promise.resolve({ data: BASE_RUN_INDEX });
    if (url.includes("/garmin/vo2max-history")) return Promise.resolve({ data: { history: [], current: null } });
    if (url.includes("/garmin/daily-metrics")) return Promise.reject(new Error("garmin unavailable"));
    return Promise.resolve({ data: null });
  });
};

describe("Progress potential UI", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
  });

  test("renders 5K/10K/Half/Marathon with formatted times and confidence labels", async () => {
    setupAxios();
    renderProgress({ lang: "en", width: 390 });

    expect(await screen.findByText("Potential")).toBeInTheDocument();
    expect(await screen.findByText("5K")).toBeInTheDocument();
    expect(await screen.findByText("10K")).toBeInTheDocument();
    expect(await screen.findByText("Half")).toBeInTheDocument();
    expect(await screen.findByText("Marathon")).toBeInTheDocument();

    expect(await screen.findByText("25:00")).toBeInTheDocument();
    expect(await screen.findByText("52:30")).toBeInTheDocument();
    expect(await screen.findByText("1:55:00")).toBeInTheDocument();
    expect(await screen.findByText("4:01:40")).toBeInTheDocument();

    expect(await screen.findAllByText("High")).toHaveLength(2);
    expect(await screen.findByText("Medium")).toBeInTheDocument();
    expect(await screen.findByText("Low")).toBeInTheDocument();
  });

  test("none != 0: missing prediction never shows 0:00", async () => {
    setupAxios({
      predictionsData: {
        has_data: true,
        predictions: [
          { distance: "5K", predicted_time_s: null, predicted_time: null, predicted_pace: null, confidence: "INSUFFICIENT" },
          { distance: "10K", predicted_time_s: 3150, predicted_time: "52:29", predicted_pace: "5:15/km", confidence: "MEDIUM" },
          { distance: "Semi", predicted_time_s: 6900, predicted_time: "1:55:00", predicted_pace: "5:27/km", confidence: "LOW" },
          { distance: "Marathon", predicted_time_s: 14500, predicted_time: "4:01:40", predicted_pace: "5:44/km", confidence: "HIGH" },
        ],
      },
    });
    renderProgress();

    expect(await screen.findByText("Not enough data")).toBeInTheDocument();
    expect(screen.queryByText("0:00")).not.toBeInTheDocument();
  });

  test("insufficient payload shows honest state and no synthetic values", async () => {
    setupAxios({ predictionsData: { has_data: false, predictions: [] } });
    renderProgress();

    expect(await screen.findByTestId("potential-insufficient-data")).toBeInTheDocument();
    expect(await screen.findByText("Not enough data yet")).toBeInTheDocument();
    expect(screen.queryByText("25:00")).not.toBeInTheDocument();
    expect(screen.queryByText("0:00")).not.toBeInTheDocument();
  });

  test("loading state does not flash fake values", async () => {
    setupAxios({ keepLoading: true });
    renderProgress();

    expect(screen.queryByText("0:00")).not.toBeInTheDocument();
    expect(screen.queryByText("Potential")).not.toBeInTheDocument();
  });

  test("potential loading skeleton is rendered while predictions request is pending", async () => {
    setupAxios({ keepPredictionsLoading: true });
    renderProgress();

    expect(await screen.findByTestId("potential-loading")).toBeInTheDocument();
    expect(screen.queryByText("0:00")).not.toBeInTheDocument();
  });

  test("error state shows compact retry and no invented predictions", async () => {
    setupAxios({ predictionsReject: true });
    renderProgress();

    expect(await screen.findByTestId("potential-error")).toBeInTheDocument();
    expect(await screen.findByText("Retry")).toBeInTheDocument();
    expect(screen.queryByText("25:00")).not.toBeInTheDocument();
  });

  test("retry recovers potential cards after an initial error", async () => {
    let predictionCalls = 0;
    axios.get.mockImplementation((url) => {
      if (url.includes("/stats")) return Promise.resolve({ data: BASE_STATS });
      if (url.includes("/training/race-predictions")) {
        predictionCalls += 1;
        if (predictionCalls === 1) return Promise.reject(new Error("temporary failure"));
        return Promise.resolve({ data: VALID_PREDICTIONS });
      }
      if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: { goal: { goal_type: "half_marathon" } } });
      if (url.includes("/run-index/history")) return Promise.resolve({ data: BASE_HISTORY });
      if (url.includes("/run-index")) return Promise.resolve({ data: BASE_RUN_INDEX });
      if (url.includes("/garmin/vo2max-history")) return Promise.resolve({ data: { history: [], current: null } });
      if (url.includes("/garmin/daily-metrics")) return Promise.reject(new Error("garmin unavailable"));
      return Promise.resolve({ data: null });
    });

    renderProgress();
    const retryButton = await screen.findByText("Retry");
    fireEvent.click(retryButton);

    expect(await screen.findByTestId("potential-cards-grid")).toBeInTheDocument();
    expect(await screen.findByText("25:00")).toBeInTheDocument();
  });

  test("FR/EN/ES render translated potential text (no raw key)", async () => {
    setupAxios();
    const { unmount } = renderProgress({ lang: "fr" });
    expect(await screen.findByText("Potentiel")).toBeInTheDocument();
    expect(screen.queryByText("progressExtended.potentialTitle")).not.toBeInTheDocument();
    unmount();

    setupAxios();
    const en = renderProgress({ lang: "en" });
    expect(await screen.findByText("Potential")).toBeInTheDocument();
    expect(screen.queryByText("progressExtended.potentialTitle")).not.toBeInTheDocument();
    en.unmount();

    setupAxios();
    renderProgress({ lang: "es" });
    expect(await screen.findByText("Potencial")).toBeInTheDocument();
    expect(screen.queryByText("progressExtended.potentialTitle")).not.toBeInTheDocument();
  });

  test("mobile width shows potential block and all 4 cards without desktop dependency", async () => {
    setupAxios();
    renderProgress({ width: 390 });

    expect(await screen.findByTestId("potential-section")).toBeInTheDocument();
    expect(await screen.findByTestId("potential-cards-grid")).toBeInTheDocument();
    expect(await screen.findByTestId("potential-card-5k")).toBeInTheDocument();
    expect(await screen.findByTestId("potential-card-10k")).toBeInTheDocument();
    expect(await screen.findByTestId("potential-card-semi")).toBeInTheDocument();
    expect(await screen.findByTestId("potential-card-marathon")).toBeInTheDocument();
  });
});

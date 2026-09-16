import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Onboarding from "@/pages/Onboarding";
import { LanguageProvider, useLanguage } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

const mockNavigate = jest.fn();
const mockRefreshSubscription = jest.fn(() => Promise.resolve({ accessRefreshSucceeded: true }));
let mockSubscriptionState = {};
let mockSyncState = {};
const mockUseGarminSyncProgress = jest.fn();

jest.mock("react-router-dom", () => {
  const actual = jest.requireActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({
    refreshSubscription: mockRefreshSubscription,
    isTrial: false,
    isPremium: false,
    trialDaysRemaining: null,
    ...mockSubscriptionState,
  }),
}));

jest.mock("@/hooks/useGarminSyncProgress", () => ({
  useGarminSyncProgress: (...args) => mockUseGarminSyncProgress(...args),
}));

function OnboardingWithLangControls() {
  const { setLang } = useLanguage();
  return (
    <>
      <button type="button" data-testid="set-lang-fr" onClick={() => setLang("fr")}>
        fr
      </button>
      <Onboarding />
    </>
  );
}

function renderOnboarding({ lang = "en", withLangControls = false } = {}) {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  return render(
    <LanguageProvider>
      <MemoryRouter>
        {withLangControls ? <OnboardingWithLangControls /> : <Onboarding />}
      </MemoryRouter>
    </LanguageProvider>
  );
}

function mockSuccessfulPostFlow() {
  axios.post.mockImplementation((url) => {
    if (url.includes("/garmin/connect")) {
      return Promise.resolve({ data: { status: "connected" } });
    }
    if (url.includes("/garmin/sync")) {
      return Promise.resolve({ data: { synced_count: 8 } });
    }
    if (url.includes("/training/set-goal")) {
      return Promise.resolve({ data: { ok: true } });
    }
    if (url.includes("/training/refresh")) {
      return Promise.resolve({ data: { ok: true } });
    }
    return Promise.reject(new Error(`Unexpected POST ${url}`));
  });
}

function setupFirstValueGetMocks({
  pacesData = null,
  pacesError = null,
  todayData = null,
  todayError = null,
} = {}) {
  axios.get.mockImplementation((url) => {
    if (String(url).includes("/training/v2/paces")) {
      if (pacesError) return Promise.reject(pacesError);
      return Promise.resolve({ data: pacesData });
    }
    if (String(url).includes("/training/today")) {
      if (todayError) return Promise.reject(todayError);
      return Promise.resolve({ data: todayData });
    }
    return Promise.resolve({ data: {} });
  });
}

function endpointCalls(pathFragment) {
  return axios.get.mock.calls.filter(([url]) => String(url).includes(pathFragment)).length;
}

async function connectGarminAndReachSync() {
  fireEvent.click(screen.getByTestId("onboarding-start"));
  fireEvent.change(await screen.findByTestId("garmin-email-input"), {
    target: { value: "runner@example.com" },
  });
  fireEvent.change(screen.getByTestId("garmin-password-input"), {
    target: { value: "Password123!" },
  });
  fireEvent.click(screen.getByTestId("garmin-connect"));
  await waitFor(() => expect(mockRefreshSubscription).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByTestId("onboarding-continue"));
  await waitFor(() => expect(screen.getByTestId("onboarding-step-sync")).toBeInTheDocument());
}

async function reachFirstValueStep() {
  await connectGarminAndReachSync();
  fireEvent.click(screen.getByTestId("onboarding-continue"));
  await waitFor(() => expect(screen.getByTestId("onboarding-step-first-value")).toBeInTheDocument());
}

describe("Onboarding first connection activation (paces + today)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockNavigate.mockReset();
    mockRefreshSubscription.mockResolvedValue({ accessRefreshSucceeded: true });
    window.localStorage.clear();
    mockSubscriptionState = { hasPremiumAccess: true };
    mockSyncState = {
      progress: { status: "complete", run_index_status: "ready", run_index: 72, readiness_status: "ready", readiness: 81, activities_count: 8 },
      isStreaming: false,
      error: null,
    };
    mockUseGarminSyncProgress.mockImplementation(() => mockSyncState);
    mockSuccessfulPostFlow();
  });

  test("A. complete first value activation: paces + today workout with independent endpoint calls", async () => {
    setupFirstValueGetMocks({
      pacesData: {
        confidence: "HIGH",
        paces: {
          easy: { lower: { min_per_km: 5.0 }, upper: { min_per_km: 5.5 } },
          threshold: { min_per_km: 4.2 },
        },
      },
      todayData: {
        status: "success",
        served_prescription: { type: "threshold", duration: 45, details: "3 x 8 min @ threshold" },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    await waitFor(() => expect(screen.getByTestId("first-paces-easy")).toBeInTheDocument());
    expect(screen.getByTestId("first-paces-easy")).toHaveTextContent("5:00 /km - 5:30 /km");
    expect(screen.getByTestId("first-paces-threshold")).toHaveTextContent("4:12 /km");
    expect(screen.getByTestId("first-today-success")).toHaveTextContent("Threshold");
    expect(screen.getByTestId("first-today-duration")).toHaveTextContent("45 min");
    expect(screen.getByTestId("first-today-details")).toHaveTextContent("3 x 8 min @ threshold");
    expect(endpointCalls("/training/v2/paces")).toBe(1);
    expect(endpointCalls("/training/today")).toBe(1);
  });

  test("B. today rest is displayed as factual rest", async () => {
    setupFirstValueGetMocks({
      pacesData: { confidence: "INSUFFICIENT", paces: {} },
      todayData: {
        status: "success",
        served_prescription: { type: "rest", details: "Complete rest" },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-today-success")).toBeInTheDocument();
    expect(screen.getByTestId("first-today-success")).toHaveTextContent("Rest");
    expect(screen.getByTestId("first-today-success")).not.toHaveTextContent(/ready/i);
    expect(screen.getByTestId("first-paces-insufficient")).toBeInTheDocument();
  });

  test("C. today no_session shows truthful unavailable state without fabricated workout", async () => {
    setupFirstValueGetMocks({
      pacesData: { confidence: "HIGH", paces: { threshold: { min_per_km: 4.2 } } },
      todayData: {
        status: "no_session",
        message: "No session planned for today",
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-today-unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("first-today-unavailable")).toHaveTextContent("No session planned for today");
    expect(screen.queryByTestId("first-today-success")).toBeNull();
  });

  test("D. today technical error shows dedicated error state and remains continuable", async () => {
    setupFirstValueGetMocks({
      pacesData: { confidence: "HIGH", paces: { threshold: { min_per_km: 4.2 } } },
      todayError: new Error("network"),
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-today-error")).toBeInTheDocument();
    expect(screen.queryByTestId("first-today-unavailable")).toBeNull();
    expect(screen.getByTestId("onboarding-continue")).not.toBeDisabled();
  });

  test("E. paces success + today failure keeps paces visible with today technical error", async () => {
    setupFirstValueGetMocks({
      pacesData: {
        confidence: "HIGH",
        paces: { easy: { lower: { min_per_km: 5.0 }, upper: { min_per_km: 5.4 } } },
      },
      todayError: new Error("timeout"),
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-easy")).toBeInTheDocument();
    expect(screen.getByTestId("first-today-error")).toBeInTheDocument();
  });

  test("F. today success + paces insufficient keeps today visible", async () => {
    setupFirstValueGetMocks({
      pacesData: { confidence: "INSUFFICIENT", paces: {} },
      todayData: {
        status: "success",
        served_prescription: { type: "easy", duration: 35 },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-insufficient")).toBeInTheDocument();
    expect(screen.getByTestId("first-today-success")).toHaveTextContent("Easy run");
  });

  test("G. today success + paces failure keeps today visible with paces technical error", async () => {
    setupFirstValueGetMocks({
      pacesError: new Error("paces failed"),
      todayData: {
        status: "success",
        served_prescription: { type: "threshold", duration: 50 },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-error")).toBeInTheDocument();
    expect(screen.getByTestId("first-today-success")).toHaveTextContent("Threshold");
  });

  test("H. terminal sync error does not trigger paces/today activation fetches", async () => {
    mockSyncState = {
      progress: { status: "failed", run_index_status: "pending", readiness_status: "pending", activities_count: 8 },
      isStreaming: false,
      error: "session_unavailable",
    };
    mockUseGarminSyncProgress.mockImplementation(() => mockSyncState);
    setupFirstValueGetMocks({
      pacesData: { confidence: "HIGH", paces: { threshold: { min_per_km: 4.2 } } },
      todayData: { status: "success", served_prescription: { type: "easy", duration: 40 } },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(endpointCalls("/training/v2/paces")).toBe(0);
    expect(endpointCalls("/training/today")).toBe(0);
    expect(screen.queryByTestId("first-paces-section")).toBeNull();
    expect(screen.queryByTestId("first-today-section")).toBeNull();
    expect(screen.getByTestId("runindex-terminal-error")).toBeInTheDocument();
  });

  test("I. completed sync with runindex insufficient still fetches and renders activation truths", async () => {
    mockSyncState = {
      progress: { status: "partial_success", run_index_status: "insufficient_data", readiness_status: "insufficient_data", activities_count: 2 },
      isStreaming: false,
      error: null,
    };
    mockUseGarminSyncProgress.mockImplementation(() => mockSyncState);
    setupFirstValueGetMocks({
      pacesData: { confidence: "INSUFFICIENT", paces: {} },
      todayData: {
        status: "success",
        served_prescription: { type: "recovery", duration: 30 },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-insufficient")).toBeInTheDocument();
    expect(screen.getByTestId("first-today-success")).toHaveTextContent("Recovery");
    expect(screen.getByTestId("runindex-insufficient-data")).toBeInTheDocument();
    expect(endpointCalls("/training/v2/paces")).toBe(1);
    expect(endpointCalls("/training/today")).toBe(1);
  });

  test("J. language change rerenders labels without refetching paces or today", async () => {
    setupFirstValueGetMocks({
      pacesData: {
        confidence: "HIGH",
        paces: { threshold: { min_per_km: 4.2 } },
      },
      todayData: {
        status: "success",
        served_prescription: { type: "threshold", duration: 45 },
      },
    });

    renderOnboarding({ withLangControls: true });
    await reachFirstValueStep();
    await waitFor(() => expect(screen.getByText("Today's session")).toBeInTheDocument());

    const pacesBefore = endpointCalls("/training/v2/paces");
    const todayBefore = endpointCalls("/training/today");
    fireEvent.click(screen.getByTestId("set-lang-fr"));

    await waitFor(() => expect(screen.getByText("Séance du jour")).toBeInTheDocument());
    expect(endpointCalls("/training/v2/paces")).toBe(pacesBefore);
    expect(endpointCalls("/training/today")).toBe(todayBefore);
  });

  test("K. free users never call premium paces/today endpoints", async () => {
    mockSubscriptionState = { hasPremiumAccess: false };
    setupFirstValueGetMocks({
      pacesData: { confidence: "HIGH", paces: { threshold: { min_per_km: 4.2 } } },
      todayData: { status: "success", served_prescription: { type: "easy", duration: 20 } },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(endpointCalls("/training/v2/paces")).toBe(0);
    expect(endpointCalls("/training/today")).toBe(0);
    expect(screen.queryByTestId("first-paces-section")).toBeNull();
    expect(screen.queryByTestId("first-today-section")).toBeNull();
  });

  test("L. activation UI does not leak vdot, predicted time, race references, or reason codes", async () => {
    setupFirstValueGetMocks({
      pacesData: {
        confidence: "HIGH",
        predicted_time: { "5k": "20:00" },
        vdot: 52.4,
        race_references: { marathon: { pace: { min_per_km: 5.1 } } },
        paces: { threshold: { min_per_km: 4.2 } },
      },
      todayData: {
        status: "success",
        adaptation_reason: "internal-code",
        adaptation_reason_codes: ["foo", "bar"],
        served_prescription: { type: "threshold", duration: 40 },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-threshold")).toBeInTheDocument();
    expect(screen.queryByText(/vdot/i)).toBeNull();
    expect(screen.queryByText(/predicted/i)).toBeNull();
    expect(screen.queryByText(/5k/i)).toBeNull();
    expect(screen.queryByText(/marathon/i)).toBeNull();
    expect(screen.queryByText(/internal-code/i)).toBeNull();
  });
});

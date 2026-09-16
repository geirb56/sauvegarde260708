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

describe("Onboarding first paces activation", () => {
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

  test("premium known sync fetches paces once and renders easy + threshold", async () => {
    axios.get.mockResolvedValue({
      data: {
        confidence: "HIGH",
        paces: {
          easy: { lower: { min_per_km: 5.0 }, upper: { min_per_km: 5.5 } },
          threshold: { min_per_km: 4.2 },
        },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    await waitFor(() => expect(axios.get).toHaveBeenCalledWith(expect.stringMatching(/\/training\/v2\/paces$/)));
    expect(axios.get).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("first-paces-easy")).toHaveTextContent("5:00 /km - 5:30 /km");
    expect(screen.getByTestId("first-paces-threshold")).toHaveTextContent("4:12 /km");
  });

  test("easy range uses canonical formatted lower + upper values", async () => {
    axios.get.mockResolvedValue({
      data: {
        confidence: "MEDIUM",
        paces: {
          easy: { lower: { min_per_km: 5.05 }, upper: { min_per_km: 5.16 } },
        },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    await waitFor(() => expect(screen.getByTestId("first-paces-easy")).toBeInTheDocument());
    expect(screen.getByTestId("first-paces-easy")).toHaveTextContent("5:03 /km - 5:10 /km");
    expect(screen.queryByTestId("first-paces-threshold")).toBeNull();
  });

  test("confidence insufficient shows honest message and onboarding remains continuable", async () => {
    axios.get.mockResolvedValue({
      data: {
        confidence: "INSUFFICIENT",
        paces: {
          easy: { lower: { min_per_km: 5.0 }, upper: { min_per_km: 5.5 } },
          threshold: { min_per_km: 4.2 },
        },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-insufficient")).toBeInTheDocument();
    expect(screen.queryByTestId("first-paces-easy")).toBeNull();
    expect(screen.queryByTestId("first-paces-threshold")).toBeNull();
    expect(screen.getByTestId("onboarding-continue")).not.toBeDisabled();
  });

  test("paces http error shows technical error and not insufficient", async () => {
    axios.get.mockRejectedValue(new Error("network"));

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-error")).toBeInTheDocument();
    expect(screen.queryByTestId("first-paces-insufficient")).toBeNull();
    expect(screen.getByTestId("onboarding-continue")).not.toBeDisabled();
  });

  test("partial payload shows only available easy pace without inventing threshold", async () => {
    axios.get.mockResolvedValue({
      data: {
        confidence: "LOW",
        paces: {
          easy: { lower: { min_per_km: 5.1 }, upper: { min_per_km: 5.4 } },
          threshold: {},
        },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-easy")).toBeInTheDocument();
    expect(screen.queryByTestId("first-paces-threshold")).toBeNull();
  });

  test("free users never call /training/v2/paces", async () => {
    mockSubscriptionState = { hasPremiumAccess: false };
    axios.get.mockResolvedValue({ data: {} });

    renderOnboarding();
    await reachFirstValueStep();

    await waitFor(() => expect(screen.getByTestId("onboarding-step-first-value")).toBeInTheDocument());
    expect(axios.get).not.toHaveBeenCalled();
    expect(screen.queryByTestId("first-paces-section")).toBeNull();
  });

  test("language change rerenders labels without refetching /training/v2/paces", async () => {
    axios.get.mockResolvedValue({
      data: {
        confidence: "HIGH",
        paces: {
          easy: { lower: { min_per_km: 5.0 }, upper: { min_per_km: 5.5 } },
          threshold: { min_per_km: 4.2 },
        },
      },
    });

    renderOnboarding({ withLangControls: true });
    await reachFirstValueStep();

    await waitFor(() => expect(screen.getByText("Your first training paces")).toBeInTheDocument());
    const callsBefore = axios.get.mock.calls.filter(([url]) => String(url).includes("/training/v2/paces")).length;

    fireEvent.click(screen.getByTestId("set-lang-fr"));

    await waitFor(() => expect(screen.getByText("Tes premières allures")).toBeInTheDocument());
    const callsAfter = axios.get.mock.calls.filter(([url]) => String(url).includes("/training/v2/paces")).length;
    expect(callsAfter).toBe(callsBefore);
  });

  test("onboarding paces section does not leak vdot, predicted time, or race references", async () => {
    axios.get.mockResolvedValue({
      data: {
        confidence: "HIGH",
        predicted_time: { "5k": "20:00" },
        vdot: 52.4,
        race_references: {
          "5k": { pace: { min_per_km: 4.0 } },
          marathon: { pace: { min_per_km: 5.1 } },
        },
        paces: {
          easy: { lower: { min_per_km: 5.0 }, upper: { min_per_km: 5.4 } },
          threshold: { min_per_km: 4.2 },
        },
      },
    });

    renderOnboarding();
    await reachFirstValueStep();

    expect(await screen.findByTestId("first-paces-success")).toBeInTheDocument();
    expect(screen.queryByText(/vdot/i)).toBeNull();
    expect(screen.queryByText(/predicted/i)).toBeNull();
    expect(screen.queryByText(/5k/i)).toBeNull();
    expect(screen.queryByText(/marathon/i)).toBeNull();
  });
});

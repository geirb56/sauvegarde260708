import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Onboarding from "@/pages/Onboarding";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

const mockNavigate = jest.fn();
const mockRefreshSubscription = jest.fn(() => Promise.resolve());
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
    ...mockSubscriptionState,
  }),
}));

jest.mock("@/hooks/useGarminSyncProgress", () => ({
  useGarminSyncProgress: (...args) => mockUseGarminSyncProgress(...args),
}));

function renderOnboarding(lang = "en") {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  return render(
    <LanguageProvider>
      <MemoryRouter>
        <Onboarding />
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

async function connectGarmin() {
  fireEvent.click(screen.getByTestId("onboarding-start"));
  fireEvent.change(await screen.findByTestId("garmin-email-input"), {
    target: { value: "runner@example.com" },
  });
  fireEvent.change(screen.getByTestId("garmin-password-input"), {
    target: { value: "Password123!" },
  });
  fireEvent.click(screen.getByTestId("garmin-connect"));
  await waitFor(() => expect(mockRefreshSubscription).toHaveBeenCalledTimes(1));
}

async function goToDoneStep() {
  await connectGarmin();

  fireEvent.click(screen.getByTestId("onboarding-continue"));
  await waitFor(() => expect(screen.getByTestId("onboarding-step-sync")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("onboarding-continue"));
  await waitFor(() => expect(screen.getByTestId("onboarding-step-first-value")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("onboarding-continue"));
  await waitFor(() => expect(screen.getByTestId("onboarding-step-goal")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("onboarding-goal-5k"));
  fireEvent.click(screen.getByTestId("onboarding-continue"));
  await waitFor(() => expect(screen.getByTestId("onboarding-step-sessions")).toBeInTheDocument());

  fireEvent.click(screen.getByTestId("onboarding-sessions-3"));
  fireEvent.click(screen.getByTestId("onboarding-continue"));

  await waitFor(() => expect(screen.getByTestId("onboarding-step-done")).toBeInTheDocument());
  await waitFor(() => expect(mockRefreshSubscription).toHaveBeenCalledTimes(2));
}

describe("Onboarding trial handoff", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockNavigate.mockReset();
    mockRefreshSubscription.mockResolvedValue(undefined);
    window.localStorage.clear();
    mockSubscriptionState = {
      hasPremiumAccess: true,
      isTrial: true,
      isPremium: false,
      isFree: false,
      trialDaysRemaining: 30,
    };
    mockSyncState = {
      progress: { status: "complete", run_index_status: "ready", run_index: 72, readiness_status: "pending", activities_count: 8 },
      isStreaming: false,
      error: null,
    };
    mockUseGarminSyncProgress.mockImplementation(() => mockSyncState);
    mockSuccessfulPostFlow();
  });

  test("eligible trial shows backend trial status and refreshes before final navigation", async () => {
    renderOnboarding();

    await goToDoneStep();

    expect(screen.getByTestId("onboarding-subscription-status")).toHaveTextContent("Premium Trial — 30 days left");
    expect(axios.post.mock.calls.some(([url]) => String(url).includes("/subscription/start-trial"))).toBe(false);

    fireEvent.click(screen.getByTestId("onboarding-dashboard-cta"));

    await waitFor(() => expect(mockRefreshSubscription).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/"));
  });

  test("french trial status uses localized day countdown", async () => {
    mockSubscriptionState = {
      hasPremiumAccess: true,
      isTrial: true,
      isPremium: false,
      isFree: false,
      trialDaysRemaining: 12,
    };

    renderOnboarding("fr");
    await goToDoneStep();

    expect(screen.getByTestId("onboarding-subscription-status")).toHaveTextContent("Essai Premium — J-12");
  });

  test("free users do not see a false trial status on the final step", async () => {
    mockSubscriptionState = {
      hasPremiumAccess: false,
      isTrial: false,
      isPremium: false,
      isFree: true,
      trialDaysRemaining: null,
    };

    renderOnboarding();
    await goToDoneStep();

    expect(screen.getByTestId("onboarding-subscription-status")).toHaveTextContent("Free");
    expect(screen.getByTestId("onboarding-subscription-status")).not.toHaveTextContent("Trial");
  });

  test("paid premium users do not see a false trial label on the final step", async () => {
    mockSubscriptionState = {
      hasPremiumAccess: true,
      isTrial: false,
      isPremium: true,
      isFree: false,
      trialDaysRemaining: null,
    };

    renderOnboarding();
    await goToDoneStep();

    expect(screen.getByTestId("onboarding-subscription-status")).toHaveTextContent("Premium");
    expect(screen.getByTestId("onboarding-subscription-status")).not.toHaveTextContent("Trial");
  });

  test("final handoff surfaces refresh failure and keeps the user on onboarding", async () => {
    mockRefreshSubscription
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("refresh failed"));

    renderOnboarding();
    await goToDoneStep();

    fireEvent.click(screen.getByTestId("onboarding-dashboard-cta"));

    expect(await screen.findByTestId("onboarding-finish-error")).toHaveTextContent(
      "Unable to refresh your subscription status right now. Please try again."
    );
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.getByTestId("onboarding-dashboard-cta")).not.toBeDisabled();
  });
});

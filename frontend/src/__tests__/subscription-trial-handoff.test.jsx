import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Subscription from "@/pages/Subscription";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

const mockRefreshSubscription = jest.fn(() => Promise.resolve({ accessRefreshSucceeded: true }));

jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));
jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "runner@example.com" },
  }),
}));
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({
    refreshSubscription: mockRefreshSubscription,
  }),
}));

function mockSubscriptionApi({
  subscriptionStatuses = ["free"],
  garminStatuses = [{ connected: false }],
  garminConnect = null,
} = {}) {
  let subscriptionIndex = 0;
  let garminStatusIndex = 0;

  axios.get.mockImplementation((url) => {
    if (url.includes("/subscription/info")) {
      const nextStatus = subscriptionStatuses[Math.min(subscriptionIndex, subscriptionStatuses.length - 1)];
      subscriptionIndex += 1;
      if (nextStatus instanceof Error) {
        return Promise.reject(nextStatus);
      }
      return Promise.resolve({ data: { status: nextStatus } });
    }
    if (url.includes("/garmin/status")) {
      const nextStatus = garminStatuses[Math.min(garminStatusIndex, garminStatuses.length - 1)];
      garminStatusIndex += 1;
      if (nextStatus instanceof Error) {
        return Promise.reject(nextStatus);
      }
      return Promise.resolve({ data: nextStatus });
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });

  axios.post.mockImplementation((url, payload) => {
    if (url.includes("/garmin/connect")) {
      if (garminConnect instanceof Error) {
        return Promise.reject(garminConnect);
      }
      return Promise.resolve({ data: garminConnect || { status: "connected" } });
    }
    return Promise.reject(new Error(`Unexpected POST ${url} ${JSON.stringify(payload)}`));
  });
}

function renderPage() {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  return render(
    <LanguageProvider>
      <MemoryRouter>
        <Subscription />
      </MemoryRouter>
    </LanguageProvider>
  );
}

describe("PR222 trial Garmin handoff", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    mockRefreshSubscription.mockResolvedValue({ accessRefreshSucceeded: true });
  });

  test("free CTA opens Garmin connect form and never calls /subscription/start-trial", async () => {
    mockSubscriptionApi();
    renderPage();

    fireEvent.click(await screen.findByTestId("start-free-trial-btn"));

    expect(await screen.findByTestId("trial-garmin-connect-form")).toBeInTheDocument();
    expect(axios.post.mock.calls.some(([url]) => String(url).includes("/subscription/start-trial"))).toBe(false);
  });

  test("Garmin success refreshes subscription and updates the UI to TRIAL", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: ["free", "trial"],
      garminStatuses: [{ connected: false }, { connected: true }],
      garminConnect: { status: "connected" },
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("start-free-trial-btn"));
    fireEvent.change(await screen.findByTestId("garmin-email-input"), { target: { value: "runner@example.com" } });
    fireEvent.change(screen.getByTestId("garmin-password-input"), { target: { value: "Password123!" } });
    fireEvent.click(screen.getByTestId("trial-garmin-connect-btn"));

    await waitFor(() => expect(mockRefreshSubscription).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("trial-active-banner")).toBeInTheDocument());

    expect(screen.queryByTestId("start-free-trial-btn")).not.toBeInTheDocument();
    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining("/garmin/connect"),
      expect.objectContaining({
        garmin_username: "runner@example.com",
        garmin_password: "Password123!",
      })
    );
    expect(axios.post.mock.calls.some(([url]) => String(url).includes("/subscription/start-trial"))).toBe(false);
  });

  test("free user with already-used Garmin stays FREE after refresh", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: ["free", "free"],
      garminStatuses: [{ connected: true }, { connected: true }],
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("start-free-trial-btn"));

    await waitFor(() => expect(mockRefreshSubscription).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId("trial-garmin-status-message")).toHaveTextContent("no longer available");
    expect(screen.getByTestId("start-free-trial-btn")).toBeInTheDocument();
    expect(axios.post).not.toHaveBeenCalled();
  });

  test("premium users do not see the trial CTA", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: ["premium"],
      garminStatuses: [{ connected: true }],
    });
    renderPage();

    expect(await screen.findByTestId("premium-status-pill")).toBeInTheDocument();
    expect(screen.queryByTestId("start-free-trial-btn")).not.toBeInTheDocument();
  });

  test("Garmin connect error does not grant false premium access", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: ["free"],
      garminStatuses: [{ connected: false }],
      garminConnect: new Error("garmin failed"),
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("start-free-trial-btn"));
    fireEvent.change(await screen.findByTestId("garmin-email-input"), { target: { value: "runner@example.com" } });
    fireEvent.change(screen.getByTestId("garmin-password-input"), { target: { value: "Password123!" } });
    fireEvent.click(screen.getByTestId("trial-garmin-connect-btn"));

    expect(await screen.findByTestId("trial-garmin-status-message")).toHaveTextContent("Garmin connection failed");
    expect(mockRefreshSubscription).not.toHaveBeenCalled();
    expect(screen.getByTestId("start-free-trial-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("trial-active-banner")).not.toBeInTheDocument();
    expect(screen.queryByTestId("premium-status-pill")).not.toBeInTheDocument();
  });

  test("subscription info error hides false FREE and TRIAL subscription CTAs until retry succeeds", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: [new Error("subscription down"), "trial"],
      garminStatuses: [{ connected: false }],
    });
    renderPage();

    expect(await screen.findByTestId("subscription-status-error")).toBeInTheDocument();
    expect(screen.queryByTestId("start-free-trial-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subscription-free-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("premium-subscribe-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("trial-active-banner")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("subscription-status-retry-btn"));

    await waitFor(() => expect(screen.getByTestId("trial-active-banner")).toBeInTheDocument());
    expect(screen.queryByTestId("subscription-status-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("start-free-trial-btn")).not.toBeInTheDocument();
  });

  test("Garmin status error never opens a false reconnect form", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: ["free"],
      garminStatuses: [new Error("garmin status down"), new Error("garmin status down")],
    });
    renderPage();

    expect(await screen.findByTestId("start-free-trial-btn")).toBeInTheDocument();
    expect(await screen.findByTestId("trial-garmin-status-message")).toHaveTextContent("Unable to verify your Garmin connection");
    expect(screen.getByTestId("garmin-status-retry-btn")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("start-free-trial-btn"));

    expect(screen.queryByTestId("trial-garmin-connect-form")).not.toBeInTheDocument();
    expect(screen.queryByText("no longer available")).not.toBeInTheDocument();
  });

  test("refresh failure after Garmin connect never shows trial unavailable", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: ["free", new Error("subscription refresh failed")],
      garminStatuses: [{ connected: false }, { connected: true }],
      garminConnect: { status: "connected" },
    });
    renderPage();

    fireEvent.click(await screen.findByTestId("start-free-trial-btn"));
    fireEvent.change(await screen.findByTestId("garmin-email-input"), { target: { value: "runner@example.com" } });
    fireEvent.change(screen.getByTestId("garmin-password-input"), { target: { value: "Password123!" } });
    fireEvent.click(screen.getByTestId("trial-garmin-connect-btn"));

    expect(await screen.findByTestId("subscription-status-error")).toBeInTheDocument();
    expect(screen.queryByText("no longer available")).not.toBeInTheDocument();
  });

  test("trial status with failed access refresh never shows false trial activated", async () => {
    mockSubscriptionApi({
      subscriptionStatuses: ["free", "trial"],
      garminStatuses: [{ connected: false }, { connected: true }],
      garminConnect: { status: "connected" },
    });
    mockRefreshSubscription.mockResolvedValue({ accessRefreshSucceeded: false });
    renderPage();

    fireEvent.click(await screen.findByTestId("start-free-trial-btn"));
    fireEvent.change(await screen.findByTestId("garmin-email-input"), { target: { value: "runner@example.com" } });
    fireEvent.change(screen.getByTestId("garmin-password-input"), { target: { value: "Password123!" } });
    fireEvent.click(screen.getByTestId("trial-garmin-connect-btn"));

    expect(await screen.findByTestId("subscription-status-error")).toBeInTheDocument();
    expect(screen.queryByTestId("trial-active-banner")).not.toBeInTheDocument();
    expect(screen.queryByText("30-day free trial activated")).not.toBeInTheDocument();
    expect(screen.queryByText("no longer available")).not.toBeInTheDocument();
  });
});

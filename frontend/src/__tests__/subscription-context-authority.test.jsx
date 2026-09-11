import React from "react";
import "@testing-library/jest-dom";
import { renderHook, waitFor } from "@testing-library/react";
import axios from "axios";

import { LanguageProvider } from "@/context/LanguageContext";
import { SubscriptionProvider, useSubscription } from "@/context/SubscriptionContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "runner@example.com" },
  }),
}));

function wrapper({ children }) {
  return (
    <LanguageProvider>
      <SubscriptionProvider>{children}</SubscriptionProvider>
    </LanguageProvider>
  );
}

describe("SubscriptionContext access authority", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    console.error.mockRestore();
  });

  test("uses /user/features as the source of trial access and days remaining", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("/user/features")) {
        return Promise.resolve({
          data: {
            plan: "trial",
            trial_active: true,
            has_premium_access: true,
            trial_days_remaining: 30,
            feature_access: { training_plan: true },
          },
        });
      }
      if (url.includes("/subscription/info")) {
        return Promise.resolve({
          data: {
            status: "free",
            trial_days_remaining: 1,
            display: { label: "Free", badge: "LIMITED", badge_color: "gray" },
          },
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    const { result } = renderHook(() => useSubscription(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isTrial).toBe(true);
    expect(result.current.hasPremiumAccess).toBe(true);
    expect(result.current.isPremium).toBe(false);
    expect(result.current.trialDaysRemaining).toBe(30);
    expect(result.current.statusLabel).toBe("Free");
  });

  test("fails closed without reusing /subscription/info trial values when /user/features fails", async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("/user/features")) {
        return Promise.reject(new Error("features unavailable"));
      }
      if (url.includes("/subscription/info")) {
        return Promise.resolve({
          data: {
            status: "trial",
            trial_days_remaining: 30,
            display: { label: "Trial", badge: "TRIAL", badge_color: "blue" },
          },
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    const { result } = renderHook(() => useSubscription(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isFree).toBe(true);
    expect(result.current.isTrial).toBe(false);
    expect(result.current.hasPremiumAccess).toBe(false);
    expect(result.current.trialDaysRemaining).toBeNull();
    expect(result.current.statusLabel).toBe("Trial");
  });
});

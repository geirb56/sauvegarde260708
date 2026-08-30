import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Onboarding from "@/pages/Onboarding";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({
    refreshSubscription: jest.fn(() => Promise.resolve()),
  }),
}));

jest.mock("@/hooks/useGarminSyncProgress", () => ({
  useGarminSyncProgress: jest.fn(() => ({
    progress: null,
    isStreaming: false,
    error: null,
  })),
}));
import { useGarminSyncProgress } from "@/hooks/useGarminSyncProgress";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function renderOnboarding() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter>
          <Onboarding />
        </MemoryRouter>
      </LanguageProvider>
    );
  });

  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

function click(container, selector) {
  const element = container.querySelector(selector);
  expect(element).toBeTruthy();
  act(() => {
    element.click();
  });
}

function setFieldValue(element, value) {
  expect(element).toBeTruthy();
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  act(() => {
    descriptor.set.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("PR205 Garmin onboarding credentials semantics", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    useGarminSyncProgress.mockReturnValue({ progress: null, isStreaming: false, error: null });
    axios.post.mockResolvedValue({ data: {} });
  });

  test("welcome CTA opens Garmin-only step", () => {
    const { container, unmount } = renderOnboarding();

    click(container, '[data-testid="onboarding-start"]');

    expect(container.querySelector('[data-testid="onboarding-step-garmin"]')).toBeTruthy();
    expect(container.textContent).not.toContain("Apple Health");
    expect(container.textContent).not.toContain("Whoop");
    expect(container.textContent).not.toContain("Fitbit");

    unmount();
  });

  test("garmin fields keep password-manager friendly attributes", () => {
    const { container, unmount } = renderOnboarding();
    click(container, '[data-testid="onboarding-start"]');

    const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
    const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
    const connectButton = container.querySelector('[data-testid="garmin-connect"]');

    expect(emailInput.getAttribute("type")).toBe("email");
    expect(emailInput.getAttribute("name")).toBe("username");
    expect(emailInput.getAttribute("autocomplete")).toContain("username");
    expect(emailInput.getAttribute("autocomplete")).not.toContain("off");

    expect(passwordInput.getAttribute("type")).toBe("password");
    expect(passwordInput.getAttribute("name")).toBe("password");
    expect(passwordInput.getAttribute("autocomplete")).toContain("current-password");
    expect(passwordInput.getAttribute("autocomplete")).not.toContain("off");

    expect(connectButton.getAttribute("type")).toBe("submit");

    unmount();
  });

  test("successful Garmin connect clears password and starts sync", async () => {
    axios.post
      .mockResolvedValueOnce({ data: { status: "connected" } })
      .mockResolvedValueOnce({ data: { synced_count: 12 } });

    const { container, unmount } = renderOnboarding();
    click(container, '[data-testid="onboarding-start"]');

    const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
    const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');

    setFieldValue(emailInput, "runner@example.com");
    setFieldValue(passwordInput, "Password123!");

    click(container, '[data-testid="garmin-connect"]');
    await flush();

    expect(axios.post).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining("/garmin/connect"),
      expect.objectContaining({
        garmin_username: "runner@example.com",
        garmin_password: "Password123!",
      })
    );
    expect(axios.post).toHaveBeenNthCalledWith(2, expect.stringContaining("/garmin/sync"), {});

    const passwordInputAfter = container.querySelector('[data-testid="garmin-password-input"]');
    expect(passwordInputAfter).toBeFalsy();

    unmount();
  });
});

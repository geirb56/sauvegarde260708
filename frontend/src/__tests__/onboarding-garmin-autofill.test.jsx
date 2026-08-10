import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Onboarding from "@/pages/Onboarding";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");
jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

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

describe("onboarding garmin login autofill semantics", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    axios.get.mockResolvedValue({ data: { metrics: null } });
    axios.post.mockResolvedValue({ data: {} });
  });

  test("garmin fields use login-friendly attributes and real form semantics", async () => {
    const { container, unmount } = renderOnboarding();

    click(container, '[data-testid="onboarding-start"]');
    click(container, '[data-testid^="fitness-option-"]');
    click(container, "button.ml-auto");
    click(container, '[data-testid^="goal-option-"]');
    click(container, "button.ml-auto");
    click(container, '[data-testid^="frequency-option-"]');
    click(container, "button.ml-auto");

    const deviceOptions = Array.from(container.querySelectorAll('[data-testid^="device-option-"]'));
    expect(deviceOptions.length).toBeGreaterThan(1);
    const garminOption = deviceOptions.find((option) => option.getAttribute("data-testid").includes("garmin")) || deviceOptions[1];
    act(() => {
      garminOption.click();
    });

    const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
    const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
    const connectButton = container.querySelector('[data-testid="garmin-connect"]');

    expect(emailInput).toBeTruthy();
    expect(passwordInput).toBeTruthy();
    expect(connectButton).toBeTruthy();

    expect(emailInput.getAttribute("type")).toBe("email");
    expect(emailInput.getAttribute("name")).toBe("username");
    expect(emailInput.getAttribute("id")).toBe("garmin-connect-email");
    expect(emailInput.getAttribute("autocomplete")).toContain("username");
    expect(emailInput.getAttribute("autocomplete")).not.toContain("off");

    expect(passwordInput.getAttribute("type")).toBe("password");
    expect(passwordInput.getAttribute("name")).toBe("password");
    expect(passwordInput.getAttribute("id")).toBe("garmin-connect-password");
    expect(passwordInput.getAttribute("autocomplete")).toContain("current-password");
    expect(passwordInput.getAttribute("autocomplete")).not.toContain("off");

    const form = emailInput.closest("form");
    expect(form).toBeTruthy();
    expect(passwordInput.closest("form")).toBe(form);
    expect(connectButton.closest("form")).toBe(form);
    expect(connectButton.getAttribute("type")).toBe("submit");

    unmount();
  });
});

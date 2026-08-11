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

function setFieldValue(element, value) {
  expect(element).toBeTruthy();
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  descriptor.set.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

function goToGarminStep(container) {
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
}

function getGarminFormElements(container) {
  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  const connectButton = container.querySelector('[data-testid="garmin-connect"]');
  const form = emailInput?.closest("form");
  return { emailInput, passwordInput, connectButton, form };
}

function connectCallCount() {
  return axios.post.mock.calls.filter(([url]) => String(url).includes("/garmin/connect")).length;
}

describe("onboarding garmin login autofill semantics", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    axios.get.mockResolvedValue({ data: { metrics: null } });
    axios.post.mockResolvedValue({ data: {} });
  });

  test("garmin fields use login-friendly attributes and real form semantics", () => {
    const { container, unmount } = renderOnboarding();
    goToGarminStep(container);

    const { emailInput, passwordInput, connectButton, form } = getGarminFormElements(container);

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

    expect(form).toBeTruthy();
    expect(passwordInput.closest("form")).toBe(form);
    expect(connectButton.closest("form")).toBe(form);
    expect(connectButton.getAttribute("type")).toBe("submit");

    unmount();
  });

  test("clicking garmin connect triggers exactly one /garmin/connect POST", async () => {
    axios.post.mockResolvedValueOnce({ data: { status: "mfa_required" } });
    const { container, unmount } = renderOnboarding();
    goToGarminStep(container);

    const { emailInput, passwordInput, connectButton } = getGarminFormElements(container);
    setFieldValue(emailInput, "athlete@example.com");
    setFieldValue(passwordInput, "Password123!");
    click(container, '[data-testid="garmin-connect"]');
    await flush();

    expect(connectButton.getAttribute("type")).toBe("submit");
    expect(connectCallCount()).toBe(1);
    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining("/garmin/connect"),
      expect.objectContaining({
        garmin_username: "athlete@example.com",
        garmin_password: "Password123!",
      })
    );
    unmount();
  });

  test("submitting garmin form triggers exactly one /garmin/connect POST", async () => {
    axios.post.mockResolvedValueOnce({ data: { status: "mfa_required" } });
    const { container, unmount } = renderOnboarding();
    goToGarminStep(container);

    const { emailInput, passwordInput, form } = getGarminFormElements(container);
    setFieldValue(emailInput, "athlete@example.com");
    setFieldValue(passwordInput, "Password123!");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await flush();

    expect(connectCallCount()).toBe(1);
    unmount();
  });

  test("garmin email/password labels are explicitly associated to inputs", () => {
    const { container, unmount } = renderOnboarding();
    goToGarminStep(container);

    const emailInput = container.querySelector("#garmin-connect-email");
    const passwordInput = container.querySelector("#garmin-connect-password");
    const emailLabel = container.querySelector('label[for="garmin-connect-email"]');
    const passwordLabel = container.querySelector('label[for="garmin-connect-password"]');

    expect(emailLabel).toBeTruthy();
    expect(passwordLabel).toBeTruthy();
    expect(emailLabel.control).toBe(emailInput);
    expect(passwordLabel.control).toBe(passwordInput);

    unmount();
  });

  test("connecting state keeps existing disabled button and spinner behavior", async () => {
    let resolveConnect;
    axios.post.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveConnect = resolve;
        })
    );
    const { container, unmount } = renderOnboarding();
    goToGarminStep(container);

    const { emailInput, passwordInput, connectButton } = getGarminFormElements(container);
    setFieldValue(emailInput, "athlete@example.com");
    setFieldValue(passwordInput, "Password123!");
    click(container, '[data-testid="garmin-connect"]');
    await flush();

    expect(connectButton.disabled).toBe(true);
    expect(connectButton.querySelector(".animate-spin")).toBeTruthy();

    resolveConnect({ data: { status: "mfa_required" } });
    await flush();

    unmount();
  });

  test("password is cleared after successful garmin connect", async () => {
    let resolveSync;
    axios.post
      .mockResolvedValueOnce({ data: { status: "connected" } })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSync = resolve;
          })
      );

    const { container, unmount } = renderOnboarding();
    goToGarminStep(container);

    const { emailInput, passwordInput } = getGarminFormElements(container);
    setFieldValue(emailInput, "athlete@example.com");
    setFieldValue(passwordInput, "Password123!");
    click(container, '[data-testid="garmin-connect"]');
    await flush();

    const passwordInputAfterConnect = container.querySelector('[data-testid="garmin-password-input"]');
    expect(passwordInputAfterConnect).toBeTruthy();
    expect(passwordInputAfterConnect.value).toBe("");
    expect(axios.post.mock.calls[1][0]).toContain("/garmin/sync");

    resolveSync({ data: { synced_count: 0 } });
    await flush();

    unmount();
  });

  test("mfa required state remains rendered after form submit flow", async () => {
    axios.post.mockResolvedValueOnce({ data: { status: "mfa_required" } });

    const { container, unmount } = renderOnboarding();
    goToGarminStep(container);

    const { emailInput, passwordInput } = getGarminFormElements(container);
    setFieldValue(emailInput, "athlete@example.com");
    setFieldValue(passwordInput, "Password123!");
    click(container, '[data-testid="garmin-connect"]');
    await flush();

    expect(container.querySelector('[data-testid="garmin-mfa"]')).toBeTruthy();
    expect(connectCallCount()).toBe(1);

    unmount();
  });
});

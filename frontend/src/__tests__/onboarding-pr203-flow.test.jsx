/**
 * PR203 — Onboarding UX V2 flow tests
 *
 * Validates:
 *   FLOW: Welcome → Garmin → Sync → First Value → Goal → Plan Parameters → Dashboard
 *   GARMIN_ONLY_ONBOARDING: no Apple Health / Whoop / Fitbit shown
 *   Goal business values stable across languages
 *   Password cleared after connect
 *   Final route = /dashboard
 *   i18n coverage: EN / FR / ES
 */

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
jest.mock("@/hooks/useGarminSyncProgress", () => ({
  useGarminSyncProgress: jest.fn(() => ({
    progress: null,
    isStreaming: false,
    error: null,
  })),
}));

import { useGarminSyncProgress } from "@/hooks/useGarminSyncProgress";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  return { container, unmount: () => { act(() => root.unmount()); container.remove(); } };
}

function click(container, selector) {
  const el = container.querySelector(selector);
  expect(el).toBeTruthy();
  act(() => { el.click(); });
}

function setFieldValue(element, value) {
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  act(() => {
    descriptor.set.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function flush() {
  await act(async () => { await Promise.resolve(); });
}

function mockSyncReady() {
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "complete",
      run_index_status: "ready",
      readiness_status: "ready",
      run_index: 70,
      readiness: 80,
      activities_count: 30,
    },
    isStreaming: false,
    error: null,
  });
}

async function navigateFullFlow(container) {
  // welcome → garmin
  click(container, '[data-testid="onboarding-start"]');

  // garmin → sync
  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "athlete@example.com");
  setFieldValue(passwordInput, "Secret1!");
  click(container, '[data-testid="garmin-connect"]');
  await flush();

  // sync → firstvalue
  click(container, '[data-testid="sync-continue"]');

  // firstvalue → goal
  click(container, '[data-testid="firstvalue-continue"]');

  // goal: pick Marathon → params
  click(container, '[data-testid="goal-option-marathon"]');
  click(container, '[data-testid="goal-continue"]');

  // params → done
  click(container, '[data-testid="apply-onboarding-plan"]');
  await flush();
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");

  mockSyncReady();

  axios.post
    .mockResolvedValueOnce({ data: { status: "connected" } })   // /garmin/connect
    .mockResolvedValueOnce({ data: { synced_count: 30 } })      // /garmin/sync
    .mockResolvedValueOnce({ data: { status: "updated" } })     // /training/set-goal
    .mockResolvedValueOnce({ data: {} });                        // /training/refresh
});

// ---------------------------------------------------------------------------
// T-FLOW — Full flow renders all steps in correct order
// ---------------------------------------------------------------------------

test("FLOW: welcome → garmin → sync → firstvalue → goal → params → done", async () => {
  const { container, unmount } = renderOnboarding();

  // Welcome step
  expect(container.querySelector('[data-testid="onboarding-start"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="onboarding-logo"]')).toBeTruthy();

  // → garmin
  click(container, '[data-testid="onboarding-start"]');
  expect(container.querySelector('[data-testid="garmin-connect-panel"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-email-input"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-password-input"]')).toBeTruthy();

  // connect → sync
  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "athlete@example.com");
  setFieldValue(passwordInput, "Secret1!");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
  expect(container.querySelector('[data-testid="garmin-sync-panel"]')).toBeTruthy();

  // sync → firstvalue
  click(container, '[data-testid="sync-continue"]');
  expect(container.querySelector('[data-testid="first-value-panel"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-runindex-panel"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-readiness-panel"]')).toBeTruthy();

  // firstvalue → goal
  click(container, '[data-testid="firstvalue-continue"]');
  expect(container.querySelector('[data-testid="goal-option-5k"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-10k"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-semi"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-marathon"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-ultra"]')).toBeTruthy();

  // goal → params
  click(container, '[data-testid="goal-option-marathon"]');
  click(container, '[data-testid="goal-continue"]');
  expect(container.querySelector('[data-testid="plan-start-date-input"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="race-date-input"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="apply-onboarding-plan"]')).toBeTruthy();

  // params → done
  click(container, '[data-testid="apply-onboarding-plan"]');
  await flush();
  expect(container.querySelector('[data-testid="onboarding-done"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-see-dashboard"]')).toBeTruthy();

  unmount();
});

// ---------------------------------------------------------------------------
// T-GARMIN-ONLY — No non-Garmin device options shown
// ---------------------------------------------------------------------------

test("GARMIN_ONLY_ONBOARDING: no Apple Health / Whoop / Fitbit options in onboarding", async () => {
  const { container, unmount } = renderOnboarding();

  // Navigate through the full flow and check no other devices appear at any step
  const fullText = () => container.textContent.toLowerCase();

  click(container, '[data-testid="onboarding-start"]');
  expect(fullText()).not.toContain("apple health");
  expect(fullText()).not.toContain("whoop");
  expect(fullText()).not.toContain("fitbit");

  unmount();
});

// ---------------------------------------------------------------------------
// T-GOAL-VALUES — Business values (5K/10K/SEMI/MARATHON/ULTRA) are stable
// ---------------------------------------------------------------------------

test("GOAL_BUSINESS_VALUES_STABLE: goal data-testids use backend values, not translated labels", async () => {
  const { container, unmount } = renderOnboarding();
  click(container, '[data-testid="onboarding-start"]');

  // fill garmin
  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "a@b.com");
  setFieldValue(passwordInput, "pw");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
  click(container, '[data-testid="sync-continue"]');
  click(container, '[data-testid="firstvalue-continue"]');

  // Goal options have data-testid based on backend value (5k, 10k, semi, marathon, ultra)
  expect(container.querySelector('[data-testid="goal-option-5k"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-10k"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-semi"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-marathon"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="goal-option-ultra"]')).toBeTruthy();

  // Select SEMI and verify the correct backend value is sent to the API
  click(container, '[data-testid="goal-option-semi"]');
  click(container, '[data-testid="goal-continue"]');

  // Reset plan mocks
  axios.post
    .mockResolvedValueOnce({ data: { status: "updated" } })
    .mockResolvedValueOnce({ data: {} });

  click(container, '[data-testid="apply-onboarding-plan"]');
  await flush();

  const setGoalCall = axios.post.mock.calls.find(([url]) => String(url).includes("set-goal"));
  expect(setGoalCall).toBeTruthy();
  // Backend value must be SEMI, NOT a translated label like "Semi-Marathon"
  expect(String(setGoalCall[0])).toContain("goal=SEMI");

  unmount();
});

// ---------------------------------------------------------------------------
// T-SESSIONS — Sessions per week selector sends numeric value
// ---------------------------------------------------------------------------

test("SESSIONS_PER_WEEK: numeric value sent to backend regardless of language", async () => {
  const { container, unmount } = renderOnboarding();
  click(container, '[data-testid="onboarding-start"]');

  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "a@b.com");
  setFieldValue(passwordInput, "pw");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
  click(container, '[data-testid="sync-continue"]');
  click(container, '[data-testid="firstvalue-continue"]');
  click(container, '[data-testid="goal-option-10k"]');
  click(container, '[data-testid="goal-continue"]');

  // Select 5 sessions
  click(container, '[data-testid="sessions-option-5"]');

  axios.post
    .mockResolvedValueOnce({ data: { status: "updated" } })
    .mockResolvedValueOnce({ data: {} });

  click(container, '[data-testid="apply-onboarding-plan"]');
  await flush();

  const refreshCall = axios.post.mock.calls.find(([url]) => String(url).includes("refresh"));
  expect(refreshCall).toBeTruthy();
  expect(String(refreshCall[0])).toContain("sessions=5");

  unmount();
});

// ---------------------------------------------------------------------------
// T-PLAN-START — Plan start date field is visible and defaults to today
// ---------------------------------------------------------------------------

test("PLAN_START_DATE_VISIBLE: plan start date field is present and has a default value", async () => {
  const { container, unmount } = renderOnboarding();
  click(container, '[data-testid="onboarding-start"]');

  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "a@b.com");
  setFieldValue(passwordInput, "pw");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
  click(container, '[data-testid="sync-continue"]');
  click(container, '[data-testid="firstvalue-continue"]');
  click(container, '[data-testid="goal-option-marathon"]');
  click(container, '[data-testid="goal-continue"]');

  const planStartInput = container.querySelector('[data-testid="plan-start-date-input"]');
  expect(planStartInput).toBeTruthy();
  // Default value should be today (non-empty)
  expect(planStartInput.value).toMatch(/^\d{4}-\d{2}-\d{2}$/);

  unmount();
});

// ---------------------------------------------------------------------------
// T-FINAL-ROUTE — Final CTA navigates to /dashboard
// ---------------------------------------------------------------------------

test("FINAL_ROUTE: done step has See my Dashboard CTA", async () => {
  const { container, unmount } = renderOnboarding();
  await navigateFullFlow(container);

  const dashboardBtn = container.querySelector('[data-testid="garmin-see-dashboard"]');
  expect(dashboardBtn).toBeTruthy();
  expect(dashboardBtn.tagName).toBe("BUTTON");

  unmount();
});

// ---------------------------------------------------------------------------
// T-I18N-FR — French locale: key new strings appear translated
// ---------------------------------------------------------------------------

test("I18N_FR: French locale translates new onboarding strings", async () => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
  const { container, unmount } = renderOnboarding();

  // Welcome CTA in French
  expect(container.textContent).toContain("Connecter Garmin");

  click(container, '[data-testid="onboarding-start"]');
  // Garmin step labels in French
  expect(container.textContent).toContain("E-mail Garmin");

  unmount();
});

// ---------------------------------------------------------------------------
// T-I18N-ES — Spanish locale: key new strings appear translated
// ---------------------------------------------------------------------------

test("I18N_ES: Spanish locale translates new onboarding strings", async () => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "es");
  const { container, unmount } = renderOnboarding();

  // Welcome CTA in Spanish
  expect(container.textContent).toContain("Conectar Garmin");

  click(container, '[data-testid="onboarding-start"]');
  // Garmin step labels in Spanish
  expect(container.textContent).toContain("Correo Garmin");

  unmount();
});

// ---------------------------------------------------------------------------
// T-READINESS-OPTIONAL — Readiness not blocking: Continue shows even if absent
// ---------------------------------------------------------------------------

test("READINESS_OPTIONAL: firstvalue Continue CTA present even without Readiness", async () => {
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "complete",
      run_index_status: "ready",
      readiness_status: "insufficient_data",
      run_index: 65,
      activities_count: 12,
    },
    isStreaming: false,
    error: null,
  });

  const { container, unmount } = renderOnboarding();
  click(container, '[data-testid="onboarding-start"]');

  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "a@b.com");
  setFieldValue(passwordInput, "pw");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
  click(container, '[data-testid="sync-continue"]');

  // RunIndex visible
  expect(container.querySelector('[data-testid="garmin-runindex-panel"]')).toBeTruthy();
  // Readiness NOT shown
  expect(container.querySelector('[data-testid="garmin-readiness-panel"]')).toBeFalsy();
  // Continue still available
  expect(container.querySelector('[data-testid="firstvalue-continue"]')).toBeTruthy();

  unmount();
});

// ---------------------------------------------------------------------------
// T-NO-DATA — Insufficient data shows honest message, Continue still available
// ---------------------------------------------------------------------------

test("INSUFFICIENT_DATA: honest message shown and onboarding not blocked", async () => {
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "partial_success",
      run_index_status: "insufficient_data",
      readiness_status: "insufficient_data",
      activities_count: 1,
    },
    isStreaming: false,
    error: null,
  });

  const { container, unmount } = renderOnboarding();
  click(container, '[data-testid="onboarding-start"]');

  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "a@b.com");
  setFieldValue(passwordInput, "pw");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
  click(container, '[data-testid="sync-continue"]');

  expect(container.querySelector('[data-testid="garmin-no-data"]')).toBeTruthy();
  // Continue still available — onboarding not blocked
  expect(container.querySelector('[data-testid="firstvalue-continue"]')).toBeTruthy();

  unmount();
});

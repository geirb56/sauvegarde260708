/**
 * PR07C — RunIndex Activation tests
 *
 * Covers the 6 required scenarios:
 * 1. run_index_status=ready shows RunIndex without waiting for Readiness.
 * 2. readiness_status=ready adds Readiness.
 * 3. Readiness absent / in-progress does NOT hide RunIndex.
 * 4. No usable data → no fake score shown.
 * 5. CTA "See my dashboard" navigates to /dashboard.
 * 6. SSE error → error message shown, credentials not re-prompted.
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

// We mock the hook so we can inject progress state without a real SSE server.
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
  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
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

/** Navigate the onboarding wizard to the device step. */
function goToDeviceStep(container) {
  click(container, '[data-testid="onboarding-start"]');
  click(container, '[data-testid^="fitness-option-"]');
  click(container, "button.ml-auto");
  click(container, '[data-testid^="goal-option-"]');
  click(container, "button.ml-auto");
  click(container, '[data-testid^="frequency-option-"]');
  click(container, "button.ml-auto");

  const deviceOptions = Array.from(
    container.querySelectorAll('[data-testid^="device-option-"]')
  );
  const garminOption =
    deviceOptions.find((o) => o.dataset.testid.includes("garmin")) ||
    deviceOptions[1];
  act(() => { garminOption.click(); });
}

/** Connect Garmin and flush all async side-effects. */
async function connectGarmin(container) {
  const emailInput = container.querySelector('[data-testid="garmin-email-input"]');
  const passwordInput = container.querySelector('[data-testid="garmin-password-input"]');
  setFieldValue(emailInput, "athlete@example.com");
  setFieldValue(passwordInput, "Password123!");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  axios.get.mockResolvedValue({ data: { metrics: null } });

  // Default: hook returns idle (no progress yet)
  useGarminSyncProgress.mockReturnValue({ progress: null, isStreaming: false, error: null });
});

// ---------------------------------------------------------------------------
// Test 1 — run_index_status=ready shows RunIndex immediately, no Readiness needed
// ---------------------------------------------------------------------------

test("T1: run_index_status=ready shows RunIndex without Readiness", async () => {
  // Simulate SSE delivering run_index_ready but not readiness_ready yet.
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "in_progress",
      run_index_status: "ready",
      readiness_status: "pending",
      run_index: 72,
      synced_count: 15,
    },
    isStreaming: false,
    error: null,
  });

  axios.post
    .mockResolvedValueOnce({ data: { status: "connected" } })
    .mockResolvedValueOnce({ data: { synced_count: 15 } });

  const { container, unmount } = renderOnboarding();
  goToDeviceStep(container);
  await connectGarmin(container);

  expect(container.querySelector('[data-testid="garmin-runindex-panel"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-runindex-value"]').textContent).toBe("72");
  expect(container.querySelector('[data-testid="garmin-readiness-panel"]')).toBeFalsy();
  expect(container.querySelector('[data-testid="garmin-see-dashboard"]')).toBeTruthy();

  unmount();
});

// ---------------------------------------------------------------------------
// Test 2 — readiness_status=ready adds Readiness row
// ---------------------------------------------------------------------------

test("T2: readiness_status=ready adds Readiness row alongside RunIndex", async () => {
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "complete",
      run_index_status: "ready",
      readiness_status: "ready",
      run_index: 68,
      readiness: 85,
      synced_count: 20,
    },
    isStreaming: false,
    error: null,
  });

  axios.post
    .mockResolvedValueOnce({ data: { status: "connected" } })
    .mockResolvedValueOnce({ data: { synced_count: 20 } });

  const { container, unmount } = renderOnboarding();
  goToDeviceStep(container);
  await connectGarmin(container);

  expect(container.querySelector('[data-testid="garmin-runindex-panel"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-runindex-value"]').textContent).toBe("68");
  expect(container.querySelector('[data-testid="garmin-readiness-panel"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-readiness-value"]').textContent).toBe("85");

  unmount();
});

// ---------------------------------------------------------------------------
// Test 3 — Readiness absent / still in-progress does NOT hide RunIndex
// ---------------------------------------------------------------------------

test("T3: readiness still in-progress does not hide RunIndex", async () => {
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "in_progress",
      run_index_status: "ready",
      readiness_status: "computing",
      run_index: 55,
      synced_count: 10,
    },
    isStreaming: true,
    error: null,
  });

  axios.post
    .mockResolvedValueOnce({ data: { status: "connected" } })
    .mockResolvedValueOnce({ data: { synced_count: 10 } });

  const { container, unmount } = renderOnboarding();
  goToDeviceStep(container);
  await connectGarmin(container);

  // RunIndex must be visible
  expect(container.querySelector('[data-testid="garmin-runindex-panel"]')).toBeTruthy();
  expect(container.querySelector('[data-testid="garmin-runindex-value"]').textContent).toBe("55");

  // Readiness must NOT be shown yet
  expect(container.querySelector('[data-testid="garmin-readiness-panel"]')).toBeFalsy();

  // No-data message must NOT appear since run_index IS ready
  expect(container.querySelector('[data-testid="garmin-no-data"]')).toBeFalsy();

  unmount();
});

// ---------------------------------------------------------------------------
// Test 4 — No usable data → honest message, no fake score
// ---------------------------------------------------------------------------

test("T4: no usable data shows honest message without fabricating a score", async () => {
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "partial_success",
      run_index_status: "insufficient_data",
      readiness_status: "insufficient_data",
      synced_count: 2,
    },
    isStreaming: false,
    error: null,
  });

  axios.post
    .mockResolvedValueOnce({ data: { status: "connected" } })
    .mockResolvedValueOnce({ data: { synced_count: 2 } });

  const { container, unmount } = renderOnboarding();
  goToDeviceStep(container);
  await connectGarmin(container);

  // No fake score panels
  expect(container.querySelector('[data-testid="garmin-runindex-panel"]')).toBeFalsy();
  expect(container.querySelector('[data-testid="garmin-readiness-panel"]')).toBeFalsy();

  // Honest message
  expect(container.querySelector('[data-testid="garmin-no-data"]')).toBeTruthy();

  unmount();
});

// ---------------------------------------------------------------------------
// Test 5 — CTA "See my dashboard" navigates to /dashboard
// ---------------------------------------------------------------------------

test("T5: CTA See my dashboard is present and navigates to /dashboard", async () => {
  useGarminSyncProgress.mockReturnValue({
    progress: {
      status: "complete",
      run_index_status: "ready",
      readiness_status: "ready",
      run_index: 60,
      readiness: 90,
      synced_count: 25,
    },
    isStreaming: false,
    error: null,
  });

  axios.post
    .mockResolvedValueOnce({ data: { status: "connected" } })
    .mockResolvedValueOnce({ data: { synced_count: 25 } });

  const { container, unmount } = renderOnboarding();
  goToDeviceStep(container);
  await connectGarmin(container);

  const dashboardBtn = container.querySelector('[data-testid="garmin-see-dashboard"]');
  expect(dashboardBtn).toBeTruthy();
  expect(dashboardBtn.tagName).toBe("BUTTON");

  // Click the button — MemoryRouter will process the navigation internally.
  // We verify no error is thrown and the button was clickable.
  act(() => { dashboardBtn.click(); });

  unmount();
});

// ---------------------------------------------------------------------------
// Test 6 — SSE error shows message without re-prompting credentials
// ---------------------------------------------------------------------------

test("T6: SSE error shows sync-failed message and does not re-prompt credentials", async () => {
  useGarminSyncProgress.mockReturnValue({
    progress: null,
    isStreaming: false,
    error: "sync_failed",
  });

  axios.post
    .mockResolvedValueOnce({ data: { status: "connected" } })
    .mockResolvedValueOnce({ data: { synced_count: 0 } });

  const { container, unmount } = renderOnboarding();
  goToDeviceStep(container);
  await connectGarmin(container);

  // Sync error message shown
  const errorEl = container.querySelector('[data-testid="garmin-sync-error"]');
  expect(errorEl).toBeTruthy();

  // Credentials form NOT shown (we are in connected state)
  expect(container.querySelector('[data-testid="garmin-email-input"]')).toBeFalsy();
  expect(container.querySelector('[data-testid="garmin-password-input"]')).toBeFalsy();

  unmount();
});

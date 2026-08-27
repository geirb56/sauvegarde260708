import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Onboarding from "@/pages/Onboarding";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

const mockNavigate = jest.fn();
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
  const el = container.querySelector(selector);
  expect(el).toBeTruthy();
  act(() => {
    el.click();
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

async function connectGarmin(container) {
  click(container, '[data-testid="onboarding-start"]');
  setFieldValue(container.querySelector('[data-testid="garmin-email-input"]'), "runner@example.com");
  setFieldValue(container.querySelector('[data-testid="garmin-password-input"]'), "Password123!");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
}

describe("PR205 onboarding flow and first value", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockNavigate.mockReset();
    window.localStorage.clear();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");

    useGarminSyncProgress.mockReturnValue({ progress: null, isStreaming: false, error: null });
  });

  test("shows RunIndex first value and optional readiness without blocking", async () => {
    useGarminSyncProgress.mockReturnValue({
      progress: {
        status: "complete",
        run_index_status: "ready",
        readiness_status: "ready",
        run_index: 74,
        readiness: 82,
        activities_count: 18,
      },
      isStreaming: false,
      error: null,
    });

    axios.post
      .mockResolvedValueOnce({ data: { status: "connected" } })
      .mockResolvedValueOnce({ data: { synced_count: 18 } });

    const { container, unmount } = renderOnboarding();
    await connectGarmin(container);

    click(container, '[data-testid="onboarding-continue"]'); // sync
    click(container, '[data-testid="onboarding-continue"]'); // first value

    expect(container.querySelector('[data-testid="runindex-first-value"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="runindex-value"]').textContent).toContain("74");
    expect(container.querySelector('[data-testid="readiness-optional"]')).toBeTruthy();

    unmount();
  });

  test("handles insufficient data honestly", async () => {
    useGarminSyncProgress.mockReturnValue({
      progress: {
        status: "partial_success",
        run_index_status: "insufficient_data",
        readiness_status: "insufficient_data",
        activities_count: 2,
      },
      isStreaming: false,
      error: null,
    });

    axios.post
      .mockResolvedValueOnce({ data: { status: "connected" } })
      .mockResolvedValueOnce({ data: { synced_count: 2 } });

    const { container, unmount } = renderOnboarding();
    await connectGarmin(container);

    click(container, '[data-testid="onboarding-continue"]');
    click(container, '[data-testid="onboarding-continue"]');

    expect(container.querySelector('[data-testid="runindex-first-value"]')).toBeFalsy();
    expect(container.querySelector('[data-testid="runindex-insufficient-data"]')).toBeTruthy();

    unmount();
  });

  test("creates plan with canonical goal and numeric sessions then routes to dashboard", async () => {
    useGarminSyncProgress.mockReturnValue({
      progress: {
        status: "complete",
        run_index_status: "ready",
        run_index: 66,
        readiness_status: "pending",
        activities_count: 9,
      },
      isStreaming: false,
      error: null,
    });

    axios.post
      .mockResolvedValueOnce({ data: { status: "connected" } })
      .mockResolvedValueOnce({ data: { synced_count: 9 } })
      .mockResolvedValueOnce({ data: { goal: "MAINTENANCE" } })
      .mockResolvedValueOnce({ data: { ok: true } });

    const { container, unmount } = renderOnboarding();
    await connectGarmin(container);

    click(container, '[data-testid="onboarding-continue"]'); // sync -> first value
    click(container, '[data-testid="onboarding-continue"]'); // first value -> goal
    click(container, '[data-testid="onboarding-continue"]'); // goal step entry

    click(container, '[data-testid="onboarding-goal-maintenance"]');
    click(container, '[data-testid="onboarding-continue"]'); // goal -> sessions

    click(container, '[data-testid="onboarding-sessions-4"]');
    click(container, '[data-testid="onboarding-continue"]'); // create plan
    await flush();

    expect(axios.post).toHaveBeenNthCalledWith(3, expect.stringContaining("/training/set-goal?goal=MAINTENANCE"), {});
    expect(axios.post).toHaveBeenNthCalledWith(4, expect.stringContaining("/training/refresh?sessions=4"), {});

    expect(container.querySelector('[data-testid="onboarding-step-done"]')).toBeTruthy();

    click(container, '[data-testid="onboarding-dashboard-cta"]');
    expect(mockNavigate).toHaveBeenCalledWith("/");

    unmount();
  });
});

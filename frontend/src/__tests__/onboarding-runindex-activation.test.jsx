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
  useGarminSyncProgress: jest.fn(),
}));

import { useGarminSyncProgress } from "@/hooks/useGarminSyncProgress";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let hookState;

function renderOnboarding() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  const renderTree = () => {
    root.render(
      <LanguageProvider>
        <MemoryRouter>
          <Onboarding />
        </MemoryRouter>
      </LanguageProvider>
    );
  };

  act(() => {
    renderTree();
  });

  return {
    container,
    rerender: () => act(() => renderTree()),
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

function continueButton(container) {
  return container.querySelector('[data-testid="onboarding-continue"]');
}

async function connectGarmin(container) {
  click(container, '[data-testid="onboarding-start"]');
  setFieldValue(container.querySelector('[data-testid="garmin-email-input"]'), "runner@example.com");
  setFieldValue(container.querySelector('[data-testid="garmin-password-input"]'), "Password123!");
  click(container, '[data-testid="garmin-connect"]');
  await flush();
}

async function goToSync(container) {
  await connectGarmin(container);
  click(container, '[data-testid="onboarding-continue"]');
}

describe("PR205 onboarding sync/first-value gating", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockNavigate.mockReset();
    window.localStorage.clear();
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");

    hookState = { progress: null, isStreaming: false, error: null };
    useGarminSyncProgress.mockImplementation(() => hookState);

    axios.post
      .mockResolvedValueOnce({ data: { status: "connected" } })
      .mockResolvedValueOnce({ data: { synced_count: 8 } });
  });

  test("SYNC_PENDING_CONTINUE_DISABLED = PASS", async () => {
    hookState = {
      progress: { status: "in_progress", run_index_status: "pending", readiness_status: "pending", activities_count: 8 },
      isStreaming: true,
      error: null,
    };

    const { container, unmount } = renderOnboarding();
    await goToSync(container);

    expect(container.querySelector('[data-testid="onboarding-step-sync"]')).toBeTruthy();
    expect(continueButton(container).disabled).toBe(true);

    unmount();
  });

  test("SYNC_RUNINDEX_READY_CONTINUE_ENABLED = PASS", async () => {
    hookState = {
      progress: { status: "in_progress", run_index_status: "ready", run_index: 70, readiness_status: "pending", activities_count: 8 },
      isStreaming: false,
      error: null,
    };

    const { container, unmount } = renderOnboarding();
    await goToSync(container);

    expect(continueButton(container).disabled).toBe(false);

    unmount();
  });

  test("SYNC_INSUFFICIENT_DATA_CONTINUE_ENABLED = PASS", async () => {
    hookState = {
      progress: { status: "partial_success", run_index_status: "insufficient_data", readiness_status: "insufficient_data", activities_count: 2 },
      isStreaming: false,
      error: null,
    };

    const { container, unmount } = renderOnboarding();
    await goToSync(container);

    expect(continueButton(container).disabled).toBe(false);

    unmount();
  });

  test("FIRST_VALUE_PENDING_CONTINUE_DISABLED = PASS", async () => {
    hookState = {
      progress: { status: "complete", run_index_status: "ready", run_index: 66, readiness_status: "pending", activities_count: 9 },
      isStreaming: false,
      error: null,
    };

    const { container, rerender, unmount } = renderOnboarding();
    await goToSync(container);
    click(container, '[data-testid="onboarding-continue"]'); // sync -> first value

    hookState = {
      progress: { status: "in_progress", run_index_status: "pending", readiness_status: "pending", activities_count: 9 },
      isStreaming: true,
      error: null,
    };
    rerender();

    expect(container.querySelector('[data-testid="onboarding-step-first-value"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="runindex-pending"]')).toBeTruthy();
    expect(continueButton(container).disabled).toBe(true);

    unmount();
  });

  test("FIRST_VALUE_READY_CONTINUE_ENABLED = PASS", async () => {
    hookState = {
      progress: { status: "complete", run_index_status: "ready", run_index: 74, readiness_status: "ready", readiness: 82, activities_count: 18 },
      isStreaming: false,
      error: null,
    };

    const { container, unmount } = renderOnboarding();
    await goToSync(container);
    click(container, '[data-testid="onboarding-continue"]');

    expect(container.querySelector('[data-testid="runindex-first-value"]')).toBeTruthy();
    expect(continueButton(container).disabled).toBe(false);

    unmount();
  });

  test("FIRST_VALUE_INSUFFICIENT_DATA_CONTINUE_ENABLED = PASS", async () => {
    hookState = {
      progress: { status: "partial_success", run_index_status: "insufficient_data", readiness_status: "insufficient_data", activities_count: 2 },
      isStreaming: false,
      error: null,
    };

    const { container, unmount } = renderOnboarding();
    await goToSync(container);
    click(container, '[data-testid="onboarding-continue"]');

    expect(container.querySelector('[data-testid="runindex-insufficient-data"]')).toBeTruthy();
    expect(continueButton(container).disabled).toBe(false);

    unmount();
  });

  test("READINESS_MISSING_DOES_NOT_BLOCK = PASS", async () => {
    hookState = {
      progress: { status: "complete", run_index_status: "ready", run_index: 71, readiness_status: "pending", activities_count: 10 },
      isStreaming: false,
      error: null,
    };

    const { container, unmount } = renderOnboarding();
    await goToSync(container);
    click(container, '[data-testid="onboarding-continue"]');

    expect(container.querySelector('[data-testid="runindex-first-value"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="readiness-optional"]')).toBeFalsy();
    expect(continueButton(container).disabled).toBe(false);

    unmount();
  });
});

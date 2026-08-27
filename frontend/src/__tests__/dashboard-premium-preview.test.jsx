/**
 * PR — Dashboard Premium Preview for FREE users
 *
 * Proves (for FREE):
 *   FREE_TODAY_PREVIEW_VISIBLE = YES
 *   FREE_WEEK_PREVIEW_VISIBLE = YES
 *   FREE_TODAY_PREVIEW_HAS_BLUR = YES
 *   FREE_WEEK_PREVIEW_HAS_BLUR = YES
 *   FREE_PREMIUM_OVERLAY_VISIBLE = YES
 *   FREE_PREMIUM_CTA_VISIBLE = YES
 *   /training/today CALLS = 0
 *   /training/v2/week CALLS = 0
 *   /rag/dashboard CALLS = 0
 *   FREE_PREMIUM_REAL_DATA_IN_DOM = NO
 *
 * Proves (for TRIAL/PREMIUM):
 *   - No blur preview rendered
 *   - No premium overlay
 *   - Real cards rendered
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Dashboard from "@/pages/Dashboard";
import { LanguageProvider } from "@/context/LanguageContext";

jest.mock("axios");
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <div>{children}</div>,
  DialogDescription: ({ children }) => <div>{children}</div>,
}));
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => ({ unitSystem: "metric" }),
}));

const mockUseSubscription = jest.fn();
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => mockUseSubscription(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const INSIGHT_PAYLOAD = {
  week: { sessions: 3, volume_km: 25, actual_duration_minutes: 135 },
  month: { volume_km: 90 },
  run_index: null,
};
const CARDIO_NO_DATA = { no_data: true, connected: false, message: "No data." };

// Recognisable Premium secrets — must NOT appear in DOM for FREE users
const SECRET_TODAY = "SECRET_PREMIUM_WORKOUT";
const SECRET_WEEK = "SECRET_PREMIUM_WEEK_TARGET";

const TODAY_PREMIUM_PAYLOAD = {
  status: "success",
  day: "monday",
  adaptation_applied: false,
  readiness: { band: "FAVORABLE", score: 82, confidence: "high", sufficiency_level: "sufficient", available: true, data_source: "garmin" },
  planned_session: {
    type: SECRET_TODAY,
    duration: "45 min",
    details: "Easy pace",
    estimated_tss: 55,
  },
};

const WEEK_PREMIUM_PAYLOAD = {
  weekly_target: {
    target_basis: "distance",
    target_km: 50,
    target_duration_minutes: null,
    label: SECRET_WEEK,
  },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function setupAxiosFree() {
  axios.get.mockImplementation((url) => {
    if (url.includes("dashboard/insight")) return Promise.resolve({ data: INSIGHT_PAYLOAD });
    if (url.includes("run-index")) return Promise.resolve({ data: CARDIO_NO_DATA });
    // Premium endpoints must never be reached for FREE
    if (url.includes("rag/dashboard")) return Promise.reject(new Error("FORBIDDEN for FREE"));
    if (url.includes("training/today")) return Promise.reject(new Error("FORBIDDEN for FREE"));
    if (url.includes("training/v2/week")) return Promise.reject(new Error("FORBIDDEN for FREE"));
    return Promise.resolve({ data: null });
  });
}

function setupAxiosPremium() {
  axios.get.mockImplementation((url) => {
    if (url.includes("dashboard/insight")) return Promise.resolve({ data: INSIGHT_PAYLOAD });
    if (url.includes("run-index")) return Promise.resolve({ data: CARDIO_NO_DATA });
    if (url.includes("rag/dashboard")) return Promise.resolve({ data: null });
    if (url.includes("training/today")) return Promise.resolve({ data: TODAY_PREMIUM_PAYLOAD });
    if (url.includes("training/v2/week")) return Promise.resolve({ data: WEEK_PREMIUM_PAYLOAD });
    return Promise.resolve({ data: null });
  });
}

function renderDashboard() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter>
          <Dashboard />
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

async function waitForRender() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 80));
  });
}

function countCalls(pattern) {
  return axios.get.mock.calls.filter(([url]) => url.includes(pattern)).length;
}

// ─── FREE user tests ───────────────────────────────────────────────────────────

describe("FREE — Premium Preview blur cards", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosFree();
  });

  it("FREE_TODAY_PREVIEW_VISIBLE = YES — today-preview-free card is rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const preview = container.querySelector('[data-testid="today-preview-free"]');
    expect(preview).not.toBeNull();
    unmount();
  });

  it("FREE_WEEK_PREVIEW_VISIBLE = YES — week-preview-free card is rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const preview = container.querySelector('[data-testid="week-preview-free"]');
    expect(preview).not.toBeNull();
    unmount();
  });

  it("FREE_TODAY_PREVIEW_HAS_BLUR = YES — blur content area has filter:blur", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const blurEl = container.querySelector('[data-testid="today-preview-blur-content"]');
    expect(blurEl).not.toBeNull();
    const style = blurEl.getAttribute("style") || "";
    expect(style).toMatch(/blur/);
    unmount();
  });

  it("FREE_WEEK_PREVIEW_HAS_BLUR = YES — blur content area has filter:blur", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const blurEl = container.querySelector('[data-testid="week-preview-blur-content"]');
    expect(blurEl).not.toBeNull();
    const style = blurEl.getAttribute("style") || "";
    expect(style).toMatch(/blur/);
    unmount();
  });

  it("FREE_PREMIUM_OVERLAY_VISIBLE = YES — at least one premium overlay is rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const overlayToday = container.querySelector('[data-testid="premium-overlay-today"]');
    const overlayWeek = container.querySelector('[data-testid="premium-overlay-week"]');
    expect(overlayToday).not.toBeNull();
    expect(overlayWeek).not.toBeNull();
    unmount();
  });

  it("FREE_PREMIUM_CTA_VISIBLE = YES — CTA buttons are rendered with /subscription href", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const ctaToday = container.querySelector('[data-testid="premium-cta-today"]');
    const ctaWeek = container.querySelector('[data-testid="premium-cta-week"]');
    expect(ctaToday).not.toBeNull();
    expect(ctaWeek).not.toBeNull();
    expect(ctaToday.getAttribute("href")).toBe("/subscription");
    expect(ctaWeek.getAttribute("href")).toBe("/subscription");
    unmount();
  });

  it("/training/today CALLS = 0 for FREE", async () => {
    const { unmount } = renderDashboard();
    await waitForRender();
    expect(countCalls("training/today")).toBe(0);
    unmount();
  });

  it("/training/v2/week CALLS = 0 for FREE", async () => {
    const { unmount } = renderDashboard();
    await waitForRender();
    expect(countCalls("training/v2/week")).toBe(0);
    unmount();
  });

  it("/rag/dashboard CALLS = 0 for FREE", async () => {
    const { unmount } = renderDashboard();
    await waitForRender();
    expect(countCalls("rag/dashboard")).toBe(0);
    unmount();
  });

  it('FREE_PREMIUM_REAL_DATA_IN_DOM = NO — SECRET_PREMIUM_WORKOUT absent from DOM', async () => {
    // Even if the mock were called, the data must not be in DOM
    // Setup with premium payload available but FREE tier
    axios.get.mockImplementation((url) => {
      if (url.includes("dashboard/insight")) return Promise.resolve({ data: INSIGHT_PAYLOAD });
      if (url.includes("run-index")) return Promise.resolve({ data: CARDIO_NO_DATA });
      if (url.includes("training/today")) return Promise.resolve({ data: TODAY_PREMIUM_PAYLOAD });
      if (url.includes("training/v2/week")) return Promise.resolve({ data: WEEK_PREMIUM_PAYLOAD });
      return Promise.resolve({ data: null });
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();
    expect(container.textContent).not.toContain(SECRET_TODAY);
    unmount();
  });

  it('FREE_PREMIUM_REAL_DATA_IN_DOM = NO — SECRET_PREMIUM_WEEK_TARGET absent from DOM', async () => {
    axios.get.mockImplementation((url) => {
      if (url.includes("dashboard/insight")) return Promise.resolve({ data: INSIGHT_PAYLOAD });
      if (url.includes("run-index")) return Promise.resolve({ data: CARDIO_NO_DATA });
      if (url.includes("training/today")) return Promise.resolve({ data: TODAY_PREMIUM_PAYLOAD });
      if (url.includes("training/v2/week")) return Promise.resolve({ data: WEEK_PREMIUM_PAYLOAD });
      return Promise.resolve({ data: null });
    });
    const { container, unmount } = renderDashboard();
    await waitForRender();
    expect(container.textContent).not.toContain(SECRET_WEEK);
    unmount();
  });

  it("FREE — real today-workout-card (PREMIUM) is NOT rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const realCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(realCard).toBeNull();
    unmount();
  });

  it("FREE — real weekly-target-card (PREMIUM) is NOT rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const realCard = container.querySelector('[data-testid="weekly-target-card"]');
    expect(realCard).toBeNull();
    unmount();
  });
});

// ─── TRIAL/PREMIUM user tests ──────────────────────────────────────────────────

describe("TRIAL/PREMIUM — real cards, no blur preview", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false });
    setupAxiosPremium();
  });

  it("TRIAL/PREMIUM — today-workout-card (real) is rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const realCard = container.querySelector('[data-testid="today-workout-card"]');
    expect(realCard).not.toBeNull();
    unmount();
  });

  it("TRIAL/PREMIUM — today-preview-free blur card is NOT rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const preview = container.querySelector('[data-testid="today-preview-free"]');
    expect(preview).toBeNull();
    unmount();
  });

  it("TRIAL/PREMIUM — week-preview-free blur card is NOT rendered", async () => {
    const { container, unmount } = renderDashboard();
    await waitForRender();
    const preview = container.querySelector('[data-testid="week-preview-free"]');
    expect(preview).toBeNull();
    unmount();
  });

  it("TRIAL/PREMIUM — /training/today is called", async () => {
    const { unmount } = renderDashboard();
    await waitForRender();
    expect(countCalls("training/today")).toBeGreaterThanOrEqual(1);
    unmount();
  });

  it("TRIAL/PREMIUM — /training/v2/week is called", async () => {
    const { unmount } = renderDashboard();
    await waitForRender();
    expect(countCalls("training/v2/week")).toBeGreaterThanOrEqual(1);
    unmount();
  });
});

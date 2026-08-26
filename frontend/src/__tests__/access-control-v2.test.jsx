/**
 * PR #201 — Access Control Frontend V2 — Tests
 *
 * Proves:
 *
 * FREE DASHBOARD:
 *   - dashboard/insight appelé
 *   - run-index appelé
 *   - rag/dashboard = 0
 *   - training/today = 0
 *   - training/v2/week = 0
 *
 * FREE PROGRESS:
 *   - Paywall visible
 *   - TOTAL DATA API CALLS = 0
 *
 * FAIL CLOSED:
 *   - pendant loading/error access
 *   - aucun appel Premium
 *
 * TRIAL:
 *   - Dashboard appelle endpoints Premium
 *   - Progress charge normalement
 *
 * PREMIUM:
 *   - même comportement fonctionnel que TRIAL
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Dashboard from "@/pages/Dashboard";
import Progress from "@/pages/Progress";
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
  useUnitSystem: () => ({ unitSystem: "metric", t: (k) => k }),
}));
jest.mock("@/components/Paywall", () => ({
  __esModule: true,
  default: ({ language, returnPath } = {}) => (
    <div data-testid="paywall">Paywall</div>
  ),
}));

// Controllable subscription mock
let mockSubState = { isFree: true, loading: false, hasPremiumAccess: false, isTrial: false, isPremium: false };
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => mockSubState,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const INSIGHT_DATA = { week: { sessions: 2, volume_km: 20 }, month: { volume_km: 40 } };
const RUN_INDEX_DATA = {
  mock: false,
  recommendation_color: "green",
  metrics: { run_readiness: 72, hrv_status: "green", rhr_status: "gray", sleep_status: "green", training_load_status: "green" },
  history: [],
};
const STATS_DATA = { sessions_7_days: 3, km_7_days: 25, km_30_days: 80 };

function setupAxiosDefault() {
  axios.get.mockImplementation((url) => {
    if (url.includes("dashboard/insight")) return Promise.resolve({ data: INSIGHT_DATA });
    if (url.includes("run-index/history")) return Promise.resolve({ data: { history: [] } });
    if (url.includes("run-index")) return Promise.resolve({ data: RUN_INDEX_DATA });
    if (url.includes("rag/dashboard")) return Promise.resolve({ data: { rag: "data" } });
    if (url.includes("training/today")) return Promise.resolve({ data: { status: "success", session: null } });
    if (url.includes("training/v2/week")) return Promise.resolve({ data: { sessions: [] } });
    if (url.includes("stats")) return Promise.resolve({ data: STATS_DATA });
    if (url.includes("training/race-predictions")) return Promise.resolve({ data: null });
    if (url.includes("training/v2/cycle")) return Promise.resolve({ data: null });
    if (url.includes("garmin/vo2max-history")) return Promise.resolve({ data: null });
    if (url.includes("garmin/daily-metrics")) return Promise.resolve({ data: { count: 0 } });
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
    unmount: () => { act(() => root.unmount()); container.remove(); },
  };
}

function renderProgress() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter>
          <Progress />
        </MemoryRouter>
      </LanguageProvider>
    );
  });
  return {
    container,
    unmount: () => { act(() => root.unmount()); container.remove(); },
  };
}

async function wait() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 80));
  });
}

function countCalls(pattern) {
  return axios.get.mock.calls.filter(([url]) => url.includes(pattern)).length;
}

// ---------------------------------------------------------------------------
// FREE DASHBOARD
// ---------------------------------------------------------------------------
describe("FREE Dashboard — access control", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSubState = { isFree: true, loading: false, hasPremiumAccess: false, isTrial: false, isPremium: false };
    setupAxiosDefault();
  });

  it("calls dashboard/insight", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("dashboard/insight")).toBe(1);
    unmount();
  });

  it("calls run-index", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("run-index")).toBeGreaterThanOrEqual(1);
    unmount();
  });

  it("does NOT call rag/dashboard", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("rag/dashboard")).toBe(0);
    unmount();
  });

  it("does NOT call training/today", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("training/today")).toBe(0);
    unmount();
  });

  it("does NOT call training/v2/week", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("training/v2/week")).toBe(0);
    unmount();
  });
});

// ---------------------------------------------------------------------------
// FREE PROGRESS
// ---------------------------------------------------------------------------
describe("FREE Progress — paywall + zero data calls", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSubState = { isFree: true, loading: false, hasPremiumAccess: false, isTrial: false, isPremium: false };
    setupAxiosDefault();
  });

  it("shows Paywall component", async () => {
    const { container, unmount } = renderProgress();
    await wait();
    const paywall = container.querySelector("[data-testid='paywall']");
    expect(paywall).not.toBeNull();
    unmount();
  });

  it("makes ZERO data API calls on progress page", async () => {
    const { unmount } = renderProgress();
    await wait();
    const dataCalls = axios.get.mock.calls.filter(([url]) =>
      url.includes("stats") ||
      url.includes("run-index") ||
      url.includes("training/race-predictions") ||
      url.includes("training/v2/cycle") ||
      url.includes("garmin/vo2max-history") ||
      url.includes("garmin/daily-metrics") ||
      url.includes("run-index/history")
    );
    expect(dataCalls.length).toBe(0);
    unmount();
  });
});

// ---------------------------------------------------------------------------
// FAIL CLOSED — loading/error access
// ---------------------------------------------------------------------------
describe("FAIL CLOSED — loading subscription", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // loading=true: subscription not yet resolved
    mockSubState = { isFree: true, loading: true, hasPremiumAccess: false, isTrial: false, isPremium: false };
    setupAxiosDefault();
  });

  it("Dashboard does NOT call Premium endpoints while subscription is loading", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("rag/dashboard")).toBe(0);
    expect(countCalls("training/today")).toBe(0);
    expect(countCalls("training/v2/week")).toBe(0);
    unmount();
  });

  it("Progress makes ZERO data calls while subscription is loading", async () => {
    const { unmount } = renderProgress();
    await wait();
    const premiumCalls = axios.get.mock.calls.filter(([url]) =>
      url.includes("stats") ||
      url.includes("training/race-predictions") ||
      url.includes("training/v2/cycle") ||
      url.includes("garmin")
    );
    expect(premiumCalls.length).toBe(0);
    unmount();
  });
});

// ---------------------------------------------------------------------------
// TRIAL
// ---------------------------------------------------------------------------
describe("TRIAL — Dashboard calls Premium endpoints", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSubState = { isFree: false, loading: false, hasPremiumAccess: true, isTrial: true, isPremium: false };
    setupAxiosDefault();
  });

  it("calls dashboard/insight", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("dashboard/insight")).toBe(1);
    unmount();
  });

  it("calls rag/dashboard", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("rag/dashboard")).toBe(1);
    unmount();
  });

  it("calls training/today", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("training/today")).toBeGreaterThanOrEqual(1);
    unmount();
  });

  it("calls training/v2/week", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("training/v2/week")).toBe(1);
    unmount();
  });
});

describe("TRIAL — Progress loads normally (no paywall)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSubState = { isFree: false, loading: false, hasPremiumAccess: true, isTrial: true, isPremium: false };
    setupAxiosDefault();
  });

  it("does NOT show Paywall", async () => {
    const { container, unmount } = renderProgress();
    await wait();
    const paywall = container.querySelector("[data-testid='paywall']");
    expect(paywall).toBeNull();
    unmount();
  });

  it("calls stats endpoint", async () => {
    const { unmount } = renderProgress();
    await wait();
    expect(countCalls("stats")).toBeGreaterThanOrEqual(1);
    unmount();
  });
});

// ---------------------------------------------------------------------------
// PREMIUM — same functional path as TRIAL
// ---------------------------------------------------------------------------
describe("PREMIUM — same functional behavior as TRIAL", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSubState = { isFree: false, loading: false, hasPremiumAccess: true, isTrial: false, isPremium: true };
    setupAxiosDefault();
  });

  it("Dashboard calls rag/dashboard", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("rag/dashboard")).toBe(1);
    unmount();
  });

  it("Dashboard calls training/today", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("training/today")).toBeGreaterThanOrEqual(1);
    unmount();
  });

  it("Dashboard calls training/v2/week", async () => {
    const { unmount } = renderDashboard();
    await wait();
    expect(countCalls("training/v2/week")).toBe(1);
    unmount();
  });

  it("Progress does NOT show Paywall", async () => {
    const { container, unmount } = renderProgress();
    await wait();
    const paywall = container.querySelector("[data-testid='paywall']");
    expect(paywall).toBeNull();
    unmount();
  });

  it("Progress calls stats endpoint", async () => {
    const { unmount } = renderProgress();
    await wait();
    expect(countCalls("stats")).toBeGreaterThanOrEqual(1);
    unmount();
  });
});

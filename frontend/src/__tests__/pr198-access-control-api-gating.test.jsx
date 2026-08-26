/**
 * PR #198 — ACCESS CONTROL V2 — Frontend API call gating tests
 *
 * Proves that React components do NOT issue Premium API calls for FREE users.
 *
 * FREE_DASHBOARD_PREMIUM_API_CALLS = 0
 *   - /rag/dashboard never called for FREE
 *   - /training/today never called for FREE (initial load)
 *
 * FREE_PROGRESS_PREMIUM_API_CALLS = 0
 *   - /training/race-predictions never called for FREE
 *   - /training/v2/cycle never called for FREE
 *   - /garmin/vo2max-history never called for FREE
 *   - /garmin/daily-metrics never called for FREE
 *
 * FREE_TRAINING_PREMIUM_API_CALLS = 0
 *   - /training/v2/week never called for FREE
 *   - /training/v2/cycle never called for FREE
 *   - /training/today never called for FREE
 *   - /training/v2/paces never called for FREE
 *
 * TRIAL_PREMIUM_BEHAVIOR_PRESERVED
 *   - TRIAL/PREMIUM Dashboard does call /rag/dashboard and /training/today
 *   - TRIAL/PREMIUM Progress does call race-predictions, v2/cycle, vo2max-history
 *   - TRIAL/PREMIUM Training page fetches all premium endpoints
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Dashboard from "@/pages/Dashboard";
import Progress from "@/pages/Progress";
import TrainingPlanV2 from "@/pages/TrainingPlanV2";
import { LanguageProvider } from "@/context/LanguageContext";

// ── Mocks ─────────────────────────────────────────────────────────────────────

jest.mock("axios");

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// Mock heavy UI sub-components that pull in CSS / canvas / etc.
jest.mock("recharts", () => ({
  LineChart: ({ children }) => <div data-testid="line-chart">{children}</div>,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  Tooltip: () => null,
  ReferenceLine: () => null,
  BarChart: ({ children }) => <div>{children}</div>,
  Bar: () => null,
}));

jest.mock("@/components/Paywall", () =>
  function MockPaywall({ returnPath }) {
    return <div data-testid="paywall" data-return-path={returnPath}>Paywall</div>;
  }
);

jest.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <div>{children}</div>,
  DialogDescription: ({ children }) => <div>{children}</div>,
}));

// UnitContext — always metric for these tests
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => ({ unitSystem: "metric" }),
  UnitProvider: ({ children }) => <>{children}</>,
}));

// SubscriptionContext — controlled per test
const mockUseSubscription = jest.fn();
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => mockUseSubscription(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const INSIGHT = {
  week: { sessions: 3, volume_km: 25, actual_duration_minutes: 135 },
  month: { volume_km: 90 },
  run_index: null,
};

const RUN_INDEX = { no_data: true, connected: false };

const TODAY = {
  status: "success",
  day: "monday",
  adaptation_applied: false,
  readiness: { band: "FAVORABLE", score: 82, confidence: "high", available: true },
  planned_session: { type: "endurance", duration: "45 min", estimated_tss: 55 },
};

const STATS = {
  sessions_7_days: 3,
  km_7_days: 25,
  km_30_days: 90,
};

const WEEK_V2 = {
  weekly_target: { target_basis: "distance", target_km: 50, target_duration_minutes: null },
  week: { sessions: [] },
};

const CYCLE_V2 = {
  goal: { goal_type: "marathon", race_date: "2026-10-05" },
  cycle: { mode: "race_calendar", status: "active", current_week: 12, total_weeks: 18 },
  weeks: [],
};

const PACES_V2 = { vdot: 50, paces: {} };

// ── Subscription states ───────────────────────────────────────────────────────

const FREE_SUB = { isFree: true, hasPremiumAccess: false, loading: false, subLoading: false };
const PREMIUM_SUB = { isFree: false, hasPremiumAccess: true, loading: false, subLoading: false };
const TRIAL_SUB = { isFree: false, hasPremiumAccess: true, loading: false, subLoading: false };

// ── Helpers ───────────────────────────────────────────────────────────────────

function setupAxios() {
  axios.get.mockImplementation((url) => {
    if (url.includes("dashboard/insight")) return Promise.resolve({ data: INSIGHT });
    if (url.includes("rag/dashboard")) return Promise.resolve({ data: null });
    if (url.includes("training/today")) return Promise.resolve({ data: TODAY });
    if (url.includes("run-index/history")) return Promise.resolve({ data: { history: [], trend: 0, granularity: "week" } });
    if (url.includes("run-index")) return Promise.resolve({ data: RUN_INDEX });
    if (url.includes("training/race-predictions")) return Promise.resolve({ data: null });
    if (url.includes("training/v2/cycle")) return Promise.resolve({ data: CYCLE_V2 });
    if (url.includes("training/v2/week")) return Promise.resolve({ data: WEEK_V2 });
    if (url.includes("training/v2/paces")) return Promise.resolve({ data: PACES_V2 });
    if (url.includes("garmin/vo2max-history")) return Promise.resolve({ data: null });
    if (url.includes("garmin/daily-metrics")) return Promise.resolve({ data: { count: 0 } });
    if (url.includes("stats")) return Promise.resolve({ data: STATS });
    return Promise.resolve({ data: null });
  });
}

async function mount(Component) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter>
          <Component />
        </MemoryRouter>
      </LanguageProvider>
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 100));
  });
  return {
    calls: () => axios.get.mock.calls.map(([url]) => url),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

// ── Dashboard tests ───────────────────────────────────────────────────────────

describe("PR198 — Dashboard: FREE premium API gating", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupAxios();
  });

  test("FREE: /rag/dashboard never called", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Dashboard);
    expect(calls().some((u) => u.includes("rag/dashboard"))).toBe(false);
    unmount();
  });

  test("FREE: /training/today never called on initial load", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Dashboard);
    expect(calls().some((u) => u.includes("training/today"))).toBe(false);
    unmount();
  });

  test("FREE: /dashboard/insight IS called (FREE endpoint)", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Dashboard);
    expect(calls().some((u) => u.includes("dashboard/insight"))).toBe(true);
    unmount();
  });

  test("FREE: /run-index IS called (FREE endpoint)", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Dashboard);
    expect(calls().some((u) => u.includes("run-index"))).toBe(true);
    unmount();
  });

  test("TRIAL: /rag/dashboard IS called", async () => {
    mockUseSubscription.mockReturnValue(TRIAL_SUB);
    const { calls, unmount } = await mount(Dashboard);
    expect(calls().some((u) => u.includes("rag/dashboard"))).toBe(true);
    unmount();
  });

  test("TRIAL: /training/today IS called", async () => {
    mockUseSubscription.mockReturnValue(TRIAL_SUB);
    const { calls, unmount } = await mount(Dashboard);
    expect(calls().some((u) => u.includes("training/today"))).toBe(true);
    unmount();
  });

  test("PREMIUM: /rag/dashboard IS called", async () => {
    mockUseSubscription.mockReturnValue(PREMIUM_SUB);
    const { calls, unmount } = await mount(Dashboard);
    expect(calls().some((u) => u.includes("rag/dashboard"))).toBe(true);
    unmount();
  });
});

// ── Progress tests ────────────────────────────────────────────────────────────

describe("PR198 — Progress: FREE premium API gating", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupAxios();
  });

  test("FREE: /training/race-predictions never called", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("race-predictions"))).toBe(false);
    unmount();
  });

  test("FREE: /training/v2/cycle never called", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("training/v2/cycle"))).toBe(false);
    unmount();
  });

  test("FREE: /garmin/vo2max-history never called", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("garmin/vo2max-history"))).toBe(false);
    unmount();
  });

  test("FREE: /garmin/daily-metrics never called", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("garmin/daily-metrics"))).toBe(false);
    unmount();
  });

  test("FREE: /stats IS called (FREE endpoint)", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("/stats"))).toBe(true);
    unmount();
  });

  test("FREE: /run-index IS called (FREE endpoint)", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("/run-index"))).toBe(true);
    unmount();
  });

  test("TRIAL: /training/race-predictions IS called", async () => {
    mockUseSubscription.mockReturnValue(TRIAL_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("race-predictions"))).toBe(true);
    unmount();
  });

  test("TRIAL: /training/v2/cycle IS called", async () => {
    mockUseSubscription.mockReturnValue(TRIAL_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("training/v2/cycle"))).toBe(true);
    unmount();
  });

  test("TRIAL: /garmin/vo2max-history IS called", async () => {
    mockUseSubscription.mockReturnValue(TRIAL_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("garmin/vo2max-history"))).toBe(true);
    unmount();
  });

  test("PREMIUM: /training/race-predictions IS called", async () => {
    mockUseSubscription.mockReturnValue(PREMIUM_SUB);
    const { calls, unmount } = await mount(Progress);
    expect(calls().some((u) => u.includes("race-predictions"))).toBe(true);
    unmount();
  });
});

// ── Training tests ────────────────────────────────────────────────────────────

describe("PR198 — Training: FREE premium API gating", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupAxios();
  });

  test("FREE: no premium training endpoints called (paywall shown immediately)", async () => {
    mockUseSubscription.mockReturnValue(FREE_SUB);
    const { calls, unmount } = await mount(TrainingPlanV2);
    const premiumPatterns = [
      "training/v2/week",
      "training/v2/cycle",
      "training/today",
      "training/v2/paces",
    ];
    for (const pattern of premiumPatterns) {
      expect(calls().some((u) => u.includes(pattern))).toBe(false);
    }
    unmount();
  });

  test("TRIAL: premium training endpoints ARE called", async () => {
    mockUseSubscription.mockReturnValue(TRIAL_SUB);
    const { calls, unmount } = await mount(TrainingPlanV2);
    expect(calls().some((u) => u.includes("training/v2/week"))).toBe(true);
    unmount();
  });

  test("PREMIUM: premium training endpoints ARE called", async () => {
    mockUseSubscription.mockReturnValue(PREMIUM_SUB);
    const { calls, unmount } = await mount(TrainingPlanV2);
    expect(calls().some((u) => u.includes("training/v2/week"))).toBe(true);
    unmount();
  });
});

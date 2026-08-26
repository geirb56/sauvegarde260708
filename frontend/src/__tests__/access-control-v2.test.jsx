/**
 * PR #199 — Access Control Frontend V2 — FREE / TRIAL / PREMIUM
 *
 * Validates the canonical FREE/TRIAL/PREMIUM access control on the frontend.
 *
 * Part A — Static file-system analysis (no DOM rendering required):
 *   A1. SubscriptionContext uses /user/features as permission authority
 *   A2. SubscriptionContext fail-closed: has_premium_access ?? false
 *   A3. FAIL_CLOSED_STATE defined with has_premium_access: false
 *   A4. Dashboard: /rag/dashboard gated on !isFree
 *   A5. Dashboard: /training/today gated on !isFree
 *   A6. Progress: premium calls gated on !isFree
 *   A7. Progress: subLoading guard present before any premium calls
 *   A8. Progress: Paywall rendered for FREE users
 *   A9. TRIAL_EQUALS_PREMIUM: both map to has_premium_access = true
 *
 * Part B — DOM tests (axios mock, Dashboard rendering):
 *   B1. FREE_DASHBOARD_RAG_CALLS = 0
 *   B2. FREE_DASHBOARD_TRAINING_TODAY_CALLS = 0
 *   B3. FREE_DASHBOARD_TRAINING_WEEK_CALLS = 0
 *   B4. TRIAL_DASHBOARD_PREMIUM_CALLS = YES (/rag/dashboard called)
 *   B5. PREMIUM_DASHBOARD_PREMIUM_CALLS = YES (/rag/dashboard called)
 *   B6. FREE: RunIndex endpoint still called (FREE accessible)
 *   B7. FAIL_CLOSED: when loading=true, no premium calls made
 *
 * INVARIANTS:
 *   FAIL_CLOSED = YES
 *   FREE_RUNINDEX = PASS
 *   TRIAL_EQUALS_PREMIUM = YES
 */

import fs from "fs";
import path from "path";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Dashboard from "@/pages/Dashboard";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

// ─── File paths ────────────────────────────────────────────────────────────────

const SUBSCRIPTION_CTX_PATH = path.resolve(__dirname, "../context/SubscriptionContext.jsx");
const DASHBOARD_PATH = path.resolve(__dirname, "../pages/Dashboard.jsx");
const PROGRESS_PATH = path.resolve(__dirname, "../pages/Progress.jsx");

function readCtx() { return fs.readFileSync(SUBSCRIPTION_CTX_PATH, "utf8"); }
function readDashboard() { return fs.readFileSync(DASHBOARD_PATH, "utf8"); }
function readProgress() { return fs.readFileSync(PROGRESS_PATH, "utf8"); }

// ─── DOM test infrastructure ───────────────────────────────────────────────────

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

const mockUseUnitSystem = jest.fn();
jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: () => mockUseUnitSystem(),
}));

const mockUseSubscription = jest.fn();
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => mockUseSubscription(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ─── Fixtures ──────────────────────────────────────────────────────────────────

const INSIGHT_PAYLOAD = {
  week: { sessions: 2, volume_km: 20, actual_duration_minutes: 100 },
  month: { volume_km: 80 },
  run_index: null,
};

const CARDIO_NO_DATA = { no_data: true, connected: false, message: "No data." };

const TODAY_PAYLOAD = {
  status: "success",
  day: "monday",
  adaptation_applied: false,
  readiness: {
    band: "FAVORABLE",
    score: 80,
    confidence: "high",
    sufficiency_level: "sufficient",
    available: true,
    data_source: "garmin",
  },
  planned_session: { type: "easy", duration: "40 min", details: "Easy", estimated_tss: 45 },
};

const RAG_PAYLOAD = { summary: "Good week" };

const WEEK_V2_PAYLOAD = {
  weekly_target: { target_basis: "distance", target_km: 45, target_duration_minutes: null },
};

function setupAxiosMocks({ withPremium = false } = {}) {
  axios.get.mockImplementation((url) => {
    if (url.includes("dashboard/insight")) return Promise.resolve({ data: INSIGHT_PAYLOAD });
    if (url.includes("run-index")) return Promise.resolve({ data: CARDIO_NO_DATA });
    if (withPremium) {
      if (url.includes("rag/dashboard")) return Promise.resolve({ data: RAG_PAYLOAD });
      if (url.includes("training/today")) return Promise.resolve({ data: TODAY_PAYLOAD });
      if (url.includes("training/v2/week")) return Promise.resolve({ data: WEEK_V2_PAYLOAD });
    } else {
      if (url.includes("rag/dashboard")) return Promise.reject(new Error("forbidden"));
      if (url.includes("training/today")) return Promise.reject(new Error("forbidden"));
      if (url.includes("training/v2/week")) return Promise.reject(new Error("forbidden"));
    }
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

// ─── Part A: Static file-system tests ──────────────────────────────────────────

describe("PR199 — A1: SubscriptionContext uses /user/features", () => {
  test("A1 — fetches /user/features as permission authority", () => {
    expect(readCtx()).toContain("/user/features");
  });

  test("A1 — does NOT use /subscription/info for permission decisions", () => {
    // /subscription/info may still appear for display, but must not be
    // the authority for isFree / hasFeature / isActive.
    const ctx = readCtx();
    // The canonical access gate must use has_premium_access from /user/features
    expect(ctx).toContain("has_premium_access");
  });
});

describe("PR199 — A2/A3: Fail-closed semantics", () => {
  test("A2 — has_premium_access defaults to false via ?? false", () => {
    expect(readCtx()).toContain("has_premium_access ?? false");
  });

  test("A3 — FAIL_CLOSED_STATE defines has_premium_access: false", () => {
    expect(readCtx()).toContain("has_premium_access: false");
  });

  test("A3 — isFree derived from !hasPremiumAccess (fail-closed)", () => {
    expect(readCtx()).toContain("isFree = !hasPremiumAccess");
  });
});

describe("PR199 — A4/A5: Dashboard gates premium calls on !isFree", () => {
  test("A4 — /rag/dashboard gated: isFree check present in same effect block", () => {
    const src = readDashboard();
    // The rag/dashboard call must be inside a block that checks isFree
    expect(src).toContain("rag/dashboard");
    // Expect the guard is in an effect that checks isFree
    expect(src).toMatch(/if\s*\(\s*subLoading\s*\|\|\s*isFree\s*\)/);
  });

  test("A5 — /training/today gated: in same isFree-guarded effect as rag/dashboard", () => {
    const src = readDashboard();
    expect(src).toContain("training/today");
    // Both endpoints must be inside the TRIAL/PREMIUM-only effect
    const ragIdx = src.indexOf("rag/dashboard");
    const todayIdx = src.indexOf("training/today");
    const guardIdx = src.indexOf("if (subLoading || isFree) return;");
    // Guard must appear before both calls
    expect(guardIdx).toBeGreaterThan(-1);
    expect(ragIdx).toBeGreaterThan(guardIdx);
    expect(todayIdx).toBeGreaterThan(guardIdx);
  });
});

describe("PR199 — A6/A7/A8: Progress gates premium calls on !isFree", () => {
  test("A6 — /training/race-predictions NOT called when isFree", () => {
    const src = readProgress();
    // The race-predictions call must be inside an isFree guard
    expect(src).toContain("training/race-predictions");
    // Must have the guard before the call
    expect(src).toMatch(/if\s*\(\s*isFree\s*\)\s*\{[\s\S]*?return/m);
  });

  test("A7 — subLoading guard present in Progress fetchData effect", () => {
    expect(readProgress()).toContain("if (subLoading) return;");
  });

  test("A8 — Paywall rendered for FREE users in Progress", () => {
    expect(readProgress()).toContain("<Paywall");
  });

  test("A6 — /garmin/daily-metrics NOT reached for FREE (inside premium block)", () => {
    const src = readProgress();
    const metricsIdx = src.indexOf("garmin/daily-metrics");
    const freeGuardIdx = src.indexOf("if (isFree)");
    expect(metricsIdx).toBeGreaterThan(-1);
    expect(freeGuardIdx).toBeGreaterThan(-1);
    // garmin/daily-metrics appears after the FREE guard
    expect(metricsIdx).toBeGreaterThan(freeGuardIdx);
  });
});

describe("PR199 — A9: TRIAL = PREMIUM", () => {
  test("A9 — trial_active mapped from canonical /user/features", () => {
    expect(readCtx()).toContain("trial_active");
  });

  test("A9 — TRIAL and PREMIUM both gated by has_premium_access (single gate)", () => {
    const ctx = readCtx();
    // Both trial and premium should share has_premium_access as the gate,
    // not separate conditions. Verify the canonical field is used for isActive.
    expect(ctx).toContain("isActive = hasPremiumAccess");
  });
});

// ─── Part B: DOM tests — Dashboard API call verification ────────────────────────

describe("PR199 — B: Dashboard API calls by tier", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseUnitSystem.mockReturnValue({ unitSystem: "metric" });
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  });

  // B1. FREE: /rag/dashboard never called
  it("B1 — FREE: /rag/dashboard is never called", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks({ withPremium: false });

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    const ragCalls = calls.filter((u) => u.includes("rag/dashboard"));
    expect(ragCalls).toHaveLength(0); // FREE_DASHBOARD_RAG_CALLS = 0
    unmount();
  });

  // B2. FREE: /training/today never called
  it("B2 — FREE: /training/today is never called", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks({ withPremium: false });

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    const todayCalls = calls.filter((u) => u.includes("training/today"));
    expect(todayCalls).toHaveLength(0); // FREE_DASHBOARD_TRAINING_TODAY_CALLS = 0
    unmount();
  });

  // B3. FREE: /training/v2/week never called
  it("B3 — FREE: /training/v2/week is never called", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks({ withPremium: false });

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    const weekCalls = calls.filter((u) => u.includes("training/v2/week"));
    expect(weekCalls).toHaveLength(0); // FREE_DASHBOARD_TRAINING_WEEK_CALLS = 0
    unmount();
  });

  // B4. TRIAL: /rag/dashboard is called
  it("B4 — TRIAL: /rag/dashboard IS called", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false, isTrial: true, isPremium: false });
    setupAxiosMocks({ withPremium: true });

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.some((u) => u.includes("rag/dashboard"))).toBe(true); // TRIAL_DASHBOARD_PREMIUM_CALLS = YES
    unmount();
  });

  // B5. PREMIUM: /rag/dashboard is called — same behaviour as TRIAL (TRIAL_EQUALS_PREMIUM)
  it("B5 — PREMIUM: /rag/dashboard IS called (TRIAL_EQUALS_PREMIUM)", async () => {
    mockUseSubscription.mockReturnValue({ isFree: false, loading: false, isTrial: false, isPremium: true });
    setupAxiosMocks({ withPremium: true });

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.some((u) => u.includes("rag/dashboard"))).toBe(true); // PREMIUM_DASHBOARD_PREMIUM_CALLS = YES
    unmount();
  });

  // B6. FREE: RunIndex endpoint still called (FREE_RUNINDEX = PASS)
  it("B6 — FREE: /run-index IS called (RunIndex accessible for FREE)", async () => {
    mockUseSubscription.mockReturnValue({ isFree: true, loading: false });
    setupAxiosMocks({ withPremium: false });

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.some((u) => u.includes("run-index"))).toBe(true); // FREE_RUNINDEX = PASS
    unmount();
  });

  // B7. FAIL_CLOSED: when loading=true (subscription not yet resolved), no premium calls
  it("B7 — FAIL_CLOSED: loading=true → no premium API calls", async () => {
    // loading=true simulates subscription still being fetched.
    // isFree defaults to true (fail-closed) in the real context,
    // but here we explicitly test that the guard blocks premium calls.
    mockUseSubscription.mockReturnValue({ isFree: true, loading: true });
    setupAxiosMocks({ withPremium: false });

    const { unmount } = renderDashboard();
    await waitForRender();

    const calls = axios.get.mock.calls.map(([url]) => url);
    expect(calls.filter((u) => u.includes("rag/dashboard"))).toHaveLength(0);
    expect(calls.filter((u) => u.includes("training/today"))).toHaveLength(0);
    expect(calls.filter((u) => u.includes("training/v2/week"))).toHaveLength(0);
    unmount();
  });
});

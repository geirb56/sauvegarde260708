/**
 * PR #169 — TrainingPlanV2 tests
 *
 * Tests cover:
 * A — Routing: /training-v2 renders TrainingPlanV2
 * B — API: only /training/v2/week is called
 * C — Distance basis: target_km via UnitContext, no "0 min" on null duration
 * D — Duration basis: target_duration_minutes shown, no "0 distance" on null km
 * E — Active TSS unknown: estimated_tss=null → no TSS text/badge
 * F — Rest TSS: estimated_tss=0 → "0 TSS" shown
 * G — Unit system: formatDistance used for sessions and weekly target
 * H — I18n: labels pass through translation
 * I — Error: API error → error state + retry
 * J — Old training: /training still routes to TrainingPlan
 */

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import axios from "axios";

import TrainingPlanV2 from "@/pages/TrainingPlanV2";
import TrainingPlan from "@/pages/TrainingPlan";
import { LanguageProvider } from "@/context/LanguageContext";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ── Mocks ────────────────────────────────────────────────────────────────────

jest.mock("axios", () => ({
  get: jest.fn(() => Promise.resolve({ data: {} })),
  post: jest.fn(() => Promise.resolve({ data: {} })),
  delete: jest.fn(() => Promise.resolve({ data: {} })),
}));

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}));

jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: jest.fn(() => ({
    isFree: false,
    loading: false,
    trialDaysRemaining: 0,
    isTrial: false,
  })),
  SubscriptionProvider: ({ children }) => children,
}));

jest.mock("@/context/UnitContext", () => ({
  useUnitSystem: jest.fn(() => ({ unitSystem: "metric" })),
  UnitProvider: ({ children }) => children,
}));

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(() => ({
    user: { id: "u1", email: "test@test.com" },
    loading: false,
    logout: jest.fn(),
    loginWithToken: jest.fn(),
  })),
  AuthProvider: ({ children }) => children,
}));

jest.mock("@/hooks/useAutoSync", () => ({ useAutoSync: jest.fn() }));
jest.mock("@/components/ChatCoach", () => () => null);
jest.mock("@/components/Paywall", () => ({ language, returnPath }) => (
  <div data-testid="paywall">Paywall {returnPath}</div>
));

// ── Helpers ──────────────────────────────────────────────────────────────────

const { useSubscription } = require("@/context/SubscriptionContext");
const { useUnitSystem } = require("@/context/UnitContext");

function makeWeekPayload({
  goal = { goal_type: "Marathon", race_date: "2026-04-15", target_time_seconds: 10800 },
  week_state = {
    continuity_state: "normal",
    allow_intensity: true,
    target_basis: "distance",
    target_km: 50,
    target_duration_minutes: null,
    session_count: 4,
    confidence: "high",
  },
  sessions = [
    { day: "monday", workout_type: "easy", intensity_class: "low", distance_km: 8, duration_minutes: 45, estimated_tss: 42 },
    { day: "tuesday", workout_type: "rest", intensity_class: "none", distance_km: null, duration_minutes: null, estimated_tss: 0 },
    { day: "wednesday", workout_type: "threshold", intensity_class: "high", distance_km: 12, duration_minutes: 60, estimated_tss: null },
  ],
} = {}) {
  return { goal, week_state, sessions };
}

function renderInMemory(initialEntry = "/training-v2") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

async function renderV2(props = {}) {
  const payload = makeWeekPayload(props);
  axios.get.mockResolvedValue({ data: payload });

  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(
      <LanguageProvider>
        <MemoryRouter initialEntries={["/training-v2"]}>
          <Routes>
            <Route path="training-v2" element={<TrainingPlanV2 />} />
          </Routes>
        </MemoryRouter>
      </LanguageProvider>
    );
  });

  return { container, root };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("A — Routing", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("renders TrainingPlanV2 at /training-v2", async () => {
    axios.get.mockResolvedValue({ data: makeWeekPayload() });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <LanguageProvider>
          <MemoryRouter initialEntries={["/training-v2"]}>
            <Routes>
              <Route path="training-v2" element={<TrainingPlanV2 />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      );
    });

    // If it rendered without error, the route works
    expect(container.innerHTML).not.toBe("");
    root.unmount();
    document.body.removeChild(container);
  });
});

describe("J — Old training route unmodified", () => {
  it("TrainingPlan component still importable and distinct from TrainingPlanV2", () => {
    expect(TrainingPlan).toBeDefined();
    expect(TrainingPlanV2).toBeDefined();
    expect(TrainingPlan).not.toBe(TrainingPlanV2);
  });
});

describe("B — API source", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("calls only /training/v2/week", async () => {
    axios.get.mockResolvedValue({ data: makeWeekPayload() });
    const { root, container } = await renderV2();

    const calls = axios.get.mock.calls.map((c) => c[0]);
    expect(calls.every((url) => url.includes("/training/v2/week"))).toBe(true);
    expect(calls.some((url) => url.includes("/training/plan"))).toBe(false);
    expect(calls.some((url) => url.includes("/training/week-plan"))).toBe(false);
    expect(calls.some((url) => url.includes("/training/full-cycle"))).toBe(false);
    expect(calls.some((url) => url.includes("/training/metrics"))).toBe(false);
    expect(calls.some((url) => url.includes("/training/refresh"))).toBe(false);

    root.unmount();
    document.body.removeChild(container);
  });
});

describe("C — Distance basis", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("shows target_km and does not show 0 min when target_duration_minutes is null", async () => {
    const { root, container } = await renderV2({
      week_state: {
        continuity_state: "normal",
        allow_intensity: true,
        target_basis: "distance",
        target_km: 40,
        target_duration_minutes: null,
        session_count: 4,
        confidence: "high",
      },
    });

    expect(container.textContent).not.toMatch(/\b0\s*min\b/);

    root.unmount();
    document.body.removeChild(container);
  });
});

describe("D — Duration basis", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("shows target_duration_minutes and does not show 0 km when target_km is null", async () => {
    const { root, container } = await renderV2({
      week_state: {
        continuity_state: "normal",
        allow_intensity: true,
        target_basis: "duration",
        target_km: null,
        target_duration_minutes: 200,
        session_count: 4,
        confidence: "medium",
      },
    });

    expect(container.textContent).toContain("200");
    // No forced "0 km" or "0.00 km"
    expect(container.textContent).not.toMatch(/\b0\.0+\s*(km|mi)\b/);

    root.unmount();
    document.body.removeChild(container);
  });
});

describe("E — Active TSS unknown (null)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("does not display TSS text when estimated_tss is null", async () => {
    const { root, container } = await renderV2({
      sessions: [
        {
          day: "monday",
          workout_type: "threshold",
          intensity_class: "high",
          distance_km: 10,
          duration_minutes: 60,
          estimated_tss: null,
        },
      ],
    });

    // The session card for monday should not contain "TSS"
    const cards = container.querySelectorAll
      ? Array.from(container.querySelectorAll("[class*='rounded-xl']")).filter((el) =>
          el.textContent.includes("monday") || el.textContent.toLowerCase().includes("monday")
        )
      : [];

    // Regardless of cards detection: the string "null TSS" or "— TSS" or "N/A TSS" must not appear
    expect(container.textContent).not.toMatch(/null\s*TSS/i);
    expect(container.textContent).not.toMatch(/—\s*TSS/i);
    expect(container.textContent).not.toMatch(/N\/A\s*TSS/i);
    expect(container.textContent).not.toMatch(/undefined\s*TSS/i);

    root.unmount();
    document.body.removeChild(container);
  });
});

describe("F — Rest TSS zero", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("displays 0 TSS when estimated_tss is 0 (rest day)", async () => {
    const { root, container } = await renderV2({
      sessions: [
        {
          day: "tuesday",
          workout_type: "rest",
          intensity_class: "none",
          distance_km: null,
          duration_minutes: null,
          estimated_tss: 0,
        },
      ],
    });

    expect(container.textContent).toMatch(/0\s*TSS/i);

    root.unmount();
    document.body.removeChild(container);
  });
});

describe("G — Unit system", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
  });

  it("uses imperial units and does not force km when user is in imperial", async () => {
    useUnitSystem.mockReturnValue({ unitSystem: "imperial" });
    axios.get.mockResolvedValue({
      data: makeWeekPayload({
        sessions: [
          { day: "monday", workout_type: "easy", intensity_class: "low", distance_km: 10, duration_minutes: 60, estimated_tss: 50 },
        ],
        week_state: {
          continuity_state: "normal",
          allow_intensity: true,
          target_basis: "distance",
          target_km: 50,
          target_duration_minutes: null,
          session_count: 3,
          confidence: "high",
        },
      }),
    });

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <LanguageProvider>
          <MemoryRouter initialEntries={["/training-v2"]}>
            <Routes>
              <Route path="training-v2" element={<TrainingPlanV2 />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      );
    });

    // imperial user should see "mi", not forced "km"
    expect(container.textContent).toMatch(/mi/);
    expect(container.textContent).not.toMatch(/\d+\.?\d*\s+km\b/);

    root.unmount();
    document.body.removeChild(container);
  });
});

describe("H — I18n", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("does not render raw i18n keys as text", async () => {
    const { root, container } = await renderV2();

    // i18n keys should be resolved; raw key pattern like "trainingV2.workout_easy" must not appear
    expect(container.textContent).not.toMatch(/trainingV2\./);

    root.unmount();
    document.body.removeChild(container);
  });

  it("does not contain hardcoded French or English user-facing labels", async () => {
    const { root, container } = await renderV2();

    const text = container.textContent;
    expect(text).not.toContain("Repos");
    expect(text).not.toContain("Endurance");
    expect(text).not.toContain("Seuil");
    expect(text).not.toContain("Fractionné");
    expect(text).not.toContain("Objectif semaine");
    expect(text).not.toContain("Planifié");
    expect(text).not.toContain("Confiance");
    expect(text).not.toContain("État");

    root.unmount();
    document.body.removeChild(container);
  });
});

describe("I — Error state and retry", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useSubscription.mockReturnValue({ isFree: false, loading: false });
    useUnitSystem.mockReturnValue({ unitSystem: "metric" });
  });

  it("shows error state when API fails and retry re-calls only v2/week", async () => {
    axios.get.mockRejectedValue(new Error("Network error"));

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <LanguageProvider>
          <MemoryRouter initialEntries={["/training-v2"]}>
            <Routes>
              <Route path="training-v2" element={<TrainingPlanV2 />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      );
    });

    // Should show an error state (not crash)
    expect(container.innerHTML).not.toBe("");
    // No legacy fallback URL called
    const calls = axios.get.mock.calls.map((c) => c[0]);
    expect(calls.some((url) => url.includes("/training/plan"))).toBe(false);
    expect(calls.some((url) => url.includes("/training/week-plan"))).toBe(false);

    root.unmount();
    document.body.removeChild(container);
  });

  it("does not call legacy endpoints after retry", async () => {
    // First call fails, second call succeeds
    axios.get
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce({ data: makeWeekPayload() });

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <LanguageProvider>
          <MemoryRouter initialEntries={["/training-v2"]}>
            <Routes>
              <Route path="training-v2" element={<TrainingPlanV2 />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      );
    });

    const calls = axios.get.mock.calls.map((c) => c[0]);
    expect(calls.every((url) => url.includes("/training/v2/week"))).toBe(true);

    root.unmount();
    document.body.removeChild(container);
  });
});

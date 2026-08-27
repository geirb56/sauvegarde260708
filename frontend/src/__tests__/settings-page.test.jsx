import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Settings from "@/pages/Settings";
import { LanguageProvider } from "@/context/LanguageContext";
import { UnitProvider } from "@/context/UnitContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";
import { UNIT_SYSTEM_KEY } from "@/utils/units";

const mockUseAuth = jest.fn();
const mockUseSubscription = jest.fn();
const mockUseGarminSyncProgress = jest.fn();

jest.mock("axios");
jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));
jest.mock("@/context/AuthContext", () => ({
  useAuth: (...args) => mockUseAuth(...args),
}));
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: (...args) => mockUseSubscription(...args),
}));
jest.mock("@/hooks/useGarminSyncProgress", () => ({
  useGarminSyncProgress: (...args) => mockUseGarminSyncProgress(...args),
}));

const { toast } = require("sonner");

function createApiState({
  fullCycle = {
    goal: "MARATHON",
    sessions_per_week: 4,
    start_date: "2026-08-27",
  },
  cycle = {
    goal: { goal_type: "marathon", race_date: "2026-10-12", target_time_seconds: 13500 },
    cycle: { start_date: "2026-08-27", status: "active", days_to_race: 46 },
    weeks: [],
  },
  userGoal = {
    event_name: "Berlin Marathon",
    event_date: "2026-10-12",
    distance_type: "marathon",
    distance_km: 42.195,
    target_time_minutes: 225,
  },
  garminStatus = {
    connected: true,
    last_sync: "2026-08-26T09:30:00Z",
    activity_count: 18,
    sync_status: { status: "complete", activities_count: 18 },
  },
} = {}) {
  return { fullCycle, cycle, userGoal, garminStatus };
}

function mockAxiosApi(state = createApiState()) {
  axios.get.mockImplementation((url) => {
    if (url.includes("/training/full-cycle")) return Promise.resolve({ data: state.fullCycle });
    if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: state.cycle });
    if (url.includes("/user/goal")) return Promise.resolve({ data: state.userGoal });
    if (url.includes("/garmin/status")) return Promise.resolve({ data: state.garminStatus });
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
  axios.post.mockResolvedValue({ data: { status: "connected" } });
}

function renderPage({ lang = "en", unitSystem = "metric" } = {}) {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  window.localStorage.setItem(UNIT_SYSTEM_KEY, unitSystem);
  return render(
    <UnitProvider>
      <LanguageProvider>
        <MemoryRouter>
          <Settings />
        </MemoryRouter>
      </LanguageProvider>
    </UnitProvider>
  );
}

describe("Settings UX V2", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 1024 });
    mockUseAuth.mockReturnValue({
      user: { id: "user-1", email: "runner@example.com", is_email_verified: true },
    });
    mockUseSubscription.mockReturnValue({
      subscription: { status: "trial" },
      isTrial: true,
      isPremium: false,
      isFree: false,
      trialDaysRemaining: 12,
      loading: false,
      statusLabel: "Trial active",
    });
    mockUseGarminSyncProgress.mockReturnValue({ progress: null });
  });

  test("loads settings and shows six supported goal buttons", async () => {
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-current-goal")).toHaveTextContent("Marathon");
    expect(screen.getByTestId("settings-plan-start-date")).toHaveTextContent("Read only");

    ["5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"].forEach((goal) => {
      expect(screen.getByTestId(`training-goal-btn-${goal}`)).toBeInTheDocument();
    });
    [3, 4, 5, 6].forEach((value) => {
      expect(screen.getByTestId(`sessions-per-week-btn-${value}`)).toBeInTheDocument();
    });
  });

  test("maintenance hides race-only fields", async () => {
    mockAxiosApi(createApiState({
      fullCycle: { goal: "MAINTENANCE", sessions_per_week: 5, start_date: "2026-08-27" },
      cycle: {
        goal: { goal_type: "maintenance", race_date: null, target_time_seconds: null },
        cycle: { start_date: "2026-08-27", status: "active", days_to_race: null },
        weeks: [],
      },
      userGoal: null,
    }));

    renderPage();

    expect(await screen.findByTestId("settings-maintenance-note")).toHaveTextContent("Maintenance");
    expect(screen.queryByTestId("settings-race-fields")).not.toBeInTheDocument();
  });

  test("garmin status is shown without exposing a saved password and keeps autofill attributes", async () => {
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-garmin-status")).toHaveTextContent("Connected");
    fireEvent.click(screen.getByTestId("settings-garmin-reconnect-toggle"));

    const emailInput = screen.getByTestId("garmin-email-input");
    const passwordInput = screen.getByTestId("garmin-password-input");

    expect(emailInput).toHaveAttribute("type", "email");
    expect(emailInput).toHaveAttribute("name", "username");
    expect(emailInput).toHaveAttribute("autocomplete", expect.stringContaining("username"));
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toHaveAttribute("name", "password");
    expect(passwordInput).toHaveAttribute("autocomplete", expect.stringContaining("current-password"));
    expect(passwordInput).toHaveValue("");
    expect(screen.getByTestId("settings-no-password-note")).toHaveTextContent("never shows a saved Garmin password");
  });

  test("shows subscription status from existing context", async () => {
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-subscription-status")).toHaveTextContent("TRIAL");
    expect(screen.getByTestId("settings-subscription-trial")).toHaveTextContent("12 days remaining");
    expect(screen.getByTestId("settings-account-email")).toHaveTextContent("runner@example.com");
  });

  test("language renders in EN, FR and ES without raw keys", async () => {
    mockAxiosApi();
    const enView = renderPage({ lang: "en" });

    expect(await screen.findByText("Training Plan")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/settingsV2\.|settings\./);
    enView.unmount();

    mockAxiosApi();
    const frView = renderPage({ lang: "fr" });
    expect(await screen.findByText("Plan d'entraînement")).toBeInTheDocument();
    frView.unmount();

    mockAxiosApi();
    renderPage({ lang: "es" });
    expect(await screen.findByText("Plan de entrenamiento")).toBeInTheDocument();
  });

  test("save race settings shows success feedback only after backend confirmation", async () => {
    mockAxiosApi();
    axios.post.mockImplementation((url) => {
      if (url.includes("/user/goal")) {
        return Promise.resolve({ data: { success: true } });
      }
      return Promise.resolve({ data: {} });
    });

    renderPage();
    await screen.findByTestId("settings-race-fields");

    fireEvent.change(screen.getByTestId("goal-name-input"), { target: { value: "Chicago Marathon" } });
    fireEvent.change(screen.getByTestId("goal-date-input"), { target: { value: "2026-10-20" } });
    fireEvent.change(screen.getByTestId("goal-hours-input"), { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("goal-minutes-input"), { target: { value: "15" } });
    fireEvent.click(screen.getByTestId("save-goal"));

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(
        expect.stringContaining("/user/goal"),
        expect.objectContaining({
          event_name: "Chicago Marathon",
          event_date: "2026-10-20",
          distance_type: "marathon",
          target_time_minutes: 195,
        })
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  test("save race settings shows error feedback on backend failure", async () => {
    mockAxiosApi();
    axios.post.mockImplementation((url) => {
      if (url.includes("/user/goal")) {
        return Promise.reject(new Error("boom"));
      }
      return Promise.resolve({ data: {} });
    });

    renderPage();
    await screen.findByTestId("settings-race-fields");

    fireEvent.change(screen.getByTestId("goal-name-input"), { target: { value: "Valencia Marathon" } });
    fireEvent.change(screen.getByTestId("goal-date-input"), { target: { value: "2026-12-01" } });
    fireEvent.click(screen.getByTestId("save-goal"));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled();
    });
    expect(screen.getByTestId("settings-plan-feedback")).toHaveTextContent("Unable to save race settings");
  });

  test("renders on mobile width 390 without hiding core sections", async () => {
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 390 });
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-page")).toBeInTheDocument();
    expect(screen.getByTestId("settings-plan-section")).toBeInTheDocument();
    expect(screen.getByTestId("settings-garmin-section")).toBeInTheDocument();
    expect(screen.getByTestId("settings-preferences-section")).toBeInTheDocument();
    expect(screen.getByTestId("settings-account-section")).toBeInTheDocument();
  });
});

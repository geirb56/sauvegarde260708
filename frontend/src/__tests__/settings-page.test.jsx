import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
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
  cycle = {
    goal: { goal_type: "marathon", race_date: "2026-10-12", target_time_seconds: 13500 },
    cycle: { start_date: "2026-08-27", status: "active", days_to_race: 46 },
    weeks: [],
  },
  week = {
    goal: { goal_type: "marathon", race_date: "2026-10-12", target_time_seconds: 13500 },
    weekly_target: { session_count: 4, target_basis: "distance", target_km: 52, target_duration_minutes: null, confidence: "high" },
    week: { session_count: 4, planned_km: 52, planned_duration_minutes: null, sessions: [] },
    training_prefs: { sessions_per_week: 4 },
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
  return { cycle, week, userGoal, garminStatus };
}

function mockAxiosApi(state = createApiState(), { postImplementation, patchImplementation } = {}) {
  if (!axios.patch) axios.patch = jest.fn();
  axios.get.mockImplementation((url) => {
    if (url.includes("/training/v2/cycle")) return Promise.resolve({ data: state.cycle });
    if (url.includes("/training/v2/week")) return Promise.resolve({ data: state.week });
    if (url.includes("/user/goal")) return Promise.resolve({ data: state.userGoal });
    if (url.includes("/garmin/status")) return Promise.resolve({ data: state.garminStatus });
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
  axios.post.mockImplementation((url, payload) => {
    if (postImplementation) return postImplementation(url, payload);
    if (url.includes("/training/v2/cycle/start-date")) {
      return Promise.resolve({ data: { status: "updated", cycle: { start_date: "2026-08-20" } } });
    }
    return Promise.resolve({ data: { status: "connected" } });
  });
  axios.patch.mockImplementation((url, payload) => {
    if (patchImplementation) return patchImplementation(url, payload);
    return Promise.resolve({ data: { success: true } });
  });
}

function getUserGoalPostCalls() {
  return axios.post.mock.calls.filter(([url]) => String(url).includes("/user/goal"));
}

function getUserGoalPatchCalls() {
  return axios.patch.mock.calls.filter(([url]) => String(url).includes("/user/goal"));
}

function setSubscription(plan, loading = false) {
  mockUseSubscription.mockReturnValue({
    subscription: { status: plan },
    isTrial: plan === "trial",
    isPremium: plan === "premium",
    isFree: plan === "free",
    trialDaysRemaining: plan === "trial" ? 12 : null,
    loading,
    statusLabel: plan,
    refreshSubscription: jest.fn(() => Promise.resolve()),
  });
}

function RouteLocation() {
  return <span data-testid="settings-test-location">{useLocation().pathname}</span>;
}

function SettingsTestPage() {
  return (
    <UnitProvider>
      <LanguageProvider>
        <MemoryRouter>
          <Settings />
          <RouteLocation />
        </MemoryRouter>
      </LanguageProvider>
    </UnitProvider>
  );
}

function renderPage({ lang = "en", unitSystem = "metric" } = {}) {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  window.localStorage.setItem(UNIT_SYSTEM_KEY, unitSystem);
  return render(<SettingsTestPage />);
}

describe("Settings UX V2", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 1024 });
    if (!axios.delete) axios.delete = jest.fn();
    axios.delete.mockReset();
    axios.delete.mockResolvedValue({ data: {} });
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
      refreshSubscription: jest.fn(() => Promise.resolve()),
    });
    mockUseGarminSyncProgress.mockReturnValue({ progress: null });
  });

  test.each(["free", "trial", "premium"])("waits for subscription loading before resolving %s plan access", async (plan) => {
    setSubscription(plan, true);
    mockAxiosApi();
    const view = renderPage();

    expect(screen.getByTestId("settings-plan-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-plan-locked")).not.toBeInTheDocument();
    expect(screen.queryByTestId("settings-current-goal")).not.toBeInTheDocument();
    await screen.findByTestId("settings-garmin-status");
    expect(axios.get.mock.calls.map(([url]) => String(url))).toEqual([
      expect.stringContaining("/garmin/status"),
    ]);
    fireEvent.click(screen.getByTestId("units-imperial"));
    expect(window.localStorage.getItem(UNIT_SYSTEM_KEY)).toBe("imperial");
    expect(screen.getByTestId("settings-account-section")).toBeInTheDocument();

    setSubscription(plan);
    view.rerender(<SettingsTestPage />);
    if (plan === "free") {
      expect(await screen.findByTestId("settings-plan-locked")).toBeInTheDocument();
      expect(axios.get.mock.calls).toHaveLength(1);
    } else {
      expect(await screen.findByTestId("settings-current-goal")).toHaveTextContent("Marathon");
      ["/training/v2/cycle", "/training/v2/week", "/user/goal"].forEach((endpoint) => {
        expect(axios.get).toHaveBeenCalledWith(expect.stringContaining(endpoint));
      });
    }
  });

  test.each([
    ["en", "Training plan settings are locked", "Training plan settings are available during your trial or with Premium.", "View subscription options"],
    ["fr", "Les réglages du plan d'entraînement sont verrouillés", "Les réglages du plan d'entraînement sont disponibles pendant votre essai ou avec Premium.", "Voir les offres d'abonnement"],
    ["es", "Los ajustes del plan de entrenamiento están bloqueados", "Los ajustes del plan de entrenamiento están disponibles durante la prueba o con Premium.", "Ver opciones de suscripción"],
  ])("FREE shows a translated inline Plan lock in %s without fetching protected settings", async (lang, title, description, cta) => {
    setSubscription("free");
    mockAxiosApi();
    renderPage({ lang });

    const lockedCard = await screen.findByTestId("settings-plan-locked");
    expect(lockedCard).toHaveTextContent(title);
    expect(lockedCard).toHaveTextContent(description);
    expect(screen.getByTestId("settings-plan-upgrade")).toHaveTextContent(cta);
    await screen.findByTestId("settings-garmin-status");
    expect(axios.get.mock.calls.map(([url]) => String(url))).toEqual([
      expect.stringContaining("/garmin/status"),
    ]);
    expect(screen.queryByTestId("settings-plan-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("training-goal-btn-10K")).not.toBeInTheDocument();
    expect(screen.queryByTestId("settings-race-fields")).not.toBeInTheDocument();
    ["preferences", "account", "about"].forEach((section) => {
      expect(screen.getByTestId(`settings-${section}-section`)).toBeInTheDocument();
    });
    expect(document.body.textContent).not.toMatch(/settingsV2\./);
    fireEvent.click(screen.getByTestId("settings-plan-upgrade"));
    expect(screen.getByTestId("settings-test-location")).toHaveTextContent("/subscription");
    expect(axios.post).not.toHaveBeenCalled();
    expect(axios.patch).not.toHaveBeenCalled();
  });

  test("FREE access is determined by context authority, not Premium billing display", async () => {
    setSubscription("free");
    mockUseSubscription.mockReturnValue({
      ...mockUseSubscription(),
      subscription: { status: "premium" },
    });
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-plan-locked")).toBeInTheDocument();
    await screen.findByTestId("settings-garmin-status");
    expect(axios.get.mock.calls).toHaveLength(1);
    expect(screen.queryByTestId("settings-garmin-sync")).not.toBeInTheDocument();
  });

  test.each(["trial", "premium"])("%s preserves plan reads and manual Garmin sync", async (plan) => {
    setSubscription(plan);
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-current-goal")).toHaveTextContent("Marathon");
    expect(screen.queryByTestId("settings-plan-locked")).not.toBeInTheDocument();
    ["/training/v2/cycle", "/training/v2/week", "/user/goal"].forEach((endpoint) => {
      expect(axios.get).toHaveBeenCalledWith(expect.stringContaining(endpoint));
    });
    await screen.findByTestId("settings-garmin-sync");
    fireEvent.click(screen.getByTestId("settings-garmin-sync"));
    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(expect.stringContaining("/garmin/sync"), {});
      expect(screen.getByTestId("settings-garmin-sync")).not.toBeDisabled();
    });
  });

  test("loads settings and shows six supported goal buttons", async () => {
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-current-goal")).toHaveTextContent("Marathon");
    expect(screen.getByTestId("settings-sessions-current")).toHaveTextContent("4 sessions/week");
    expect(screen.getByTestId("settings-sessions-current")).toHaveTextContent("Maximum sessions per week");
    expect(screen.getByTestId("settings-sessions-current")).toHaveTextContent("RunIndex may schedule fewer sessions based on training state and plan safeguards.");
    expect(screen.getByTestId("settings-plan-start-date")).toHaveTextContent("Aug 27, 2026");
    expect(screen.getByTestId("settings-plan-start-date")).toHaveTextContent("Update the canonical Training V2 cycle anchor used by Settings and Training V2.");
    expect(screen.getByTestId("plan-start-date-input")).toHaveValue("2026-08-27");
    expect(document.body).not.toHaveTextContent("Backend contract");
    expect(document.body).not.toHaveTextContent("Backend unchanged");

    ["5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"].forEach((goal) => {
      expect(screen.getByTestId(`training-goal-btn-${goal}`)).toBeInTheDocument();
    });
    [2, 3, 4, 5, 6].forEach((value) => {
      expect(screen.getByTestId(`sessions-per-week-btn-${value}`)).toBeInTheDocument();
    });
  });

  test("shows stored sessions preference even when effective weekly target differs", async () => {
    mockAxiosApi(createApiState({
      week: {
        goal: { goal_type: "marathon", race_date: "2026-10-12", target_time_seconds: 13500 },
        weekly_target: { session_count: 3, target_basis: "distance", target_km: 40, target_duration_minutes: null, confidence: "high" },
        week: { session_count: 3, planned_km: 40, planned_duration_minutes: null, sessions: [] },
        training_prefs: { sessions_per_week: 5 },
      },
    }));

    renderPage();

    expect(await screen.findByTestId("settings-sessions-current")).toHaveTextContent("5 sessions/week");
  });

  test("loads plan settings from v2 endpoints only", async () => {
    mockAxiosApi();
    renderPage();

    await screen.findByTestId("settings-current-goal");

    const calledUrls = axios.get.mock.calls.map(([url]) => String(url));
    expect(calledUrls.some((url) => url.includes("/training/v2/cycle"))).toBe(true);
    expect(calledUrls.some((url) => url.includes("/training/v2/week"))).toBe(true);
    expect(calledUrls.some((url) => url.includes("/training/full-cycle"))).toBe(false);
  });

  test.each(["trial", "premium"])("%s goal update uses canonical set-goal endpoint and never legacy route", async (plan) => {
    setSubscription(plan);
    mockAxiosApi();
    renderPage();

    await screen.findByTestId("settings-current-goal");
    fireEvent.click(screen.getByTestId("training-goal-btn-10K"));

    await waitFor(() => {
      expect(axios.post.mock.calls.some(([url]) => String(url).includes("/training/set-goal?goal=10K"))).toBe(true);
    });
    expect(axios.post.mock.calls.some(([url]) => String(url).includes("/training-plan/set-goal"))).toBe(false);
  });

  test("maintenance hides race-only fields", async () => {
    mockAxiosApi(createApiState({
      cycle: {
        goal: { goal_type: "maintenance", race_date: null, target_time_seconds: null },
        cycle: { start_date: "2026-08-27", status: "active", days_to_race: null },
        weeks: [],
      },
      week: {
        goal: { goal_type: "maintenance", race_date: null, target_time_seconds: null },
        weekly_target: { session_count: 5, target_basis: "distance", target_km: 40, target_duration_minutes: null, confidence: "high" },
        week: { session_count: 5, planned_km: 40, planned_duration_minutes: null, sessions: [] },
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

  test("hides manual Garmin sync action for FREE while keeping reconnect and disconnect", async () => {
    mockUseSubscription.mockReturnValue({
      subscription: { status: "free" },
      isTrial: false,
      isPremium: false,
      isFree: true,
      trialDaysRemaining: null,
      loading: false,
      statusLabel: "Free",
      refreshSubscription: jest.fn(() => Promise.resolve()),
    });
    mockAxiosApi(createApiState({
      garminStatus: {
        connected: true,
        last_sync: "2026-08-26T09:30:00Z",
        activity_count: 18,
        sync_status: { status: "complete", activities_count: 18 },
      },
    }));
    renderPage();

    expect(await screen.findByTestId("settings-garmin-status")).toHaveTextContent("Connected");
    expect(screen.queryByTestId("settings-garmin-sync")).not.toBeInTheDocument();
    expect(screen.getByTestId("settings-garmin-reconnect-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("settings-garmin-disconnect")).toBeInTheDocument();
  });

  test.each([false, true])("FREE Garmin connect/reconnect and disconnect remain usable (connected=%s)", async (connected) => {
    setSubscription("free");
    const state = createApiState({ garminStatus: { connected, activity_count: 0 } });
    mockAxiosApi(state, {
      postImplementation: (url) => {
        if (url.includes("/garmin/connect")) {
          state.garminStatus.connected = true;
          return Promise.resolve({ data: { status: "connected" } });
        }
        if (url.includes("/garmin/disconnect")) {
          state.garminStatus.connected = false;
          return Promise.resolve({ data: {} });
        }
        return Promise.reject(new Error(`Unexpected POST ${url}`));
      },
    });
    renderPage();

    await screen.findByTestId("settings-garmin-status");
    if (connected) fireEvent.click(screen.getByTestId("settings-garmin-reconnect-toggle"));
    fireEvent.change(screen.getByTestId("garmin-email-input"), { target: { value: "runner@example.com" } });
    fireEvent.change(screen.getByTestId("garmin-password-input"), { target: { value: "test-placeholder" } });
    fireEvent.click(screen.getByTestId("garmin-connect"));

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(expect.stringContaining("/garmin/connect"), {
        garmin_username: "runner@example.com",
        garmin_password: "test-placeholder",
      });
      expect(screen.getByTestId("settings-garmin-disconnect")).not.toBeDisabled();
    });
    expect(mockUseSubscription().refreshSubscription).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("settings-garmin-sync")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("settings-garmin-disconnect"));
    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(expect.stringContaining("/garmin/disconnect"), {});
      expect(screen.getByTestId("garmin-password-input")).toHaveValue("");
    });
    fireEvent.click(screen.getByTestId("lang-fr"));
    expect(screen.getByTestId("settings-language-current")).toHaveTextContent("FR");
    expect(axios.get.mock.calls.every(([url]) => String(url).includes("/garmin/status"))).toBe(true);
    expect(axios.patch).not.toHaveBeenCalled();
  });

  test("shows subscription status from existing context", async () => {
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-subscription-status")).toHaveTextContent("TRIAL");
    expect(screen.getByTestId("settings-subscription-trial")).toHaveTextContent("12 days remaining");
    expect(screen.getByTestId("settings-account-email")).toHaveTextContent("runner@example.com");
    expect(screen.getByTestId("settings-account-avatar")).toHaveTextContent("R");
  });

  test("uses a neutral account avatar fallback when user email is unavailable", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "user-1", is_email_verified: false },
    });
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("settings-account-section")).toBeInTheDocument();
    expect(screen.getByTestId("settings-account-avatar")).toHaveTextContent("?");
  });

  test("language renders in EN, FR and ES without raw keys", async () => {
    mockAxiosApi();
    const enView = renderPage({ lang: "en" });

    expect(await screen.findByText("Training Plan")).toBeInTheDocument();
    expect(screen.getByTestId("settings-sessions-current")).toHaveTextContent("Maximum sessions per week");
    expect(screen.getByTestId("settings-sessions-current")).toHaveTextContent("RunIndex may schedule fewer sessions based on training state and plan safeguards.");
    expect(await screen.findByTestId("remove-race-button")).toHaveTextContent("Remove race");
    expect(screen.getByTestId("remove-target-time-button")).toHaveTextContent("Remove target time");
    expect(document.body.textContent).not.toMatch(/settingsV2\.|settings\./);
    expect(document.body).not.toHaveTextContent("Backend contract");
    expect(document.body).not.toHaveTextContent("Backend unchanged");
    expect(screen.getByTestId("settings-plan-start-date")).toHaveTextContent("Update the canonical Training V2 cycle anchor used by Settings and Training V2.");
    enView.unmount();

    mockAxiosApi();
    const frView = renderPage({ lang: "fr" });
    expect(await screen.findByText("Plan d'entraînement")).toBeInTheDocument();
    const sessionsFr = await screen.findByTestId("settings-sessions-current");
    expect(sessionsFr).toHaveTextContent("Nombre maximum de séances par semaine");
    expect(sessionsFr).toHaveTextContent("RunIndex peut en prévoir moins selon l’état d’entraînement et les garde-fous du plan.");
    expect(await screen.findByTestId("remove-race-button")).toHaveTextContent("Supprimer la course");
    expect(screen.getByTestId("remove-target-time-button")).toHaveTextContent("Supprimer le temps cible");
    expect(document.body).not.toHaveTextContent("Contrat backend");
    expect(document.body).not.toHaveTextContent("Backend inchangé");
    expect(screen.getByTestId("settings-plan-start-date")).toHaveTextContent("Modifie l'ancre canonique du cycle Training V2 utilisée par Settings et Training V2.");
    frView.unmount();

    mockAxiosApi();
    renderPage({ lang: "es" });
    expect(await screen.findByText("Plan de entrenamiento")).toBeInTheDocument();
    const sessionsEs = await screen.findByTestId("settings-sessions-current");
    expect(sessionsEs).toHaveTextContent("Número máximo de sesiones por semana");
    expect(sessionsEs).toHaveTextContent("RunIndex puede programar menos según el estado de entrenamiento y los guardarraíles del plan.");
    expect(await screen.findByTestId("remove-race-button")).toHaveTextContent("Eliminar carrera");
    expect(screen.getByTestId("remove-target-time-button")).toHaveTextContent("Eliminar tiempo objetivo");
    expect(document.body).not.toHaveTextContent("Contrato backend");
    expect(document.body).not.toHaveTextContent("Backend sin cambios");
    expect(screen.getByTestId("settings-plan-start-date")).toHaveTextContent("Actualiza el ancla canónica del ciclo Training V2 usada por Ajustes y Training V2.");
  });

  test("event_date without event_name does not claim race details are missing", async () => {
    mockAxiosApi(createApiState({
      userGoal: {
        event_name: "",
        event_date: "2026-10-12",
        distance_type: "marathon",
        distance_km: 42.195,
        target_time_minutes: null,
      },
    }));

    renderPage();

    const raceRow = await screen.findByTestId("settings-race-date-current");
    expect(raceRow).toHaveTextContent("Oct 12, 2026");
    expect(raceRow).toHaveTextContent("Race date saved.");
    expect(raceRow).not.toHaveTextContent("No race details saved yet.");
  });

  test("event_date and target_time without event_name show a truthful neutral helper", async () => {
    mockAxiosApi(createApiState({
      userGoal: {
        event_name: " ",
        event_date: "2026-10-12",
        distance_type: "marathon",
        distance_km: 42.195,
        target_time_minutes: 225,
      },
    }));

    renderPage();

    const raceRow = await screen.findByTestId("settings-race-date-current");
    expect(raceRow).toHaveTextContent("Race date and target time saved.");
    expect(raceRow).not.toHaveTextContent("No race details saved yet.");
    expect(screen.getByTestId("settings-current-target-time")).toHaveTextContent("3h45");
  });

  test("empty race details still allow the missing-details helper", async () => {
    mockAxiosApi(createApiState({
      userGoal: {
        event_name: "",
        event_date: null,
        distance_type: "marathon",
        distance_km: 42.195,
        target_time_minutes: null,
      },
    }));

    renderPage();

    const raceRow = await screen.findByTestId("settings-race-date-current");
    expect(raceRow).toHaveTextContent("No race details saved yet.");
  });

  test("save plan start date uses canonical backend contract and reloads plan settings", async () => {
    mockAxiosApi();
    renderPage();

    await screen.findByTestId("settings-plan-start-date");
    fireEvent.change(screen.getByTestId("plan-start-date-input"), { target: { value: "2026-08-20" } });
    fireEvent.click(screen.getByTestId("save-plan-start-date"));

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(
        expect.stringContaining("/training/v2/cycle/start-date"),
        { start_date: "2026-08-20" }
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  test("save race settings shows success feedback only after backend confirmation", async () => {
    mockAxiosApi(createApiState(), {
      postImplementation: (url) => {
        if (url.includes("/user/goal")) {
          return Promise.resolve({ data: { success: true } });
        }
        return Promise.resolve({ data: {} });
      },
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

  test("saving sessions preference uses max wording and keeps 5-column selector layout", async () => {
    mockAxiosApi();
    renderPage({ lang: "fr" });

    await screen.findByTestId("settings-sessions-current");
    expect(screen.getByTestId("settings-sessions-grid").className).toContain("grid-cols-5");

    fireEvent.click(screen.getByTestId("sessions-per-week-btn-5"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/training/v2/preferences"),
        { sessions_per_week: 5 }
      );
      expect(axios.post.mock.calls.some(([url]) => String(url).includes("/training/refresh"))).toBe(false);
      expect(toast.success).toHaveBeenCalledWith("Maximum de 5 séances/semaine enregistré");
    });
  });

  test("save goal target time without race metadata sends null event fields", async () => {
    mockAxiosApi(createApiState(), {
      postImplementation: (url) => {
        if (url.includes("/user/goal")) {
          return Promise.resolve({ data: { success: true } });
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    await screen.findByTestId("settings-race-fields");

    fireEvent.change(screen.getByTestId("goal-name-input"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("goal-date-input"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("goal-hours-input"), { target: { value: "0" } });
    fireEvent.change(screen.getByTestId("goal-minutes-input"), { target: { value: "50" } });
    fireEvent.click(screen.getByTestId("save-goal"));

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(
        expect.stringContaining("/user/goal"),
        expect.objectContaining({
          event_name: null,
          event_date: null,
          distance_type: "marathon",
          target_time_minutes: 50,
        })
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  test("save race settings shows error feedback on backend failure", async () => {
    mockAxiosApi(createApiState(), {
      postImplementation: (url) => {
        if (url.includes("/user/goal")) {
          return Promise.reject(new Error("boom"));
        }
        return Promise.resolve({ data: {} });
      },
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

  test("shows remove race action only when race metadata is present", async () => {
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("remove-race-button")).toBeInTheDocument();
  });

  test("hides remove race action when race metadata is absent", async () => {
    mockAxiosApi(createApiState({
      userGoal: {
        event_name: null,
        event_date: null,
        distance_type: "marathon",
        distance_km: 42.195,
        target_time_minutes: 225,
      },
    }));
    renderPage();

    await screen.findByTestId("settings-race-fields");
    expect(screen.queryByTestId("remove-race-button")).not.toBeInTheDocument();
  });

  test("shows remove target time action only when target time is present", async () => {
    mockAxiosApi();
    renderPage();

    expect(await screen.findByTestId("remove-target-time-button")).toBeInTheDocument();
  });

  test("hides remove target time action when target time is absent", async () => {
    mockAxiosApi(createApiState({
      userGoal: {
        event_name: "Berlin Marathon",
        event_date: "2026-10-12",
        distance_type: "marathon",
        distance_km: 42.195,
        target_time_minutes: null,
      },
    }));
    renderPage();

    await screen.findByTestId("settings-race-fields");
    expect(screen.queryByTestId("remove-target-time-button")).not.toBeInTheDocument();
  });

  test("cancel remove race closes confirmation without calling a mutation", async () => {
    mockAxiosApi();
    renderPage();

    fireEvent.click(await screen.findByTestId("remove-race-button"));
    const dialog = await screen.findByTestId("remove-race-dialog");
    fireEvent.click(within(dialog).getByTestId("cancel-remove-race"));

    await waitFor(() => {
      expect(screen.queryByTestId("remove-race-dialog")).not.toBeInTheDocument();
    });
    expect(getUserGoalPatchCalls()).toHaveLength(0);
    expect(axios.delete).not.toHaveBeenCalled();
  });

  test("cancel remove target time closes confirmation without calling a mutation", async () => {
    mockAxiosApi();
    renderPage();

    fireEvent.click(await screen.findByTestId("remove-target-time-button"));
    const dialog = await screen.findByTestId("remove-target-time-dialog");
    fireEvent.click(within(dialog).getByTestId("cancel-remove-target-time"));

    await waitFor(() => {
      expect(screen.queryByTestId("remove-target-time-dialog")).not.toBeInTheDocument();
    });
    expect(getUserGoalPatchCalls()).toHaveLength(0);
    expect(axios.delete).not.toHaveBeenCalled();
  });

  test("confirm remove race sends minimal PATCH payload", async () => {
    const state = createApiState();
    mockAxiosApi(state, {
      patchImplementation: (url, payload) => {
        if (url.includes("/user/goal")) {
          state.userGoal = { ...state.userGoal, ...payload };
          return Promise.resolve({ data: { success: true } });
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("remove-race-button"));
    fireEvent.click(within(await screen.findByTestId("remove-race-dialog")).getByTestId("confirm-remove-race"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/user/goal"),
        { event_name: null, event_date: null }
      );
    });
    expect(getUserGoalPatchCalls()).toHaveLength(1);
    expect(getUserGoalPostCalls()).toHaveLength(0);
    expect(axios.delete).not.toHaveBeenCalled();
  });

  test("confirm remove target time sends minimal PATCH payload and reloads optional state", async () => {
    const state = createApiState();
    mockAxiosApi(state, {
      patchImplementation: (url, payload) => {
        if (url.includes("/user/goal")) {
          state.userGoal = { ...state.userGoal, ...payload, target_pace: null };
          return Promise.resolve({ data: { success: true } });
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("remove-target-time-button"));
    fireEvent.click(within(await screen.findByTestId("remove-target-time-dialog")).getByTestId("confirm-remove-target-time"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/user/goal"),
        { target_time_minutes: null }
      );
    });
    expect(getUserGoalPatchCalls()).toHaveLength(1);
    expect(getUserGoalPostCalls()).toHaveLength(0);
    expect(axios.delete).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByTestId("settings-current-target-time")).toHaveTextContent("Current target time: Optional");
    });
  });

  test("remove target time uses PATCH even when the stored race date is in the past", async () => {
    const state = createApiState({
      userGoal: {
        event_name: "Auray-Vannes",
        event_date: "2026-09-01",
        distance_type: "semi",
        distance_km: 21.0975,
        target_time_minutes: 115,
      },
    });
    mockAxiosApi(state, {
      patchImplementation: (url, payload) => {
        if (url.includes("/user/goal")) {
          state.userGoal = { ...state.userGoal, ...payload, target_pace: null };
          return Promise.resolve({ data: { success: true } });
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("remove-target-time-button"));
    fireEvent.click(within(await screen.findByTestId("remove-target-time-dialog")).getByTestId("confirm-remove-target-time"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/user/goal"),
        { target_time_minutes: null }
      );
    });
  });

  test("remove race keeps working for ULTRA without sending distance fields from the client", async () => {
    const state = createApiState({
      cycle: {
        goal: { goal_type: "ultra", race_date: "2026-09-13", target_time_seconds: 36000 },
        cycle: { start_date: "2026-08-27", status: "active", days_to_race: 17 },
        weeks: [],
      },
      week: {
        goal: { goal_type: "ultra", race_date: "2026-09-13", target_time_seconds: 36000 },
        weekly_target: { session_count: 4, target_basis: "distance", target_km: 90, target_duration_minutes: null, confidence: "high" },
        week: { session_count: 4, planned_km: 90, planned_duration_minutes: null, sessions: [] },
      },
      userGoal: {
        event_name: "Auray-Vannes",
        event_date: "2026-09-13",
        distance_type: "ultra",
        distance_km: 80,
        target_time_minutes: 600,
      },
    });
    mockAxiosApi(state, {
      patchImplementation: (url, payload) => {
        if (url.includes("/user/goal")) {
          state.userGoal = { ...state.userGoal, ...payload };
          return Promise.resolve({ data: { success: true } });
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("remove-race-button"));
    fireEvent.click(within(await screen.findByTestId("remove-race-dialog")).getByTestId("confirm-remove-race"));

    await waitFor(() => {
      expect(axios.patch).toHaveBeenCalledWith(
        expect.stringContaining("/user/goal"),
        { event_name: null, event_date: null }
      );
    });
    expect(getUserGoalPatchCalls()[0][1]).not.toHaveProperty("distance_km");
    expect(getUserGoalPatchCalls()[0][1]).not.toHaveProperty("distance_type");
  });

  test("remove race shows recoverable error state and keeps existing race data", async () => {
    mockAxiosApi(createApiState(), {
      patchImplementation: (url) => {
        if (url.includes("/user/goal")) {
          return Promise.reject(new Error("boom"));
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("remove-race-button"));
    fireEvent.click(within(await screen.findByTestId("remove-race-dialog")).getByTestId("confirm-remove-race"));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Unable to remove this race.");
    });
    expect(screen.getByTestId("settings-race-date-current")).toHaveTextContent("Berlin Marathon");
    expect(screen.getByTestId("settings-plan-feedback")).toHaveTextContent("Unable to remove this race.");
  });

  test("remove target time shows recoverable error state and keeps the target time", async () => {
    mockAxiosApi(createApiState(), {
      patchImplementation: (url) => {
        if (url.includes("/user/goal")) {
          return Promise.reject(new Error("boom"));
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("remove-target-time-button"));
    fireEvent.click(within(await screen.findByTestId("remove-target-time-dialog")).getByTestId("confirm-remove-target-time"));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Unable to remove the target time.");
    });
    expect(screen.getByTestId("settings-current-target-time")).toHaveTextContent("3h45");
    expect(screen.getByTestId("settings-plan-feedback")).toHaveTextContent("Unable to remove the target time.");
  });

  test("remove race prevents double-submit while saving", async () => {
    let resolveMutation;
    const state = createApiState();
    const mutationPromise = new Promise((resolve) => {
      resolveMutation = resolve;
    });
    mockAxiosApi(state, {
      patchImplementation: (url, payload) => {
        if (url.includes("/user/goal")) {
          return mutationPromise.then(() => {
            state.userGoal = { ...state.userGoal, ...payload };
            return { data: { success: true } };
          });
        }
        return Promise.resolve({ data: {} });
      },
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("remove-race-button"));
    const confirmButton = within(await screen.findByTestId("remove-race-dialog")).getByTestId("confirm-remove-race");

    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(getUserGoalPatchCalls()).toHaveLength(1);
    });

    resolveMutation({ data: { success: true } });
    await waitFor(() => {
      expect(screen.queryByTestId("remove-race-dialog")).not.toBeInTheDocument();
    });
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

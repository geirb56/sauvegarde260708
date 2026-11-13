import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App from "@/App";

// Mocked-router tests: they validate routing logic, not a production E2E flow.
const mockAuth = { user: null, loading: false };

jest.mock("@/context/AuthContext", () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => mockAuth,
}));
jest.mock("@/context/LanguageContext", () => ({ LanguageProvider: ({ children }) => children }));
jest.mock("@/context/SubscriptionContext", () => ({ SubscriptionProvider: ({ children }) => children }));
jest.mock("@/context/UnitContext", () => ({ UnitProvider: ({ children }) => children }));
jest.mock("@/components/Layout", () => {
  const { Outlet } = require("react-router-dom");
  return function MockLayout() {
    return <Outlet />;
  };
});
jest.mock("@/components/ui/sonner", () => ({ Toaster: () => null }));
jest.mock("@/components/IOSPWAHint", () => () => null);

jest.mock("@/pages/Dashboard", () => () => <div>dashboard-page</div>);
jest.mock("@/pages/Subscription", () => () => <div>subscription-page</div>);
jest.mock("@/pages/TrainingPlanV2", () => () => <div>training-page</div>);
jest.mock("@/pages/Coach", () => () => <div>coach-page</div>);
jest.mock("@/pages/Login", () => () => <div>login-page</div>);
jest.mock("@/pages/Register", () => () => <div>register-page</div>);
jest.mock("axios");

function go(path) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

describe("C424 public landing routing", () => {
  beforeEach(() => {
    mockAuth.user = null;
    mockAuth.loading = false;
  });

  test("anonymous visitor on / sees the Landing, not the Dashboard", () => {
    go("/");
    expect(screen.getByTestId("landing-page")).toBeInTheDocument();
    expect(screen.queryByText("dashboard-page")).not.toBeInTheDocument();
  });

  test("authenticated user on / gets the Dashboard", () => {
    mockAuth.user = { id: "u1", is_admin: false };
    go("/");
    expect(screen.getByText("dashboard-page")).toBeInTheDocument();
    expect(screen.queryByTestId("landing-page")).not.toBeInTheDocument();
  });

  test("Landing is not flashed while the session is loading", () => {
    mockAuth.loading = true;
    go("/");
    expect(screen.queryByTestId("landing-page")).not.toBeInTheDocument();
    expect(screen.queryByText("dashboard-page")).not.toBeInTheDocument();
  });

  test("trial CTA navigates to /register", async () => {
    go("/");
    fireEvent.click(screen.getByTestId("landing-hero-trial"));
    await waitFor(() => expect(screen.getByText("register-page")).toBeInTheDocument());
    expect(window.location.pathname).toBe("/register");
  });

  test("login CTA navigates to /login", async () => {
    go("/");
    fireEvent.click(screen.getByTestId("landing-hero-login"));
    await waitFor(() => expect(screen.getByText("login-page")).toBeInTheDocument());
    expect(window.location.pathname).toBe("/login");
  });

  test.each(["/subscription", "/training", "/coach"])("anonymous %s redirects to /login", async (path) => {
    go(path);
    await waitFor(() => expect(screen.getByText("login-page")).toBeInTheDocument());
    expect(window.location.pathname).toBe("/login");
  });

  test.each([
    ["/subscription", "subscription-page"],
    ["/training", "training-page"],
    ["/coach", "coach-page"],
  ])("authenticated %s renders its page", (path, text) => {
    mockAuth.user = { id: "u1", is_admin: false };
    go(path);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  test("authenticated user keeps the session on /login and /register routes", () => {
    mockAuth.user = { id: "u1", is_admin: false };
    window.localStorage.setItem("access_token", "tok");
    go("/login");
    expect(screen.getByText("login-page")).toBeInTheDocument();
    expect(window.localStorage.getItem("access_token")).toBe("tok");
    window.localStorage.clear();
  });

  test.each([360, 390])("Landing first screen exposes both CTAs at %i px", (width) => {
    window.innerWidth = width;
    window.dispatchEvent(new Event("resize"));
    go("/");
    const hero = document.getElementById("hero");
    // Both CTAs live in the hero, before any other section, and are full-width on mobile.
    const trial = within(hero).getByTestId("landing-hero-trial");
    const login = within(hero).getByTestId("landing-hero-login");
    expect(trial).toHaveAttribute("href", "/register");
    expect(login).toHaveAttribute("href", "/login");
    expect(trial.className).toMatch(/\bw-full\b/);
    expect(login.className).toMatch(/\bw-full\b/);
    expect(trial.textContent).toBe("Essayer gratuitement");
    expect(login.textContent).toBe("Se connecter");
  });
});

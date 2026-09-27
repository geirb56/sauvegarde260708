import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import App from "@/App";

jest.mock("@/context/AuthContext", () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => ({ user: { id: "u1", is_admin: false }, loading: false }),
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
jest.mock("@/pages/WorkoutDetail", () => () => <div>workout-detail-page</div>);
jest.mock("@/pages/DetailedAnalysis", () => () => <div>detailed-analysis-page</div>);
jest.mock("@/pages/Sessions", () => () => <div>sessions-page</div>);
jest.mock("@/pages/SessionDetail", () => () => <div>session-detail-page</div>);
jest.mock("@/pages/Progress", () => () => <div>progress-page</div>);
jest.mock("@/pages/Settings", () => () => <div>settings-page</div>);
jest.mock("@/pages/Subscription", () => () => <div>subscription-page</div>);
jest.mock("@/pages/TrainingPlanV2", () => () => <div>training-page</div>);
jest.mock("@/pages/Coach", () => () => <div>coach-page</div>);
jest.mock("@/pages/Onboarding", () => () => <div>onboarding-page</div>);
jest.mock("@/pages/Login", () => () => <div>login-page</div>);
jest.mock("@/pages/Register", () => () => <div>register-page</div>);
jest.mock("@/pages/ForgotPassword", () => () => <div>forgot-password-page</div>);
jest.mock("@/pages/ResetPassword", () => () => <div>reset-password-page</div>);
jest.mock("@/pages/Admin", () => () => <div>admin-page</div>);

describe("Legacy redirects remain active", () => {
  it("/guidance redirects to /coach", async () => {
    window.history.pushState({}, "Guidance", "/guidance");
    render(<App />);
    await waitFor(() => expect(screen.getByText("coach-page")).toBeTruthy());
  });

  it("/digest redirects to /progress", async () => {
    window.history.pushState({}, "Digest", "/digest");
    render(<App />);
    await waitFor(() => expect(screen.getByText("progress-page")).toBeTruthy());
  });
});

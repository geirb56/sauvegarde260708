import React from "react";
import "@testing-library/jest-dom";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Layout from "@/components/Layout";
import { LanguageProvider } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

describe("Layout mobile nav", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useAuth.mockReturnValue({
      user: { email: "runner@example.com", is_admin: true },
      logout: jest.fn(),
    });
  });

  test("keeps admin out of the primary mobile nav and exposes it in the header", () => {
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Layout />
        </MemoryRouter>
      </LanguageProvider>
    );

    const mobileNav = screen.getByTestId("mobile-nav");
    expect(within(mobileNav).queryByText("Admin")).not.toBeInTheDocument();
    expect(screen.getByTestId("header-admin-link")).toBeInTheDocument();
    expect(screen.getByTestId("header-settings-link")).toBeInTheDocument();
    expect(screen.getByTestId("mobile-nav-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("mobile-nav-training")).toBeInTheDocument();
    expect(screen.getByTestId("mobile-nav-sessions")).toBeInTheDocument();
    expect(screen.getByTestId("mobile-nav-coach")).toBeInTheDocument();
    expect(screen.getByTestId("mobile-nav-progress")).toBeInTheDocument();
  });

  test("renders the intended full english labels in the mobile nav", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Layout />
        </MemoryRouter>
      </LanguageProvider>
    );

    const mobileNav = screen.getByTestId("mobile-nav");
    expect(within(mobileNav).getByText("Home")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Training")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Sessions")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Coach")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Progress")).toBeInTheDocument();
  });

  test("renders the intended full french labels in the mobile nav", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Layout />
        </MemoryRouter>
      </LanguageProvider>
    );

    const mobileNav = screen.getByTestId("mobile-nav");
    expect(within(mobileNav).getByText("Accueil")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Entraînement")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Séances")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Coach")).toBeInTheDocument();
    expect(within(mobileNav).getByText("Progression")).toBeInTheDocument();
  });
});

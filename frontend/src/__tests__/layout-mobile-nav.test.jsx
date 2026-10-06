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
    expect(screen.queryByTestId("header-user-avatar")).not.toBeInTheDocument();
  });

  test.each([
    ["fr", ["Accueil", "Plan", "Séances", "Coach", "Progrès"], "Entraînement", "Progression"],
    ["en", ["Home", "Plan", "Sessions", "Coach", "Progress"], "Training", "Progress"],
    ["es", ["Inicio", "Plan", "Sesiones", "Coach", "Progreso"], "Entrenamiento", "Progreso"],
  ])("renders short single-line mobile labels with full accessible names in %s", (language, labels, training, progress) => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Layout />
        </MemoryRouter>
      </LanguageProvider>
    );

    const mobileNav = screen.getByTestId("mobile-nav");
    expect(within(mobileNav).getAllByRole("link")).toHaveLength(5);
    expect(mobileNav.firstChild).toHaveClass("grid-cols-5");
    labels.forEach((label) => {
      const element = within(mobileNav).getByText(label);
      expect(element).toHaveClass("text-[11px]", "whitespace-nowrap");
      expect(element).not.toHaveClass("break-words");
      expect(element).not.toHaveClass("whitespace-normal");
      expect(element).not.toHaveClass("truncate");
    });
    expect(within(mobileNav).getByRole("link", { name: training })).toHaveAttribute("title", training);
    expect(within(mobileNav).getByRole("link", { name: progress })).toHaveAttribute("title", progress);
    expect(screen.getByTestId("mobile-nav-training")).toHaveAttribute("href", "/training");
    expect(screen.getByTestId("mobile-nav-progress")).toHaveAttribute("href", "/progress");
  });

  test("removes the non-interactive header avatar even when identity is unavailable", () => {
    useAuth.mockReturnValue({
      user: { is_admin: false },
      logout: jest.fn(),
    });

    render(
      <LanguageProvider>
        <MemoryRouter>
          <Layout />
        </MemoryRouter>
      </LanguageProvider>
    );

    expect(screen.queryByTestId("header-user-avatar")).not.toBeInTheDocument();
    expect(screen.getByTestId("header-settings-link")).toBeInTheDocument();
  });
});

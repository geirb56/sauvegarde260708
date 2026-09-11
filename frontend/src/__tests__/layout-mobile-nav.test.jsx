import React from "react";
import "@testing-library/jest-dom";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Layout from "@/components/Layout";
import { LanguageProvider } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

describe("Layout mobile nav", () => {
  beforeEach(() => {
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
});

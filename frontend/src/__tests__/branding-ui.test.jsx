import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import { LanguageProvider } from "@/context/LanguageContext";

jest.mock("axios");

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => {
  const actual = jest.requireActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({
    refreshSubscription: jest.fn(() => Promise.resolve()),
  }),
}));

jest.mock("@/hooks/useGarminSyncProgress", () => ({
  useGarminSyncProgress: jest.fn(),
}));

import { useGarminSyncProgress } from "@/hooks/useGarminSyncProgress";
import Onboarding from "@/pages/Onboarding";
import { BrandSplash } from "@/components/LoadingSpinner";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function renderWithProviders(ui) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter>
          {ui}
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

describe("branding asset wiring", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    axios.get.mockResolvedValue({ data: {} });
    axios.post.mockResolvedValue({ data: {} });
    useGarminSyncProgress.mockReturnValue({ progress: null, isStreaming: false, error: null });
    window.localStorage.clear();
  });

  test("BrandSplash keeps the canonical public logo path", () => {
    const { container, unmount } = renderWithProviders(<BrandSplash text="Loading" />);

    const logo = container.querySelector('[data-testid="brand-splash"] img[alt="RunIndex"]');
    expect(logo).toBeTruthy();
    expect(logo.getAttribute("src")).toBe("/runindex-logo.png");
    expect(logo.className).toContain("brand-splash-logo");
    expect(container.textContent).toContain("Loading");

    unmount();
  });

  test("onboarding welcome keeps the canonical public logo path", () => {
    const { container, unmount } = renderWithProviders(<Onboarding />);

    const logo = container.querySelector('[data-testid="onboarding-logo"]');
    expect(logo).toBeTruthy();
    expect(logo.getAttribute("src")).toBe("/runindex-logo.png");
    expect(logo.getAttribute("alt")).toBe("RunIndex");

    unmount();
  });
});

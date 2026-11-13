import React from "react";
import "@testing-library/jest-dom";
import fs from "fs";
import path from "path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Landing from "@/pages/Landing";
import Subscription from "@/pages/Subscription";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

const mockInitializePaddle = jest.fn();
jest.mock("@paddle/paddle-js", () => ({
  initializePaddle: (...args) => mockInitializePaddle(...args),
}), { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
// No AuthProvider/SubscriptionProvider is mounted around Landing: it must not need them.
jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-1", email: "runner@example.com" } }),
}));
jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({ refreshSubscription: jest.fn(() => Promise.resolve()) }),
}));

const ROOT = path.resolve(__dirname, "../..");

describe("C424 Landing is a navigation-only page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
  });

  test("renders commercial content without any API, Garmin or Paddle call", () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    );
    expect(screen.getByText("Pourquoi RunIndex ?")).toBeInTheDocument();
    expect(screen.getByText("Comment ça marche ?")).toBeInTheDocument();
    expect(screen.getByText("Questions fréquentes")).toBeInTheDocument();
    expect(screen.getByText("4,99 €")).toBeInTheDocument();
    expect(screen.getByTestId("subscription-trial-info")).toHaveTextContent(/30 jours.*éligible/i);

    for (const method of ["get", "post", "put", "patch", "delete", "request"]) {
      expect(axios[method]).not.toHaveBeenCalled();
    }
    expect(mockInitializePaddle).not.toHaveBeenCalled();
    expect(screen.queryByTestId("garmin-email-input")).not.toBeInTheDocument();
    expect(screen.queryByTestId("premium-subscribe-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("start-free-trial-btn")).not.toBeInTheDocument();
  });

  test("every plan/final CTA is a plain link to /register or /login", () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    );
    const page = screen.getByTestId("landing-page");
    const links = within(page).getAllByRole("link");
    links.forEach((link) => expect(["/register", "/login"]).toContain(link.getAttribute("href")));
    expect(within(page).queryAllByRole("button", { name: /activer premium|démarrer mon essai/i })).toHaveLength(0);
  });
});

describe("C424 Subscription page keeps its authenticated behaviour", () => {
  function renderSubscription() {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    return render(
      <LanguageProvider>
        <MemoryRouter>
          <Subscription />
        </MemoryRouter>
      </LanguageProvider>
    );
  }

  function mockApi(status) {
    axios.get.mockImplementation((url) => {
      if (url.includes("/subscription/info")) return Promise.resolve({ data: { status } });
      if (url.includes("/garmin/status")) return Promise.resolve({ data: { connected: false } });
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  }

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("keeps the commercial sections and Garmin trial activation for FREE users", async () => {
    mockApi("free");
    renderSubscription();
    expect(await screen.findByText("Tarifs")).toBeInTheDocument();
    expect(screen.getByText("4,99 €")).toBeInTheDocument();
    expect(screen.getByText("Questions fréquentes")).toBeInTheDocument();
    expect(screen.getByText("Comment ça marche ?")).toBeInTheDocument();

    fireEvent.click(await screen.findByTestId("start-free-trial-btn"));
    expect(await screen.findByTestId("trial-garmin-connect-form")).toBeInTheDocument();
  });

  test("shows the real TRIAL status", async () => {
    mockApi("trial");
    renderSubscription();
    expect(await screen.findByTestId("trial-status-pill")).toBeInTheDocument();
    expect(screen.getByTestId("trial-active-banner")).toBeInTheDocument();
  });

  test("Premium checkout posts to the authenticated endpoint and opens Paddle", async () => {
    mockApi("free");
    const open = jest.fn();
    mockInitializePaddle.mockResolvedValue({ Checkout: { open } });
    axios.post.mockResolvedValue({
      data: { transaction_id: "txn_1", paddle_environment: "sandbox", paddle_client_token: "tok" },
    });
    renderSubscription();

    fireEvent.click(await screen.findByTestId("premium-subscribe-btn"));
    await waitFor(() => expect(open).toHaveBeenCalled());
    expect(axios.post).toHaveBeenCalledWith(expect.stringContaining("/subscription/paddle/checkout"), {});
    expect(mockInitializePaddle).toHaveBeenCalledWith({ environment: "sandbox", token: "tok" });
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ transactionId: "txn_1" }));
  });

  test("a subscription status error is surfaced with a retry", async () => {
    axios.get.mockRejectedValue(new Error("boom"));
    renderSubscription();
    expect(await screen.findByTestId("subscription-status-error")).toBeInTheDocument();
    expect(screen.getByTestId("subscription-status-retry-btn")).toBeInTheDocument();
  });
});

describe("C424 static deployment configuration", () => {
  test("Netlify rewrites every path to index.html so /login and /register survive a reload", () => {
    const toml = fs.readFileSync(path.resolve(ROOT, "../netlify.toml"), "utf8");
    expect(toml).toMatch(/from\s*=\s*"\/\*"/);
    expect(toml).toMatch(/to\s*=\s*"\/index\.html"/);
    expect(toml).toMatch(/status\s*=\s*200/);
  });

  test("index.html has no stale Strava/RAG marketing and keeps PWA metadata", () => {
    const html = fs.readFileSync(path.resolve(ROOT, "public/index.html"), "utf8");
    expect(html).not.toMatch(/strava|\bRAG\b/i);
    expect(html).toMatch(/connectée à Garmin/);
    expect(html).toMatch(/rel="manifest"/);
    expect(html).toMatch(/name="theme-color"/);
    const manifest = fs.readFileSync(path.resolve(ROOT, "public/manifest.json"), "utf8");
    expect(manifest).not.toMatch(/strava|\bRAG\b/i);
  });
});

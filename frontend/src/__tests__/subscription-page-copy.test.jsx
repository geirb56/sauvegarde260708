import React from "react";
import "@testing-library/jest-dom";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Subscription from "@/pages/Subscription";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";

jest.mock("axios");

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "runner@example.com" },
  }),
}));

jest.mock("@/context/SubscriptionContext", () => ({
  useSubscription: () => ({
    refreshSubscription: jest.fn(() => Promise.resolve()),
  }),
}));

function renderPage() {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
  return render(
    <LanguageProvider>
      <MemoryRouter>
        <Subscription />
      </MemoryRouter>
    </LanguageProvider>
  );
}

describe("Subscription page product-truth copy", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    axios.get.mockImplementation((url) => {
      if (url.includes("/subscription/info")) {
        return Promise.resolve({ data: { status: "free" } });
      }
      if (url.includes("/garmin/status")) {
        return Promise.resolve({ data: { connected: false } });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  });

  test("shows accurate trial messaging and clearly labels examples", async () => {
    renderPage();

    expect(await screen.findByText("Tarifs")).toBeInTheDocument();
    const trialInfo = screen.getByTestId("subscription-trial-info");
    expect(within(trialInfo).getByText(/trial/i)).toBeInTheDocument();
    expect(trialInfo).toHaveTextContent(/30 jours/i);
    expect(trialInfo).toHaveTextContent(/premium/i);
    expect(trialInfo).toHaveTextContent(/garmin/i);
    expect(trialInfo).toHaveTextContent(/éligible/i);
    expect(trialInfo).toHaveTextContent(/un seul essai/i);
    expect(trialInfo).toHaveTextContent(/compte garmin/i);
    expect(screen.getByText(/exemples illustratifs/i)).toBeInTheDocument();
    expect(screen.getByText(/exemples de questions/i)).toBeInTheDocument();
    expect(screen.getAllByText(/garmin éligible/i).length).toBeGreaterThan(0);
  });

  test("removes misleading free and marketing promises", async () => {
    renderPage();

    expect(await screen.findByText("FREE")).toBeInTheDocument();
    expect(screen.queryByText("Analyse automatique des séances")).not.toBeInTheDocument();
    expect(screen.queryByText("Revue hebdomadaire")).not.toBeInTheDocument();
    expect(screen.queryByText("Coach IA prioritaire")).not.toBeInTheDocument();
    expect(screen.queryByText("Aucun paiement pendant les 30 premiers jours.")).not.toBeInTheDocument();
    expect(screen.queryByText(/Rejoignez les coureurs qui utilisent déjà RunIndex/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/L'accès Trial est décidé par le backend/i)).not.toBeInTheDocument();
  });
});

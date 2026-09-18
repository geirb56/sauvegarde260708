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
    expect(within(trialInfo).getByText("TRIAL")).toBeInTheDocument();
    expect(within(trialInfo).getByText(/30 jours d'accès Premium complet après une connexion Garmin éligible/i)).toBeInTheDocument();
    expect(within(trialInfo).getByText(/Un seul essai est disponible par compte Garmin/i)).toBeInTheDocument();
    expect(screen.getByText("Exemples illustratifs")).toBeInTheDocument();
    expect(screen.getByText("Exemples de questions")).toBeInTheDocument();
    expect(screen.getByText("Essai Premium 30 jours si Garmin éligible")).toBeInTheDocument();
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

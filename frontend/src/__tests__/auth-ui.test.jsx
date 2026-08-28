import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import Layout from "@/components/Layout";
import { LanguageProvider } from "@/context/LanguageContext";
import { LANGUAGE_STORAGE_KEY } from "@/lib/i18n";
import { useAuth } from "@/context/AuthContext";

jest.mock("axios", () => ({
  get: jest.fn(() => Promise.resolve({ data: {} })),
  post: jest.fn(() => Promise.resolve({ data: {} })),
  delete: jest.fn(() => Promise.resolve({ data: {} })),
}));

jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
  },
}));

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/components/ChatCoach", () => () => null);

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function makeAuthOverrides(overrides = {}) {
  return {
    user: { id: "user-1", email: "user@example.com" },
    loading: false,
    login: jest.fn().mockResolvedValue({ ok: true }),
    register: jest.fn().mockResolvedValue({ ok: true }),
    logout: jest.fn(),
    loginWithToken: jest.fn(),
    refreshUser: jest.fn(),
    ...overrides,
  };
}

function renderWithProviders(ui, { route = "/" } = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <LanguageProvider>
        <MemoryRouter initialEntries={[route]}>
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

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

function setFieldValue(element, value) {
  const descriptor = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value"
  );
  descriptor.set.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("auth pages and oauth UI", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
    useAuth.mockReturnValue(makeAuthOverrides());
  });

  test("login renders translated oauth/auth UI and persists language across remount", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "es");
    const first = renderWithProviders(<Login />);

    expect(first.container.textContent).toContain("Inicia sesión en tu cuenta");
    expect(first.container.textContent).toContain("Continuar con Google");
    expect(first.container.textContent).toContain("Continuar con Apple");
    expect(first.container.querySelector(".min-h-screen")).not.toBeNull();
    expect(first.container.querySelector(".max-w-sm")).not.toBeNull();

    first.unmount();

    const second = renderWithProviders(<Login />);
    expect(second.container.textContent).toContain("Inicia sesión en tu cuenta");
    second.unmount();
  });

  test("login shows translated loading and auth error states", async () => {
    let resolveLogin;
    const login = jest.fn(
      () =>
        new Promise((resolve) => {
          resolveLogin = resolve;
        })
    );
    useAuth.mockReturnValue(makeAuthOverrides({ login }));
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");

    const { container, unmount } = renderWithProviders(<Login />);
    setFieldValue(container.querySelector("#email"), "user@example.com");
    setFieldValue(container.querySelector("#password"), "Password1!");

    await act(async () => {
      container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("Connexion…");

    resolveLogin({ ok: false, errorDetail: "Invalid email or password." });
    await flush();

    expect(container.textContent).toContain("E-mail ou mot de passe invalide.");
    unmount();
  });

  test("register shows translated client-side validation and responsive layout", async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "es");
    const { container, unmount } = renderWithProviders(<Register />);

    setFieldValue(container.querySelector("#email"), "user@example.com");
    setFieldValue(container.querySelector("#password"), "Password1!");
    setFieldValue(container.querySelector("#confirmPassword"), "Mismatch1!");

    await act(async () => {
      container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("Las contraseñas no coinciden.");
    expect(container.querySelector(".max-w-sm")).not.toBeNull();
    unmount();
  });

  test("oauth buttons show translated configuration errors when credentials are absent", async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "es");
    const { container, unmount } = renderWithProviders(<Login />);
    const buttons = Array.from(container.querySelectorAll("button"));

    await act(async () => {
      buttons.find((button) => button.textContent.includes("Google")).click();
    });
    expect(container.textContent).toContain("El inicio de sesión con Google no está configurado.");

    await act(async () => {
      buttons.find((button) => button.textContent.includes("Apple")).click();
    });
    expect(container.textContent).toContain("El inicio de sesión con Apple no está configurado.");
    unmount();
  });

  test("forgot/reset password pages render translated states", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");

    const forgot = renderWithProviders(<ForgotPassword />);
    expect(forgot.container.textContent).toContain("Réinitialisez votre mot de passe");
    expect(forgot.container.textContent).toContain("Envoyer le lien de réinitialisation");
    forgot.unmount();

    const resetInvalid = renderWithProviders(<ResetPassword />, { route: "/reset-password" });
    expect(resetInvalid.container.textContent).toContain("Lien de réinitialisation invalide.");
    resetInvalid.unmount();

    const resetValid = renderWithProviders(<ResetPassword />, { route: "/reset-password?token=test-token" });
    expect(resetValid.container.textContent).toContain("Choisissez un nouveau mot de passe");
    expect(resetValid.container.textContent).toContain("Réinitialiser le mot de passe");
    resetValid.unmount();
  });

  test("layout exposes translated logout control and calls logout", async () => {
    const logout = jest.fn();
    useAuth.mockReturnValue(makeAuthOverrides({ logout }));
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "es");

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <LanguageProvider>
          <MemoryRouter initialEntries={["/"]}>
            <Routes>
              <Route path="/" element={<Layout />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      );
    });

    const logoutButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.getAttribute("title") === "Cerrar sesión"
    );
    expect(logoutButton).toBeTruthy();

    await act(async () => {
      logoutButton.click();
    });
    expect(logout).toHaveBeenCalled();

    act(() => root.unmount());
    container.remove();
  });
});

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import Register from "@/pages/Register";
import Login from "@/pages/Login";

const mockNavigate = jest.fn();
const mockRegister = jest.fn();
const mockLogin = jest.fn();

jest.mock("react-router-dom", () => {
  const actual = jest.requireActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

jest.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    register: mockRegister,
    login: mockLogin,
  }),
}));

jest.mock("@/context/LanguageContext", () => ({
  useLanguage: () => ({
    t: (key) => key,
  }),
}));

jest.mock("@/components/OAuthButtons", () => () => <div data-testid="oauth-buttons" />);
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function renderUI(node) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(<MemoryRouter>{node}</MemoryRouter>);
  });

  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

function setFieldValue(element, value) {
  expect(element).toBeTruthy();
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  act(() => {
    descriptor.set.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function submit(container, selector = "form") {
  const form = container.querySelector(selector);
  expect(form).toBeTruthy();
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
}

describe("PR205 auth routing", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockNavigate.mockReset();
    mockRegister.mockReset();
    mockLogin.mockReset();
  });

  test("new register success routes to /onboarding", async () => {
    mockRegister.mockResolvedValue({ ok: true });

    const { container, unmount } = renderUI(<Register />);

    setFieldValue(container.querySelector("#email"), "new@runner.com");
    setFieldValue(container.querySelector("#password"), "Password123!");
    setFieldValue(container.querySelector("#confirmPassword"), "Password123!");

    await submit(container);

    expect(mockRegister).toHaveBeenCalledWith("new@runner.com", "Password123!");
    expect(mockNavigate).toHaveBeenCalledWith("/onboarding", { replace: true });

    unmount();
  });

  test("existing login success still routes to dashboard route", async () => {
    mockLogin.mockResolvedValue({ ok: true });

    const { container, unmount } = renderUI(<Login />);

    setFieldValue(container.querySelector("#email"), "existing@runner.com");
    setFieldValue(container.querySelector("#password"), "Password123!");

    await submit(container);

    expect(mockLogin).toHaveBeenCalledWith("existing@runner.com", "Password123!");
    expect(mockNavigate).toHaveBeenCalledWith("/", { replace: true });

    unmount();
  });
});

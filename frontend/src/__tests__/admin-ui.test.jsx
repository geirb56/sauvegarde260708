import React, { act } from "react";
import { createRoot } from "react-dom/client";

import axios from "axios";

import Admin from "@/pages/Admin";
import { AuthProvider } from "@/context/AuthContext";

jest.mock("axios");

function renderAdmin() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <AuthProvider>
        <Admin />
      </AuthProvider>
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

describe("admin dashboard", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
  });

  test("loads admin users and renders status columns for admins", async () => {
    window.localStorage.setItem("access_token", "jwt-token");
    axios.get
      .mockResolvedValueOnce({
        data: {
          id: "admin-1",
          email: "admin@example.com",
          role: "admin",
          is_admin: true,
          is_email_verified: true,
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
          last_login_at: "2026-01-02T00:00:00Z",
        },
      })
      .mockResolvedValueOnce({
        data: {
          users: [
            {
              id: "user-1",
              email: "trial@example.com",
              role: "user",
              is_admin: false,
              status: "trial",
              trial_active: true,
              trial_used: true,
              trial_days_remaining: 7,
              garmin_connected: true,
            },
          ],
        },
      });

    const { container, unmount } = renderAdmin();
    await flush();
    await flush();

    expect(axios.get).toHaveBeenNthCalledWith(2, expect.stringContaining("/api/admin/users"), {
      headers: { Authorization: "******" },
    });
    expect(container.textContent).toContain("Admin dashboard");
    expect(container.textContent).toContain("trial@example.com");
    expect(container.textContent).toContain("Connected");
    expect(container.textContent).toContain("7 day(s) left");
    unmount();
  });

  test("blocks non-admin users from the admin page", async () => {
    window.localStorage.setItem("access_token", "jwt-token");
    axios.get.mockResolvedValueOnce({
      data: {
        id: "user-1",
        email: "user@example.com",
        role: "user",
        is_admin: false,
        is_email_verified: true,
        is_active: true,
        created_at: "2026-01-01T00:00:00Z",
        last_login_at: "2026-01-02T00:00:00Z",
      },
    });

    const { container, unmount } = renderAdmin();
    await flush();

    expect(container.textContent).toContain("Access denied");
    expect(axios.get).toHaveBeenCalledTimes(1);
    unmount();
  });
});

/**
 * AuthContext — JWT-based multi-user authentication.
 *
 * Provides:
 *   user         { id, email, is_email_verified, is_active }  or null
 *   loading      boolean — true during initial session check
 *   login(email, password) → { ok, error? }
 *   register(email, password) → { ok, error? }
 *   logout()
 *   refreshUser() — re-fetch /auth/me and update user state
 */

import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API_BASE_URL } from "@/config";

const AuthContext = createContext(null);

const TOKEN_KEY = "access_token";

// ── Token storage helpers ────────────────────────────────────────────────────

function saveToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Ignore storage errors (private browsing, storage full, etc.)
  }
}

function loadToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

function removeToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Ignore
  }
}

// ── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  /** Fetch current user from /api/auth/me using the stored token. */
  const refreshUser = useCallback(async () => {
    const token = loadToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }

    try {
      const res = await axios.get(`${API_BASE_URL}/auth/me`, {
        headers: { Authorization: 'Bearer ' + token },
      });
      setUser(res.data);
    } catch (err) {
      // Token expired or invalid — clear it
      if (err.response && (err.response.status === 401 || err.response.status === 403)) {
        removeToken();
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // On mount, validate any stored token
  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const login = useCallback(async (email, password) => {
    try {
      const res = await axios.post(`${API_BASE_URL}/auth/login`, { email, password });
      const { access_token, user: userData } = res.data;
      saveToken(access_token);
      setUser(userData);
      return { ok: true };
    } catch (err) {
      const message =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        "Login failed. Please try again.";
      return { ok: false, error: message };
    }
  }, []);

  const register = useCallback(async (email, password) => {
    try {
      const res = await axios.post(`${API_BASE_URL}/auth/register`, { email, password });
      const { access_token, user: userData } = res.data;
      saveToken(access_token);
      setUser(userData);
      return { ok: true };
    } catch (err) {
      const message =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        "Registration failed. Please try again.";
      return { ok: false, error: message };
    }
  }, []);

  const logout = useCallback(async () => {
    const token = loadToken();
    if (token) {
      // Best-effort server-side logout (JWT is stateless; this is for audit logs)
      try {
        await axios.post(
          `${API_BASE_URL}/auth/logout`,
          {},
          { headers: { Authorization: 'Bearer ' + token } },
        );
      } catch {
        // Ignore — client-side logout always succeeds
      }
    }
    removeToken();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

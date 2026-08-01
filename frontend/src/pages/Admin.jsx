import { useEffect, useMemo, useState } from "react";
import axios from "axios";

import { API_BASE_URL } from "@/config";
import { useAuth } from "@/context/AuthContext";

const TOKEN_KEY = "access_token";

function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function StatusBadge({ children, tone }) {
  const tones = {
    free: "bg-slate-800 text-slate-200 border-slate-700",
    trial: "bg-amber-500/15 text-amber-200 border-amber-500/30",
    premium: "bg-emerald-500/15 text-emerald-200 border-emerald-500/30",
    admin: "bg-blue-500/15 text-blue-200 border-blue-500/30",
  };

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-medium uppercase tracking-wide ${tones[tone] || tones.free}`}>
      {children}
    </span>
  );
}

export default function Admin() {
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user?.is_admin) {
      setLoading(false);
      return;
    }

    const token = getToken();
    if (!token) {
      setError("Missing session token.");
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);

    axios.get(`${API_BASE_URL}/admin/users`, {
      headers: { Authorization: "Bearer " + token },
    }).then((response) => {
      if (!cancelled) {
        setUsers(response.data.users || []);
        setError("");
      }
    }).catch((err) => {
      if (!cancelled) {
        setError(err.response?.data?.detail || "Unable to load admin dashboard.");
      }
    }).finally(() => {
      if (!cancelled) {
        setLoading(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [user]);

  const summary = useMemo(() => (
    users.reduce((acc, entry) => {
      acc.total += 1;
      acc[entry.status] = (acc[entry.status] || 0) + 1;
      if (entry.garmin_connected) acc.garmin += 1;
      if (entry.trial_active) acc.trialActive += 1;
      return acc;
    }, { total: 0, free: 0, trial: 0, premium: 0, garmin: 0, trialActive: 0 })
  ), [users]);

  if (!user?.is_admin) {
    return (
      <div className="p-4 sm:p-6 max-w-5xl mx-auto">
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4 sm:p-6">
          <h1 className="text-xl sm:text-2xl font-semibold mb-2">Admin</h1>
          <p className="text-sm text-muted-foreground">Access denied. This page is reserved for administrators.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-3xl font-semibold break-words">Admin dashboard</h1>
          <p className="text-sm text-muted-foreground">Users, subscription tier, trial usage, and Garmin connection status.</p>
        </div>
        <StatusBadge tone="admin">admin only</StatusBadge>
      </div>

      <div className="grid gap-3 sm:gap-4 grid-cols-2 md:grid-cols-4">
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4"><div className="text-sm text-muted-foreground">Users</div><div className="text-2xl sm:text-3xl font-semibold break-words">{summary.total}</div></div>
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4"><div className="text-sm text-muted-foreground">FREE / TRIAL / PREMIUM</div><div className="text-base sm:text-xl font-semibold break-words">{summary.free} / {summary.trial} / {summary.premium}</div></div>
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4"><div className="text-sm text-muted-foreground">Trial active</div><div className="text-2xl sm:text-3xl font-semibold break-words">{summary.trialActive}</div></div>
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4"><div className="text-sm text-muted-foreground">Garmin connected</div><div className="text-2xl sm:text-3xl font-semibold break-words">{summary.garmin}</div></div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-black/20 p-3 sm:p-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading admin data…</p>
        ) : error ? (
          <p className="text-sm text-red-300">{error}</p>
        ) : (
          <div className="overflow-x-auto -mx-3 sm:mx-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-muted-foreground">
                  <th className="px-3 py-3 font-medium whitespace-nowrap">User</th>
                  <th className="px-3 py-3 font-medium whitespace-nowrap">Role</th>
                  <th className="px-3 py-3 font-medium whitespace-nowrap">Status</th>
                  <th className="px-3 py-3 font-medium whitespace-nowrap">Trial</th>
                  <th className="px-3 py-3 font-medium whitespace-nowrap">Garmin</th>
                  <th className="px-3 py-3 font-medium whitespace-nowrap">Created</th>
                  <th className="px-3 py-3 font-medium whitespace-nowrap">Last login</th>
                </tr>
              </thead>
              <tbody>
                {users.map((entry) => (
                  <tr key={entry.id} className="border-b border-white/5 last:border-0">
                    <td className="px-3 py-3 align-top">
                      <div className="font-medium">{entry.email}</div>
                      <div className="text-xs text-muted-foreground">{entry.id}</div>
                    </td>
                    <td className="px-3 py-3 align-top">
                      <StatusBadge tone={entry.is_admin ? "admin" : "free"}>{entry.role}</StatusBadge>
                    </td>
                    <td className="px-3 py-3 align-top">
                      <StatusBadge tone={entry.status}>{entry.status}</StatusBadge>
                    </td>
                    <td className="px-3 py-3 align-top">
                      <div>{entry.trial_active ? "Active" : entry.trial_used ? "Used" : "Not used"}</div>
                      <div className="text-xs text-muted-foreground">
                        {entry.trial_days_remaining == null ? "—" : `${entry.trial_days_remaining} day(s) left`}
                      </div>
                    </td>
                    <td className="px-3 py-3 align-top">{entry.garmin_connected ? "Connected" : "Not connected"}</td>
                    <td className="px-3 py-3 align-top">{formatDate(entry.created_at)}</td>
                    <td className="px-3 py-3 align-top">{formatDate(entry.last_login_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * SubscriptionContext V2
 * ======================
 * Single source of truth for tier-level access in the frontend.
 *
 * Backend source: GET /api/user/features
 * Response shape (canonical, from access_control.UserAccess.to_api_dict):
 *   {
 *     plan: "free" | "trial" | "premium",
 *     trial_active: bool,
 *     has_premium_access: bool,
 *     trial_days_remaining: int | null,
 *     feature_access: { [feature: string]: bool }
 *   }
 *
 * Security contract:
 *   - Fail-closed on any error: deny all premium access until backend confirms.
 *   - The frontend NEVER decides who is premium; it only mirrors what the
 *     backend returns.
 *   - Access enforcement always happens server-side; this context is
 *     display-only / UX gating.
 */

import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

// Fail-closed sentinel: used when the backend cannot be reached.
const FAIL_CLOSED_ACCESS = {
  plan: "free",
  trial_active: false,
  has_premium_access: false,
  trial_days_remaining: null,
  feature_access: {},
};

const SubscriptionContext = createContext(null);

export function SubscriptionProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.id;
  const [access, setAccess] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAccess = useCallback(async () => {
    if (!userId) {
      setLoading(false);
      return;
    }
    try {
      const res = await axios.get(`${API}/user/features`);
      setAccess(res.data);
      setError(null);
    } catch (err) {
      console.error("[SubscriptionContext] Error fetching access tier:", err);
      setError(err);
      // Fail-closed: no premium access until backend confirms.
      setAccess(FAIL_CLOSED_ACCESS);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    fetchAccess();
  }, [fetchAccess]);

  const refreshSubscription = useCallback(() => {
    setLoading(true);
    fetchAccess();
  }, [fetchAccess]);

  // ── Tier helpers ──────────────────────────────────────────────────────────
  const plan = access?.plan ?? "free";
  const isFree    = plan === "free";
  const isTrial   = plan === "trial";
  const isPremium = plan === "premium";
  const isActive  = !isFree;  // trial or premium
  const hasPremiumAccess = access?.has_premium_access ?? false;
  const trialDaysRemaining = access?.trial_days_remaining ?? null;

  // ── Feature access ────────────────────────────────────────────────────────
  const featureAccess = access?.feature_access ?? {};

  const hasFeature = useCallback(
    (feature) => featureAccess[feature] ?? false,
    [featureAccess],
  );

  // ── Legacy display fields (backward-compatible) ───────────────────────────
  // Derive display labels locally so callers that still use statusLabel/
  // statusBadge don't break.
  const _TIER_LABELS = { free: "Gratuit", trial: "Essai gratuit", premium: "Premium" };
  const _TIER_BADGES = { free: "FREE", trial: "TRIAL", premium: "PREMIUM" };
  const _TIER_COLORS = { free: "gray", trial: "blue", premium: "amber" };
  const statusLabel      = _TIER_LABELS[plan] ?? "Gratuit";
  const statusBadge      = _TIER_BADGES[plan] ?? "FREE";
  const statusBadgeColor = _TIER_COLORS[plan] ?? "gray";

  // ── Backward-compatible `subscription` shape ──────────────────────────────
  // Some pages still read `subscription.status` or `subscription.features`.
  // We provide a synthetic object so those reads continue to work while pages
  // are migrated to the V2 helpers (isFree / isTrial / isPremium / hasFeature).
  const subscription = access
    ? {
        status: plan,
        features: featureAccess,
        trial_days_remaining: trialDaysRemaining,
        display: { label: statusLabel, badge: statusBadge, badge_color: statusBadgeColor },
      }
    : null;

  const value = {
    // ── V2 ───────────────────────────────────────────────────────────────
    plan,
    isFree,
    isTrial,
    isPremium,
    isActive,
    hasPremiumAccess,
    trialDaysRemaining,
    featureAccess,
    hasFeature,
    // ── Shared ───────────────────────────────────────────────────────────
    loading,
    error,
    refreshSubscription,
    // ── Legacy (backward-compatible) ─────────────────────────────────────
    subscription,
    canAccessPlan:  hasFeature("training_plan"),
    canAccessCoach: hasFeature("llm_access"),
    canSync:        hasFeature("sync_enabled"),
    statusLabel,
    statusBadge,
    statusBadgeColor,
  };

  return (
    <SubscriptionContext.Provider value={value}>
      {children}
    </SubscriptionContext.Provider>
  );
}

export function useSubscription() {
  const context = useContext(SubscriptionContext);
  if (!context) {
    throw new Error("useSubscription must be used within a SubscriptionProvider");
  }
  return context;
}

/**
 * withSubscription HOC (V2 — uses AccessGate internally).
 *
 * Prefer <AccessGate> for new components; this HOC remains for backward
 * compatibility with pages that still use it.
 */
export function withSubscription(Component, requiredFeature = "full_access") {
  return function ProtectedComponent(props) {
    const { hasFeature, isFree, loading } = useSubscription();

    if (loading) {
      return (
        <div className="p-4 flex justify-center text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin" />
        </div>
      );
    }

    if (isFree || !hasFeature(requiredFeature)) {
      // Lazy-loaded so Paywall is not bundled into every protected page.
      const Paywall = require("@/components/Paywall").default;
      return <Paywall />;
    }

    return <Component {...props} />;
  };
}

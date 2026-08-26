import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

const SubscriptionContext = createContext(null);

// PR198 — fail-closed canonical state used when backend cannot be reached.
// No premium access is ever granted by default.
const FAIL_CLOSED_STATE = {
  plan: "free",
  has_premium_access: false,
  trial_active: false,
  trial_days_remaining: null,
  feature_access: {},
};

export function SubscriptionProvider({ children }) {
  const { lang } = useLanguage();
  const { user } = useAuth();
  const userId = user?.id;
  // canonical: data from /user/features (access_control single source of truth)
  const [canonical, setCanonical] = useState(null);
  // display: data from /subscription/info (UI labels only)
  const [display, setDisplay] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSubscription = useCallback(async () => {
    if (!userId) {
      setLoading(false);
      return;
    }
    try {
      // PR198 — call both endpoints in parallel.
      // /user/features is the CANONICAL source for all access decisions.
      // /subscription/info is used only for display labels.
      const [featuresRes, infoRes] = await Promise.allSettled([
        axios.get(`${API}/user/features`),
        axios.get(`${API}/subscription/info?language=${lang}`),
      ]);

      if (featuresRes.status === "fulfilled") {
        setCanonical(featuresRes.value.data);
      } else {
        // FAIL CLOSED: canonical data unavailable → no premium access
        console.error("Error fetching /user/features:", featuresRes.reason);
        setCanonical(FAIL_CLOSED_STATE);
      }

      if (infoRes.status === "fulfilled") {
        setDisplay(infoRes.value.data);
      }
      // display failure is non-critical — UI labels fall back gracefully

      setError(featuresRes.status === "rejected" ? featuresRes.reason : null);
    } catch (err) {
      console.error("Error fetching subscription:", err);
      setError(err);
      // FAIL CLOSED: no premium access granted until backend confirms status
      setCanonical(FAIL_CLOSED_STATE);
    } finally {
      setLoading(false);
    }
  }, [lang, userId]);

  useEffect(() => {
    fetchSubscription();
  }, [fetchSubscription]);

  const refreshSubscription = useCallback(() => {
    setLoading(true);
    fetchSubscription();
  }, [fetchSubscription]);

  // PR198 — derive all status flags from the canonical backend contract.
  // The frontend MUST NOT reconstruct its own access policy.
  const plan = canonical?.plan ?? "free";
  const hasPremiumAccess = canonical?.has_premium_access ?? false;
  const isFree = plan === "free";
  const isTrial = canonical?.trial_active ?? false;
  const isPremium = plan === "premium";
  const isActive = hasPremiumAccess;

  // Feature access: always from canonical backend feature_access map.
  // Unknown features default to false (fail closed).
  const hasFeature = (feature) => {
    return canonical?.feature_access?.[feature] ?? false;
  };

  const trialDaysRemaining = canonical?.trial_days_remaining ?? null;

  // Derive display labels from /subscription/info when available,
  // with graceful fallback.
  const statusLabel = display?.display?.label ?? null;
  const statusBadge = display?.display?.badge ?? null;
  const statusBadgeColor = display?.display?.badge_color ?? null;

  // Legacy subscription shape for components still reading subscription.status
  // PR198: keep backward-compat shim so existing consumers don't break
  const subscription = canonical
    ? {
        status: plan,
        features: canonical.feature_access ?? {},
        trial_days_remaining: trialDaysRemaining,
        display: display?.display ?? null,
      }
    : null;

  const value = {
    subscription,
    loading,
    error,
    refreshSubscription,
    // Status helpers (canonical)
    isActive,
    isTrial,
    isPremium,
    isFree,
    hasPremiumAccess,
    // Feature helpers (canonical)
    hasFeature,
    canAccessPlan: hasFeature("training_plan"),
    canAccessCoach: hasFeature("llm_access"),
    canSync: hasFeature("sync_enabled"),
    // Trial info
    trialDaysRemaining,
    // Display info
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

// HOC pour protéger les composants
export function withSubscription(Component, requiredFeature = "full_access") {
  return function ProtectedComponent(props) {
    const { hasFeature, isFree, loading } = useSubscription();
    
    if (loading) {
      return <div className="p-4 flex justify-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div>;
    }
    
    if (isFree || !hasFeature(requiredFeature)) {
      // Import dynamique du Paywall
      const Paywall = require("@/components/Paywall").default;
      return <Paywall />;
    }
    
    return <Component {...props} />;
  };
}

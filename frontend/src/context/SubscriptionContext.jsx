import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

const SubscriptionContext = createContext(null);

// Fail-closed defaults: no premium access when status cannot be determined.
const FAIL_CLOSED_FEATURES = {
  training_plan: false,
  plan_adaptation: false,
  session_analysis: false,
  sync_enabled: false,
  api_access: false,
  llm_access: false,
  full_access: false,
  rag_access: false,
  race_predictions: false,
  full_cycle: false,
};

const FAIL_CLOSED_STATE = {
  plan: "free",
  trial_active: false,
  has_premium_access: false,
  trial_days_remaining: null,
  feature_access: FAIL_CLOSED_FEATURES,
};

export function SubscriptionProvider({ children }) {
  const { lang } = useLanguage();
  const { user } = useAuth();
  const userId = user?.id;
  // `accessData` holds the canonical /user/features contract:
  //   plan, trial_active, has_premium_access, trial_days_remaining, feature_access
  const [accessData, setAccessData] = useState(null);
  // `displayData` holds /subscription/info for billing/display UI only (not for permissions).
  const [displayData, setDisplayData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSubscription = useCallback(async () => {
    if (!userId) {
      setLoading(false);
      return;
    }
    try {
      // /user/features is the canonical authority for ALL permission decisions.
      // /subscription/info is fetched in parallel for display/billing UI only.
      const [featuresRes, infoRes] = await Promise.allSettled([
        axios.get(`${API}/user/features`),
        axios.get(`${API}/subscription/info?language=${lang}`),
      ]);

      if (featuresRes.status === "fulfilled") {
        setAccessData(featuresRes.value.data);
      } else {
        // Fail-closed: backend error → no premium access granted.
        console.error("Error fetching /user/features:", featuresRes.reason);
        setAccessData(FAIL_CLOSED_STATE);
        setError(featuresRes.reason);
      }

      if (infoRes.status === "fulfilled") {
        setDisplayData(infoRes.value.data);
      }
      // Display failure is non-fatal; permissions are already handled above.
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

  // --- Permission helpers — derived from canonical /user/features contract ---
  // Fail-closed: when accessData is null (initial load), has_premium_access
  // defaults to false via ?? false, so isFree === true until backend confirms.
  const hasPremiumAccess = accessData?.has_premium_access ?? false;
  const isActive = hasPremiumAccess;
  const isTrial = accessData?.trial_active ?? false;
  const isPremium = accessData?.plan === "premium";
  const isFree = !hasPremiumAccess;

  const hasFeature = (feature) => {
    return accessData?.feature_access?.[feature] ?? false;
  };

  const trialDaysRemaining = accessData?.trial_days_remaining;

  // Display info: from /subscription/info for billing UI; falls back to plan name.
  const _planLabels = {
    fr: { free: "Gratuit", trial: "Essai gratuit", premium: "Premium" },
    es: { free: "Gratuito", trial: "Prueba gratuita", premium: "Premium" },
    en: { free: "Free", trial: "Free trial", premium: "Premium" },
  };
  const _planBadges = {
    fr: { free: "GRATUIT", trial: "ESSAI", premium: "PREMIUM" },
    es: { free: "GRATIS", trial: "PRUEBA", premium: "PREMIUM" },
    en: { free: "FREE", trial: "TRIAL", premium: "PREMIUM" },
  };
  const _currentPlan = accessData?.plan ?? "free";
  const _labels = _planLabels[lang] ?? _planLabels.en;
  const _badges = _planBadges[lang] ?? _planBadges.en;

  const value = {
    // Raw data (for components that need full info)
    subscription: displayData,
    accessData,
    loading,
    error,
    refreshSubscription,
    // Status helpers — canonical, fail-closed
    isActive,
    isTrial,
    isPremium,
    isFree,
    // Feature helpers — canonical
    hasFeature,
    canAccessPlan: hasFeature("training_plan"),
    canAccessCoach: hasFeature("llm_access"),
    canSync: hasFeature("sync_enabled"),
    // Trial info
    trialDaysRemaining,
    // Display info (billing UI only — NOT for permission decisions)
    statusLabel: displayData?.display?.label ?? _labels[_currentPlan] ?? _labels.free,
    statusBadge: displayData?.display?.badge ?? _badges[_currentPlan] ?? _badges.free,
    statusBadgeColor: displayData?.display?.badge_color ?? (_currentPlan === "free" ? "gray" : "green"),
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

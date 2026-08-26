import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

const SubscriptionContext = createContext(null);

// Fail-closed defaults when /user/features is unavailable
const FEATURES_FAIL_CLOSED = {
  plan: "free",
  trial_active: false,
  has_premium_access: false,
  trial_days_remaining: null,
  feature_access: {},
};

export function SubscriptionProvider({ children }) {
  const { lang } = useLanguage();
  const { user } = useAuth();
  const userId = user?.id;
  const [subscription, setSubscription] = useState(null);
  const [features, setFeatures] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSubscription = useCallback(async () => {
    if (!userId) {
      setLoading(false);
      return;
    }
    try {
      // /user/features is the canonical authority for access rights (fail closed)
      const [featuresRes, infoRes] = await Promise.allSettled([
        axios.get(`${API}/user/features`),
        axios.get(`${API}/subscription/info?language=${lang}`),
      ]);

      if (featuresRes.status === "fulfilled") {
        setFeatures(featuresRes.value.data);
      } else {
        console.error("Error fetching /user/features:", featuresRes.reason);
        // Fail closed: treat as free until backend confirms access
        setFeatures(FEATURES_FAIL_CLOSED);
      }

      if (infoRes.status === "fulfilled") {
        setSubscription(infoRes.value.data);
      } else {
        // Display/billing info unavailable — not an access decision
        setSubscription(null);
      }

      setError(null);
    } catch (err) {
      console.error("Error fetching subscription:", err);
      setError(err);
      setFeatures(FEATURES_FAIL_CLOSED);
      setSubscription(null);
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

  // Access authority: derived exclusively from /user/features (fail closed)
  const hasPremiumAccess = features?.has_premium_access ?? false;
  const isTrial = features?.trial_active ?? false;
  const isPremium = hasPremiumAccess && !isTrial;
  const isFree = !hasPremiumAccess;
  const isActive = hasPremiumAccess;

  const hasFeature = (feature) => {
    // feature_access from /user/features takes priority; fall back to subscription
    if (features?.feature_access) {
      return features.feature_access[feature] ?? false;
    }
    return subscription?.features?.[feature] ?? false;
  };

  const trialDaysRemaining = features?.trial_days_remaining ?? subscription?.trial_days_remaining ?? null;

  const value = {
    subscription,
    loading,
    error,
    refreshSubscription,
    // Status helpers (authority: /user/features)
    isActive,
    isTrial,
    isPremium,
    isFree,
    hasPremiumAccess,
    // Feature helpers
    hasFeature,
    canAccessPlan: hasFeature("training_plan"),
    canAccessCoach: hasFeature("llm_access"),
    canSync: hasFeature("sync_enabled"),
    // Trial info
    trialDaysRemaining,
    // Display info (from /subscription/info, for billing UI only)
    statusLabel: subscription?.display?.label,
    statusBadge: subscription?.display?.badge,
    statusBadgeColor: subscription?.display?.badge_color
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

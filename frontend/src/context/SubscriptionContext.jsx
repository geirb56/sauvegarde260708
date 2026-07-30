import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;

const SubscriptionContext = createContext(null);

export function SubscriptionProvider({ children }) {
  const { lang } = useLanguage();
  const { user } = useAuth();
  const userId = user?.id;
  const [subscription, setSubscription] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSubscription = useCallback(async () => {
    if (!userId) {
      setSubscription(null);
      setLoading(false);
      return;
    }
    try {
      const res = await axios.get(`${API}/subscription/info?language=${lang}`);
      setSubscription(res.data);
      setError(null);
    } catch (err) {
      console.error("Error fetching subscription:", err);
      setError(err);
      // Fail-closed on error: no premium access granted until backend confirms status.
      // Never default to trial/premium — the frontend MUST NOT decide access.
      setSubscription({
        status: "free",
        features: {
          training_plan: false,
          plan_adaptation: false,
          session_analysis: false,
          sync_enabled: false,
          api_access: false,
          llm_access: false,
          full_access: false
        },
        display: {
          label: lang === "fr" ? "Accès limité" : lang === "es" ? "Acceso limitado" : "Limited access",
          badge: lang === "fr" ? "LIMITÉ" : lang === "es" ? "LIMITADO" : "LIMITED",
          badge_color: "gray"
        }
      });
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

  // Helper functions
  const isActive = subscription?.status !== "free";
  const isTrial = subscription?.status === "trial";
  const isEarlyAdopter = subscription?.status === "early_adopter";
  const isPremium = subscription?.status === "premium" || subscription?.status === "early_adopter";
  const isFree = subscription?.status === "free";

  const hasFeature = (feature) => {
    return subscription?.features?.[feature] ?? false;
  };

  const trialDaysRemaining = subscription?.trial_days_remaining;

  const value = {
    subscription,
    loading,
    error,
    refreshSubscription,
    // Status helpers
    isActive,
    isTrial,
    isEarlyAdopter,
    isPremium,
    isFree,
    // Feature helpers
    hasFeature,
    canAccessPlan: hasFeature("training_plan"),
    canAccessCoach: hasFeature("llm_access"),
    canSync: hasFeature("sync_enabled"),
    // Trial info
    trialDaysRemaining,
    // Display info
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

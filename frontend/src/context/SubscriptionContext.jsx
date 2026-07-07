import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { Loader2 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const USER_ID = "default";

const SubscriptionContext = createContext(null);

export function SubscriptionProvider({ children }) {
  const { lang } = useLanguage();
  const [subscription, setSubscription] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSubscription = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/subscription/info?user_id=${USER_ID}&language=${lang}`);
      setSubscription(res.data);
      setError(null);
    } catch (err) {
      console.error("Error fetching subscription:", err);
      setError(err);
      // Default to trial on error (display labels translated in consuming components via t())
      setSubscription({
        status: "trial",
        features: {
          training_plan: true,
          plan_adaptation: true,
          session_analysis: true,
          sync_enabled: true,
          api_access: true,
          llm_access: true,
          full_access: true
        },
        display: {
          label: lang === "fr" ? "Essai gratuit" : lang === "es" ? "Prueba gratuita" : "Free trial",
          badge: lang === "fr" ? "ESSAI" : lang === "es" ? "PRUEBA" : "TRIAL",
          badge_color: "blue"
        }
      });
    } finally {
      setLoading(false);
    }
  }, [lang]);

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
  const isPremium = subscription?.status === "premium";
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

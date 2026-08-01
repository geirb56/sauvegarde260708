import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import {
  Lock,
  Sparkles,
  CheckCircle2,
  Zap,
  Target,
  Activity,
  MessageSquare,
  Watch,
  TrendingUp,
  Crown,
} from "lucide-react";
import axios from "axios";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

const FEATURE_ICONS = {
  0: Target,
  1: Zap,
  2: Activity,
  3: MessageSquare,
  4: Watch,
  5: TrendingUp,
};

// Single Premium offer: 4.99 EUR/month via Paddle.
// The old Stripe / Early Adopter / multi-tier flow is removed.
const PREMIUM_OFFER = {
  offer_name: "Premium",
  price_display: "4,99 € / mois",
  features: [
    "Plan d'entraînement personnalisé",
    "Adaptation automatique du plan",
    "Analyses IA avancées",
    "Coach IA conversationnel illimité",
    "Synchronisation Garmin",
    "Prédictions de course",
  ],
  cta_button: "Activer Premium",
};

export default function Paywall({ onClose, returnPath = "/training" }) {
  const navigate = useNavigate();
  const { t, lang } = useLanguage();
  const { refreshSubscription } = useSubscription();

  const [loading, setLoading] = useState(false);
  const [checkoutError, setCheckoutError] = useState(null);

  // Destructure into plain identifiers so JSX uses `features.map(...)` instead of
  // `PREMIUM_OFFER.features.map(...)` (member-expression array). Same data, same UI.
  const { offer_name, features, cta_button } = PREMIUM_OFFER;

  // ── Paddle.js checkout ────────────────────────────────────────────────────
  // Security model:
  //   1. Backend creates the Paddle transaction (server-side, with verified identity).
  //   2. Frontend opens the Paddle overlay with the transaction_id.
  //   3. After payment Paddle sends a webhook to the backend.
  //   4. The backend verifies the webhook signature and activates Premium.
  //   5. The frontend refreshes its subscription state from the backend.
  //
  // The frontend NEVER decides that the user is Premium — it only displays what
  // the backend confirms via GET /api/subscription/info.
  const handleActivate = useCallback(async () => {
    setLoading(true);
    setCheckoutError(null);

    try {
      // Step 1: Create a Paddle transaction via the backend
      const res = await axios.post(`${API}/subscription/paddle/checkout`, {});
      const { transaction_id, paddle_environment, paddle_client_token } = res.data;

      if (!transaction_id || !paddle_client_token) {
        throw new Error("Invalid checkout configuration received from server");
      }

      // Step 2: Initialize Paddle.js (dynamic import to keep initial bundle lean)
      const { initializePaddle } = await import("@paddle/paddle-js");
      const paddle = await initializePaddle({
        environment: paddle_environment === "production" ? "production" : "sandbox",
        token: paddle_client_token,
      });

      if (!paddle) {
        throw new Error("Failed to initialize Paddle.js");
      }

      // Step 3: Open the Paddle checkout overlay
      paddle.Checkout.open({
        transactionId: transaction_id,
        settings: {
          displayMode: "overlay",
          theme: "dark",
          locale: lang === "fr" ? "fr" : lang === "es" ? "es" : "en",
        },
        events: {
          onPaymentSuccess: () => {
            // Refresh from backend — backend confirms Premium after webhook
            refreshSubscription();
            setLoading(false);
            if (onClose) onClose();
            else navigate(returnPath);
          },
          onCheckoutError: (err) => {
            console.error("[Paywall] Paddle checkout error:", err);
            setCheckoutError(t("paywall.checkoutError") || "Checkout failed. Please try again.");
            setLoading(false);
          },
          onCheckoutClose: () => {
            setLoading(false);
          },
        },
      });
    } catch (err) {
      console.error("[Paywall] Checkout setup error:", err);
      setCheckoutError(
        err?.response?.data?.detail ||
          t("paywall.checkoutError") ||
          "Could not start checkout. Please try again."
      );
      setLoading(false);
    }
  }, [lang, navigate, onClose, refreshSubscription, returnPath, t]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
      style={{
        background: "linear-gradient(180deg, rgba(0,0,0,0.95) 0%, rgba(15,10,30,0.98) 100%)",
      }}
      data-testid="paywall"
    >
      <div className="max-w-md w-full space-y-6 max-h-[calc(100dvh-2rem)] overflow-y-auto my-auto">
        {/* Lock icon */}
        <div className="flex justify-center">
          <div
            className="w-20 h-20 rounded-full flex items-center justify-center"
            style={{ background: "linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)" }}
          >
            <Lock className="w-10 h-10 text-white" />
          </div>
        </div>

        {/* Title */}
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold text-white">
            {t("paywall.title") || "Activez votre coach running"}
          </h1>
          <p className="text-base text-slate-300">
            {t("paywall.subtitle") || "Votre plan d'entraînement personnalisé est prêt"}
          </p>
        </div>

        {/* Offer card */}
        <div
          className="rounded-2xl p-6 space-y-4"
          style={{
            background:
              "linear-gradient(135deg, rgba(139,92,246,0.15) 0%, rgba(236,72,153,0.1) 100%)",
            border: "1px solid rgba(139,92,246,0.3)",
          }}
        >
          <div className="flex items-center gap-2">
            <Crown className="w-5 h-5 text-amber-400" />
            <span className="font-bold text-white">{PREMIUM_OFFER.offer_name}</span>
          </div>

          {/* Price */}
          <div className="text-center py-2">
            <span className="text-4xl font-bold text-white">4,99 €</span>
            <span className="text-lg text-slate-400">
              &nbsp;/ {t("paywall.perMonth") || "mois"}
            </span>
          </div>

          {/* Features */}
          <div className="space-y-2">
            {features.map((feature, idx) => {
              const Icon = FEATURE_ICONS[idx] || CheckCircle2;
              return (
                <div key={idx} className="flex items-center gap-3">
                  <div
                    className="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                    style={{ background: "rgba(34,197,94,0.2)" }}
                  >
                    <Icon className="w-3.5 h-3.5 text-emerald-400" />
                  </div>
                  <span className="text-sm text-slate-200">{feature}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Error */}
        {checkoutError && (
          <div
            className="rounded-lg p-3 text-sm text-center"
            style={{
              background: "rgba(239,68,68,0.15)",
              border: "1px solid rgba(239,68,68,0.3)",
              color: "#fca5a5",
            }}
          >
            {checkoutError}
          </div>
        )}

        {/* CTA */}
        <Button
          onClick={handleActivate}
          disabled={loading}
          className="w-full h-14 text-lg font-bold rounded-xl"
          style={{
            background: "linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)",
            border: "none",
          }}
          data-testid="paywall-cta"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <span className="animate-spin">⏳</span>
              {t("paywall.activating") || "Chargement…"}
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <Sparkles className="w-5 h-5" />
              {cta_button}
            </span>
          )}
        </Button>

        {/* Skip */}
        {onClose && (
          <button
            onClick={onClose}
            className="w-full text-center text-sm text-slate-500 hover:text-slate-300 transition-colors"
          >
            {t("paywall.maybeLater") || "Plus tard"}
          </button>
        )}
      </div>
    </div>
  );
}

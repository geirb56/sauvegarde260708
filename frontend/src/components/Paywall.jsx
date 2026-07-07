import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/context/LanguageContext";
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
  Crown
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
  5: TrendingUp
};

export default function Paywall({ 
  onClose, 
  userId = "default", 
  language: languageProp,
  returnPath = "/training"
}) {
  const navigate = useNavigate();
  const { t, lang } = useLanguage();
  const language = languageProp ?? lang;
  const [offer, setOffer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState(false);

  useEffect(() => {
    fetchOffer();
  }, [language]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchOffer = async () => {
    try {
      const res = await axios.get(`${API}/subscription/early-adopter-offer?language=${language}`);
      setOffer(res.data);
    } catch (err) {
      console.error("Error fetching offer:", err);
      setOffer({
        title: t("paywall.title"),
        subtitle: t("paywall.subtitle"),
        description: t("paywall.description"),
        offer_name: "Early Adopter",
        price: 4.99,
        price_display: t("paywall.priceDisplay"),
        price_guarantee: t("paywall.priceGuarantee"),
        features: [
          t("paywall.feature1"),
          t("paywall.feature2"),
          t("paywall.feature3"),
          t("paywall.feature4"),
          t("paywall.feature5"),
          t("paywall.feature6")
        ],
        cta_button: t("paywall.ctaButton")
      });
    } finally {
      setLoading(false);
    }
  };

  const handleActivate = async () => {
    setActivating(true);
    try {
      // Créer une session Stripe Checkout pour Early Adopter
      const res = await axios.post(
        `${API}/subscription/early-adopter/checkout?user_id=${encodeURIComponent(userId)}&origin_url=${encodeURIComponent(window.location.origin)}`
      );
      
      if (res.data?.checkout_url) {
        // Rediriger vers Stripe Checkout
        window.location.href = res.data.checkout_url;
      } else {
        console.error("No checkout URL received");
      }
    } catch (err) {
      console.error("Error creating checkout session:", err);
      setActivating(false);
    }
    // Note: pas de setActivating(false) car on redirige vers Stripe
  };

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.9)" }}>
        <div className="animate-pulse text-white">{t("common.loading")}</div>
      </div>
    );
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "linear-gradient(180deg, rgba(0,0,0,0.95) 0%, rgba(15,10,30,0.98) 100%)" }}
      data-testid="paywall"
    >
      <div className="max-w-md w-full space-y-6">
        {/* Lock Icon */}
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
            {offer?.title}
          </h1>
          <p className="text-base text-slate-300">
            {offer?.subtitle}
          </p>
          <p className="text-sm text-slate-400">
            {offer?.description}
          </p>
        </div>

        {/* Offer Card */}
        <div 
          className="rounded-2xl p-6 space-y-4"
          style={{ 
            background: "linear-gradient(135deg, rgba(139,92,246,0.15) 0%, rgba(236,72,153,0.1) 100%)",
            border: "1px solid rgba(139,92,246,0.3)"
          }}
        >
          {/* Offer Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Crown className="w-5 h-5 text-amber-400" />
              <span className="font-bold text-white">{offer?.offer_name}</span>
            </div>
            <div 
              className="px-2 py-1 rounded-full text-[10px] font-bold"
              style={{ background: "rgba(251,191,36,0.2)", color: "#fbbf24" }}
            >
              {offer?.price_guarantee}
            </div>
          </div>

          {/* Price */}
          <div className="text-center py-2">
            <span className="text-4xl font-bold text-white">{offer?.price_display?.split('/')[0]}</span>
            <span className="text-lg text-slate-400">/ {t("paywall.perMonth")}</span>
          </div>

          {/* Features */}
          <div className="space-y-2">
            {offer?.features?.map((feature, idx) => {
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

        {/* CTA Button */}
        <Button
          onClick={handleActivate}
          disabled={activating}
          className="w-full h-14 text-lg font-bold rounded-xl"
          style={{ 
            background: "linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)",
            border: "none"
          }}
          data-testid="paywall-cta"
        >
          {activating ? (
            <span className="flex items-center gap-2">
              <span className="animate-spin">⏳</span>
              {t("paywall.activating")}
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <Sparkles className="w-5 h-5" />
              {offer?.cta_button}
            </span>
          )}
        </Button>

        {/* Close / Skip */}
        {onClose && (
          <button
            onClick={onClose}
            className="w-full text-center text-sm text-slate-500 hover:text-slate-300 transition-colors"
          >
            {t("paywall.maybeLater")}
          </button>
        )}
      </div>
    </div>
  );
}

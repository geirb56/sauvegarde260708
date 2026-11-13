import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLanguage } from "@/context/LanguageContext";
import { Loader2, Zap, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import {
  SalesHero,
  WhySection,
  HowItWorksSection,
  GarminSection,
  CoachSection,
  PricingSection,
  FaqSection,
  FinalCtaSection,
  scrollToSection,
} from "@/components/commercial/SalesSections";

import { API_BASE_URL } from "@/config";
import { useSubscription } from "@/context/SubscriptionContext";
const API = API_BASE_URL;

// Tiers whose subscription counts as "premium" in the UI.
const PREMIUM_TIERS = new Set(["premium"]);

// ─── Component ────────────────────────────────────────────────────────────────

export default function Subscription() {
  const { t, lang } = useLanguage();
  const { refreshSubscription } = useSubscription();
  const [searchParams, setSearchParams] = useSearchParams();
  const [currentTier, setCurrentTier] = useState(null);
  const [loading, setLoading] = useState(true);
  const [subscribing, setSubscribing] = useState(false);
  const [trialBusy, setTrialBusy] = useState(false);
  const [garminLoading, setGarminLoading] = useState(true);
  const [garminStatus, setGarminStatus] = useState(null);
  const [subscriptionStatusError, setSubscriptionStatusError] = useState(false);
  const [garminStatusError, setGarminStatusError] = useState(false);
  const [showGarminConnect, setShowGarminConnect] = useState(false);
  const [garminUsername, setGarminUsername] = useState("");
  const [garminPassword, setGarminPassword] = useState("");
  const [trialMessage, setTrialMessage] = useState({ status: "idle", message: "" });

  const loadStatus = useCallback(async ({ showLoader = false } = {}) => {
    if (showLoader) {
      setLoading(true);
    }
    try {
      const res = await axios.get(`${API}/subscription/info?language=${lang}`);
      const nextTier = res.data.status || "free";
      setCurrentTier(nextTier);
      setSubscriptionStatusError(false);
      return { ok: true, tier: nextTier };
    } catch (e) {
      console.error(e);
      setCurrentTier(null);
      setSubscriptionStatusError(true);
      return { ok: false, tier: null };
    } finally {
      setLoading(false);
    }
  }, [lang]);

  const loadGarminStatus = useCallback(async () => {
    setGarminLoading(true);
    try {
      const res = await axios.get(`${API}/garmin/status`);
      const nextStatus = res.data || null;
      setGarminStatus(nextStatus);
      setGarminStatusError(false);
      return { ok: true, status: nextStatus };
    } catch (error) {
      console.error("Failed to load Garmin status:", error);
      setGarminStatus(null);
      setGarminStatusError(true);
      setShowGarminConnect(false);
      return { ok: false, status: null };
    } finally {
      setGarminLoading(false);
    }
  }, []);

  useEffect(() => {
    const prevTitle = document.title;
    document.title =
      "RunIndex – Suivez vos entraînements Garmin";

    loadStatus();
    loadGarminStatus();

    // Clean up any stale legacy checkout query params
    const sessionId = searchParams.get("session_id");
    const subParam = searchParams.get("subscription");
    if (sessionId || subParam) {
      setSearchParams({});
    }

    return () => {
      document.title = prevTitle;
    };
  }, [loadGarminStatus, loadStatus, searchParams, setSearchParams]);

  const syncSubscriptionState = useCallback(async () => {
    const [subscriptionResult, garminResult, accessResult] = await Promise.all([
      loadStatus(),
      loadGarminStatus(),
      refreshSubscription(),
    ]);
    return {
      tier: subscriptionResult.tier,
      subscriptionOk: subscriptionResult.ok,
      garminOk: garminResult.ok,
      accessOk: accessResult?.accessRefreshSucceeded === true,
    };
  }, [loadGarminStatus, loadStatus, refreshSubscription]);

  const handlePostGarminRefresh = useCallback(({ tier, subscriptionOk, garminOk, accessOk }) => {
    if (!subscriptionOk || !accessOk) {
      setCurrentTier(null);
      setSubscriptionStatusError(true);
      setShowGarminConnect(false);
      setTrialMessage({
        status: "error",
        message: t("subscription.subscriptionStatusError")
          || "Impossible de vérifier votre abonnement pour le moment. Réessayez.",
      });
      return;
    }

    if (!garminOk) {
      setTrialMessage({
        status: "error",
        message: t("subscription.garminStatusError")
          || "Impossible de vérifier la connexion Garmin pour le moment. Réessayez.",
      });
      return;
    }

    if (tier === "trial") {
      setTrialMessage({ status: "success", message: t("subscription.trialStarted") || "Essai gratuit de 30 jours activé !" });
      setShowGarminConnect(false);
      toast.success(t("subscription.trialStarted") || "Essai gratuit de 30 jours activé !");
      return;
    }

    if (PREMIUM_TIERS.has(tier)) {
      setTrialMessage({ status: "success", message: t("subscription.subscriptionActivated") || "Abonnement activé !" });
      setShowGarminConnect(false);
      toast.success(t("subscription.subscriptionActivated") || "Abonnement activé !");
      return;
    }

    setTrialMessage({
      status: "info",
      message:
        t("subscription.garminTrialUnavailable")
        || "Compte Garmin connecté, mais cet essai gratuit n'est plus disponible. Passez à Premium pour débloquer l'accès complet.",
    });
    setShowGarminConnect(false);
  }, [t]);

  const handleStartTrial = useCallback(async () => {
    setTrialMessage({ status: "idle", message: "" });

    if (garminStatusError) {
      setShowGarminConnect(false);
      setTrialMessage({
        status: "error",
        message: t("subscription.garminStatusError")
          || "Impossible de vérifier la connexion Garmin pour le moment. Réessayez.",
      });
      return;
    }

    const garminResult = garminStatus
      ? { ok: true, status: garminStatus }
      : garminLoading
        ? await loadGarminStatus()
        : { ok: true, status: null };
    if (!garminResult.ok) {
      setShowGarminConnect(false);
      setTrialMessage({
        status: "error",
        message: t("subscription.garminStatusError")
          || "Impossible de vérifier la connexion Garmin pour le moment. Réessayez.",
      });
      return;
    }

    const effectiveGarminStatus = garminResult.status;
    if (!effectiveGarminStatus?.connected) {
      setShowGarminConnect(true);
      return;
    }

    setTrialBusy(true);
    try {
      const nextTier = await syncSubscriptionState();
      handlePostGarminRefresh(nextTier);
    } finally {
      setTrialBusy(false);
    }
  }, [garminLoading, garminStatus, garminStatusError, handlePostGarminRefresh, loadGarminStatus, syncSubscriptionState, t]);

  const handleGarminTrialConnect = useCallback(async (event) => {
    event.preventDefault();

    if (!garminUsername.trim() || !garminPassword) {
      setTrialMessage({ status: "error", message: t("onboarding.garminCredsRequired") });
      toast.error(t("onboarding.garminCredsRequired"));
      return;
    }

    setTrialBusy(true);
    setTrialMessage({ status: "idle", message: "" });

    try {
      const res = await axios.post(`${API}/garmin/connect`, {
        garmin_username: garminUsername.trim(),
        garmin_password: garminPassword,
      });

      if (res.data?.status === "connected") {
        setGarminPassword("");
        const nextTier = await syncSubscriptionState();
        handlePostGarminRefresh(nextTier);
        return;
      }

      if (res.data?.status === "mfa_required") {
        setGarminPassword("");
        setTrialMessage({ status: "error", message: t("onboarding.garminMfa") });
        toast.error(t("onboarding.garminMfa"));
        return;
      }

      setTrialMessage({ status: "error", message: t("onboarding.garminFailed") });
      toast.error(t("onboarding.garminFailed"));
    } catch (error) {
      console.error("Failed to connect Garmin:", error);
      setTrialMessage({ status: "error", message: t("onboarding.garminFailed") });
      toast.error(t("onboarding.garminFailed"));
    } finally {
      setTrialBusy(false);
    }
  }, [garminPassword, garminUsername, handlePostGarminRefresh, syncSubscriptionState, t]);

  // ── Paddle checkout ────────────────────────────────────────────────────
  // Security: the backend creates the transaction, the frontend only opens
  // the overlay. Premium is activated server-side after the Paddle webhook.
  const handleSubscribe = async () => {
    setSubscribing(true);
    try {
      // 1. Create Paddle transaction on the backend (identity from JWT)
      const res = await axios.post(API + "/subscription/paddle/checkout", {});
      const { transaction_id, paddle_environment, paddle_client_token } = res.data;

      if (!transaction_id || !paddle_client_token) {
        throw new Error("Invalid checkout configuration");
      }

      // 2. Initialize Paddle.js
      const { initializePaddle } = await import("@paddle/paddle-js");
      const paddle = await initializePaddle({
        environment: paddle_environment === "production" ? "production" : "sandbox",
        token: paddle_client_token,
      });

      if (!paddle) throw new Error("Failed to initialize Paddle.js");

      // 3. Open checkout overlay
      paddle.Checkout.open({
        transactionId: transaction_id,
        settings: {
          displayMode: "overlay",
          theme: "dark",
        },
        events: {
          onPaymentSuccess: () => {
            toast.success(t("subscription.subscriptionActivated") || "Premium activé !");
            refreshSubscription();
            loadStatus();
            setSubscribing(false);
          },
          onCheckoutError: (err) => {
            console.error("[Subscription] Paddle checkout error:", err);
            toast.error(t("common.error") || "Checkout failed");
            setSubscribing(false);
          },
          onCheckoutClose: () => {
            setSubscribing(false);
          },
        },
      });
    } catch (e) {
      console.error("[Subscription] Checkout error:", e);
      toast.error(t("common.error") || "Could not start checkout");
      setSubscribing(false);
    }
  };


  const isCurrentlyPremium = PREMIUM_TIERS.has(currentTier);
  const isInTrial = currentTier === "trial";
  const isTierKnown = typeof currentTier === "string";
  const showTrialCta = currentTier === "free";
  const trialMessageClass = (garminStatusError || trialMessage.status === "error")
    ? "border-destructive/40 bg-destructive/10 text-destructive"
    : trialMessage.status === "success"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : "border-amber-500/40 bg-amber-500/10 text-amber-200";
  const garminMessage = garminStatusError
    ? t("subscription.garminStatusError")
      || "Impossible de vérifier la connexion Garmin pour le moment. Réessayez."
    : trialMessage.message;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  const heroActions = (
    <>
      {subscriptionStatusError ? (
        <div className="w-full max-w-md rounded-2xl border border-destructive/40 bg-destructive/10 p-4 text-left" data-testid="subscription-status-error">
          <p className="text-sm text-destructive">
            {t("subscription.subscriptionStatusError")
              || "Impossible de vérifier votre abonnement pour le moment. Réessayez."}
          </p>
          <Button
            type="button"
            variant="outline"
            className="mt-3"
            onClick={() => loadStatus({ showLoader: true })}
            data-testid="subscription-status-retry-btn"
          >
            {t("subscription.retry") || "Réessayer"}
          </Button>
        </div>
      ) : showTrialCta ? (
        <Button
          onClick={handleStartTrial}
          disabled={trialBusy}
          className="h-12 px-8 text-base font-semibold rounded-xl"
          data-testid="start-free-trial-btn"
        >
          {trialBusy && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
          Démarrer mon essai gratuit
        </Button>
      ) : (
        <div
          className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold ${
            isInTrial
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-amber-500/40 bg-amber-500/10 text-amber-200"
          }`}
          data-testid={isInTrial ? "trial-status-pill" : "premium-status-pill"}
        >
          {isInTrial ? "Essai Premium actif" : "Premium actif"}
        </div>
      )}
      <Button
        variant="outline"
        className="h-12 px-8 text-base rounded-xl border-border"
        onClick={() => scrollToSection("features")}
      >
        Voir les fonctionnalités
        <ArrowRight className="w-4 h-4 ml-2" />
      </Button>
    </>
  );

  const garminTrialPanel = showTrialCta && isTierKnown && (showGarminConnect || garminMessage) ? (
    <div className="mx-auto max-w-md space-y-3 rounded-2xl border border-border bg-card/80 p-4 text-left" data-testid="trial-garmin-panel">
      {showGarminConnect && !garminStatusError && (
        <form className="space-y-3" onSubmit={handleGarminTrialConnect} data-testid="trial-garmin-connect-form">
          <div>
            <p className="font-semibold">Connectez Garmin pour démarrer l'essai</p>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              L&apos;essai Premium de 30 jours démarre après une connexion Garmin éligible. Un seul essai est disponible par compte Garmin.
            </p>
          </div>
          <Input
            type="email"
            name="username"
            autoComplete="section-garmin username"
            value={garminUsername}
            onChange={(event) => setGarminUsername(event.target.value)}
            placeholder={t("onboarding.garminEmailPlaceholder")}
            data-testid="garmin-email-input"
          />
          <Input
            type="password"
            name="password"
            autoComplete="section-garmin current-password"
            value={garminPassword}
            onChange={(event) => setGarminPassword(event.target.value)}
            placeholder={t("onboarding.garminPasswordPlaceholder")}
            data-testid="garmin-password-input"
          />
          <Button
            type="submit"
            disabled={trialBusy}
            className="w-full"
            data-testid="trial-garmin-connect-btn"
          >
            {trialBusy && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
            {t("onboarding.connectGarminCta")}
          </Button>
        </form>
      )}

      {garminMessage ? (
        <div className={`rounded-xl border px-3 py-2 text-sm ${trialMessageClass}`} data-testid="trial-garmin-status-message">
          {garminMessage}
        </div>
      ) : null}
      {garminStatusError ? (
        <Button
          type="button"
          variant="outline"
          onClick={() => loadGarminStatus()}
          disabled={garminLoading}
          data-testid="garmin-status-retry-btn"
        >
          {garminLoading && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
          {t("subscription.retry") || "Réessayer"}
        </Button>
      ) : null}
    </div>
  ) : null;

  const pricingError = subscriptionStatusError ? (
    <div
      className="mx-auto max-w-3xl rounded-2xl border border-destructive/40 bg-destructive/10 px-5 py-4 text-sm"
      data-testid="subscription-status-error-pricing"
    >
      <p className="text-destructive">
        {t("subscription.subscriptionStatusError")
          || "Impossible de vérifier votre abonnement pour le moment. Réessayez."}
      </p>
    </div>
  ) : null;

  const trialBanner = isInTrial ? (
    <div
      className="mx-auto mb-8 max-w-2xl rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-center"
      data-testid="trial-active-banner"
    >
      <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
        {t("subscription.trialActive") || "Essai gratuit actif — accès complet"}
      </p>
    </div>
  ) : null;

  const freeAction = (
    <Button
      variant="outline"
      className="w-full mt-4"
      disabled={currentTier === "free"}
    >
      {currentTier === "free"
        ? t("subscription.currentPlan")
        : "Commencer gratuitement"}
    </Button>
  );

  const premiumAction = isCurrentlyPremium ? (
    <Button disabled className="w-full mt-4">
      {t("subscription.currentPlan")}
    </Button>
  ) : (
    <Button
      onClick={handleSubscribe}
      disabled={subscribing}
      className="w-full mt-4"
      data-testid="premium-subscribe-btn"
    >
      {subscribing ? (
        <Loader2 className="w-4 h-4 animate-spin mr-2" />
      ) : (
        <Zap className="w-4 h-4 mr-2" />
      )}
      Activer Premium
    </Button>
  );

  return (
    <div className="min-h-screen">
      <SalesHero actions={heroActions}>{garminTrialPanel}</SalesHero>
      <WhySection />
      <HowItWorksSection />
      <GarminSection />
      <CoachSection />
      <PricingSection
        error={pricingError}
        banner={trialBanner}
        freeAction={freeAction}
        premiumAction={premiumAction}
      />
      <FaqSection />
      <FinalCtaSection
        title="Prêt à voir vos données Garmin dans RunIndex ?"
        description="Connectez Garmin pour activer votre espace RunIndex et, si votre compte est éligible, l'essai Premium de 30 jours."
      >
        {showTrialCta && isTierKnown ? (
          <Button
            onClick={handleStartTrial}
            disabled={trialBusy}
            className="h-12 px-10 text-base font-semibold rounded-xl"
          >
            {trialBusy && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
            Commencer mon essai gratuit
          </Button>
        ) : null}
      </FinalCtaSection>
    </div>
  );
}

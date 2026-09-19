import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLanguage } from "@/context/LanguageContext";
import {
  Activity,
  Brain,
  TrendingUp,
  Heart,
  Calendar,
  Watch,
  Shield,
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  Zap,
  MessageSquare,
  Target,
  Sparkles,
  ArrowRight,
} from "lucide-react";
import { toast } from "sonner";

import { API_BASE_URL } from "@/config";
import { useSubscription } from "@/context/SubscriptionContext";
const API = API_BASE_URL;

// ─── Static data ──────────────────────────────────────────────────────────────

const FREE_FEATURES = [
  "Connexion Garmin",
  "Synchronisation automatique",
  "Tableau de bord",
  "RunIndex",
  "Historique récent des activités",
  "Statistiques de base",
  "Jusqu'à 10 questions au coach IA par mois",
];

const PREMIUM_FEATURES = [
  "Tout le contenu Gratuit",
  "Plan d'entraînement",
  "Adaptation du plan",
  "Analyse des séances",
  "Analyses détaillées",
  "Bilan hebdomadaire",
  "Prévisions 5 km",
  "Prévisions 10 km",
  "Prévisions Semi-marathon",
  "Prévisions Marathon",
  "Historique complet du RunIndex",
  "Questions illimitées au coach IA",
];

const WHY_FEATURES = [
  {
    icon: Activity,
    title: "Analyse des séances",
    desc: "Selon votre abonnement, RunIndex résume vos séances Garmin et met en avant les points clés.",
  },
  {
    icon: Brain,
    title: "Coach IA",
    desc: "Posez vos questions sur vos données d'entraînement. Free inclut 10 questions par mois.",
  },
  {
    icon: TrendingUp,
    title: "Suivi de progression",
    desc: "Consultez votre RunIndex actuel et son évolution dans le temps.",
  },
  {
    icon: Target,
    title: "Prévisions de course",
    desc: "Le mode Premium inclut des estimations sur 5 km, 10 km, semi-marathon et marathon.",
  },
  {
    icon: Heart,
    title: "Fatigue & récupération",
    desc: "Retrouvez des repères sur votre état de forme à partir de vos données Garmin.",
  },
  {
    icon: Calendar,
    title: "Plan d'entraînement",
    desc: "Le plan Premium s'ajuste à votre état de forme et à vos séances.",
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    title: "Connectez Garmin",
    desc: "Reliez votre compte Garmin avec une connexion sécurisée.",
  },
  {
    step: "02",
    title: "Synchronisation automatique",
    desc: "Vos activités et indicateurs compatibles remontent dans RunIndex.",
  },
  {
    step: "03",
    title: "Suivez vos données",
    desc: "RunIndex met à jour votre tableau de bord, votre RunIndex et, selon votre abonnement, vos analyses.",
  },
  {
    step: "04",
    title: "Activez Trial ou Premium",
    desc: "Le Trial donne 30 jours d'accès Premium complet après une connexion Garmin éligible.",
  },
];

const COACH_QUESTIONS = [
  "Puis-je courir aujourd'hui ?",
  "Pourquoi mon RunIndex baisse ?",
  "Suis-je en surentraînement ?",
  "Quel objectif viser sur mon prochain semi ?",
];

const FAQ_ITEMS = [
  {
    q: "Dois-je posséder une montre Garmin ?",
    a: "Oui, RunIndex se connecte exclusivement à l'écosystème Garmin pour récupérer vos données d'entraînement. Tout modèle compatible avec Garmin Connect fonctionne.",
  },
  {
    q: "Mes données sont-elles sécurisées ?",
    a: "Oui. La connexion à Garmin se fait via un parcours sécurisé, et vos données d'entraînement restent associées à votre compte RunIndex.",
  },
  {
    q: "Puis-je annuler à tout moment ?",
    a: "Oui, sans engagement ni frais. L'annulation prend effet à la fin de la période de facturation en cours.",
  },
  {
    q: "Comment fonctionne l'essai gratuit ?",
    a: "L'essai donne 30 jours d'accès Premium complet après une connexion Garmin éligible. Un seul essai est disponible par compte Garmin. À la fin de l'essai, le compte repasse en Free sauf abonnement Premium actif.",
  },
  {
    q: "Le coach IA remplace-t-il un entraîneur ?",
    a: "Non. Le coach IA est un outil complémentaire qui analyse vos données et répond à vos questions. Pour un suivi approfondi, un entraîneur humain reste irremplaçable.",
  },
];

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
  const [openFaq, setOpenFaq] = useState(null);
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

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth" });
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

  return (
    <div className="min-h-screen">

      {/* ── HERO ──────────────────────────────────────────────────────────── */}
      <section
        id="hero"
        className="relative flex flex-col items-center justify-center px-4 py-20 text-center overflow-hidden"
      >
        {/* Ambient glow */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse at 50% 0%, rgba(76,175,80,0.12) 0%, transparent 65%)",
          }}
        />

        <div className="relative z-10 max-w-3xl mx-auto space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-primary/30 bg-primary/10 text-primary text-xs font-medium">
            <Sparkles className="w-3 h-3" />
            IA + données Garmin
          </div>

          <h1 className="font-heading text-4xl sm:text-5xl md:text-6xl uppercase tracking-tight font-bold text-white leading-tight">
            Analysez vos entraînements Garmin.{" "}
            <span className="text-primary">Suivez votre progression.</span>
          </h1>

          <p className="text-muted-foreground text-base sm:text-lg max-w-xl mx-auto leading-relaxed">
            Connectez Garmin pour retrouver vos activités, votre RunIndex et,
            selon votre abonnement, des analyses, des prévisions et un plan
            d&apos;entraînement.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
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
              onClick={() => scrollTo("features")}
            >
              Voir les fonctionnalités
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </div>

          {showTrialCta && isTierKnown && (showGarminConnect || garminMessage) && (
            <div className="mx-auto max-w-md space-y-3 rounded-2xl border border-border bg-card/80 p-4 text-left" data-testid="trial-garmin-panel">
              {showGarminConnect && !garminStatusError && (
                <form className="space-y-3" onSubmit={handleGarminTrialConnect} data-testid="trial-garmin-connect-form">
                  <div>
                    <p className="font-semibold">Connectez Garmin pour démarrer l'essai</p>
                    <p className="mt-1 text-xs text-muted-foreground">
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
          )}

          <div className="flex flex-wrap items-center justify-center gap-4 pt-2 text-xs text-muted-foreground">
            {[
              "Essai Premium 30 jours si Garmin éligible",
              "Sans engagement",
              "Résiliable à tout moment",
            ].map((label) => (
              <span key={label} className="flex items-center gap-1">
                <Check className="w-3 h-3 text-primary" />
                {label}
              </span>
            ))}
          </div>
        </div>

        {/* Illustration cards */}
        <div className="relative mt-14 w-full max-w-lg mx-auto px-4">
          <p className="mb-3 text-center text-xs text-muted-foreground">
            Exemples illustratifs
          </p>
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            {[
              { icon: Activity, label: "RunIndex", value: "87", color: "text-primary" },
              { icon: Heart, label: "Récupération", value: "94 %", color: "text-rose-400" },
              { icon: TrendingUp, label: "Progression", value: "+12 %", color: "text-amber-400" },
            ].map(({ icon: Icon, label, value, color }) => (
              <div
                key={label}
                className="rounded-xl border border-border bg-card/60 p-3 sm:p-4 text-center backdrop-blur-sm min-w-0"
              >
                <Icon className={`w-5 h-5 mx-auto mb-2 ${color}`} />
                <div className={`text-lg sm:text-xl font-bold ${color} break-words`}>{value}</div>
                <div className="text-[10px] text-muted-foreground mt-1 truncate">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── POURQUOI RUNINDEX ─────────────────────────────────────────────── */}
      <section id="features" className="px-4 py-16 max-w-6xl mx-auto">
        <div className="text-center mb-10">
          <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold mb-3">
            Pourquoi RunIndex ?
          </h2>
          <p className="text-muted-foreground text-sm max-w-lg mx-auto">
            Des repères clairs pour relire vos entraînements Garmin.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {WHY_FEATURES.map(({ icon: Icon, title, desc }) => (
            <Card
              key={title}
              className="border-border bg-card/50 hover:border-primary/40 hover:bg-card transition-all duration-200 group cursor-default"
            >
              <CardContent className="p-6">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center mb-4 group-hover:bg-primary/20 transition-colors">
                  <Icon className="w-5 h-5 text-primary" />
                </div>
                <h3 className="font-semibold text-sm mb-2">{title}</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* ── COMMENT ÇA MARCHE ─────────────────────────────────────────────── */}
      <section
        id="how-it-works"
        className="px-4 py-16"
        style={{ background: "hsl(var(--card))" }}
      >
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold mb-3">
              Comment ça marche ?
            </h2>
            <p className="text-muted-foreground text-sm">En quelques étapes.</p>
          </div>

          <div className="space-y-8">
            {HOW_IT_WORKS.map(({ step, title, desc }) => (
              <div key={step} className="flex items-start gap-5">
                <div
                  className="shrink-0 w-12 h-12 rounded-full flex items-center justify-center font-bold text-sm font-mono"
                  style={{
                    background: "hsl(var(--primary))",
                    color: "hsl(var(--primary-foreground))",
                  }}
                >
                  {step}
                </div>
                <div className="flex-1 pt-2.5">
                  <h3 className="font-semibold text-sm mb-1">{title}</h3>
                  <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── GARMIN ────────────────────────────────────────────────────────── */}
      <section id="garmin" className="px-4 py-16 max-w-6xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-border bg-card text-xs font-medium text-muted-foreground">
              <Watch className="w-3 h-3" />
              Connexion sécurisée
            </div>
            <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold">
              Connectez votre compte Garmin
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              RunIndex récupère vos activités et les indicateurs compatibles
              nécessaires pour alimenter vos vues et vos fonctionnalités.
            </p>
            <div className="space-y-3 pt-1">
              {[
                "Connexion sécurisée",
                "Import des activités compatibles",
                "Essai Premium 30 jours si éligible",
              ].map((item) => (
                <div key={item} className="flex items-center gap-3 text-sm">
                  <div className="w-5 h-5 rounded-full bg-primary/15 flex items-center justify-center shrink-0">
                    <Check className="w-3 h-3 text-primary" />
                  </div>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-card/50 p-8 flex flex-col items-center justify-center gap-5 text-center">
            <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center">
              <Watch className="w-8 h-8 text-primary" />
            </div>
            <div>
              <p className="font-bold text-lg">Garmin Connect</p>
              <p className="text-xs text-muted-foreground mt-1">
                La connexion Garmin reste nécessaire pour importer vos données
              </p>
            </div>
            <div className="flex gap-8">
              {[
                { title: "Activités", subtitle: "données compatibles" },
                { title: "Sommeil", subtitle: "si disponible" },
                { title: "Charge", subtitle: "selon Garmin" },
              ].map(({ title, subtitle }) => (
                <div key={title} className="text-center">
                  <p className="text-primary font-bold text-lg">{title}</p>
                  <p className="text-xs text-muted-foreground">{subtitle}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── COACH IA ──────────────────────────────────────────────────────── */}
      <section
        id="coach"
        className="px-4 py-16"
        style={{ background: "hsl(var(--card))" }}
      >
        <div className="max-w-4xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
            <div className="space-y-4">
              <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold">
                Posez vos questions au coach IA
              </h2>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Le coach IA aide à relire vos données et vos entraînements.
                Free inclut 10 questions par mois ; Trial et Premium donnent
                l&apos;accès complet.
              </p>
            </div>

            <div className="space-y-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Exemples de questions
              </p>
              {COACH_QUESTIONS.map((question, idx) => (
                <div
                  key={idx}
                  className={`px-4 py-3 rounded-2xl text-sm ${
                    idx % 2 === 0
                      ? "bg-primary/10 ml-4 rounded-tl-sm"
                      : "border border-border bg-card mr-4 rounded-tr-sm"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {idx % 2 === 0 ? (
                      <MessageSquare className="w-3.5 h-3.5 text-primary shrink-0" />
                    ) : (
                      <Brain className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                    )}
                    <span
                      className={
                        idx % 2 === 0 ? "" : "text-muted-foreground"
                      }
                    >
                      {question}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── TARIFS ────────────────────────────────────────────────────────── */}
      <section id="pricing" className="px-4 py-16 max-w-6xl mx-auto">
        <div className="text-center mb-10">
          <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold mb-3">
            Tarifs
          </h2>
          <p className="text-muted-foreground text-sm">
            Trois états d&apos;abonnement : FREE, TRIAL et PREMIUM.
          </p>
        </div>

        {subscriptionStatusError ? (
          <div
            className="mx-auto max-w-3xl rounded-2xl border border-destructive/40 bg-destructive/10 px-5 py-4 text-sm"
            data-testid="subscription-status-error-pricing"
          >
            <p className="text-destructive">
              {t("subscription.subscriptionStatusError")
                || "Impossible de vérifier votre abonnement pour le moment. Réessayez."}
            </p>
          </div>
        ) : (
          <>
            <div
              className="mx-auto mb-8 max-w-3xl rounded-2xl border border-border bg-card/50 px-5 py-4 text-sm"
              data-testid="subscription-trial-info"
            >
              <p className="font-semibold">TRIAL</p>
              <p className="mt-1 text-muted-foreground">
                30 jours d&apos;accès Premium complet après une connexion Garmin éligible.
                Un seul essai est disponible par compte Garmin.
              </p>
            </div>

            {/* Trial banner (preserved) */}
            {isInTrial && (
              <div
                className="mx-auto mb-8 max-w-2xl rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-center"
                data-testid="trial-active-banner"
              >
                <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
                  {t("subscription.trialActive") || "Essai gratuit actif — accès complet"}
                </p>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
          {/* Free */}
              <Card className="border-border" data-testid="subscription-free-card">
                <CardContent className="p-6 flex flex-col h-full">
                  <div className="mb-auto">
                    <h3 className="font-bold text-lg mb-1">FREE</h3>
                    <p className="text-xs text-muted-foreground mb-5">
                      Pour découvrir RunIndex
                    </p>
                    <div className="mb-6">
                      <span className="text-3xl font-bold">0 €</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        / toujours gratuit
                      </span>
                    </div>
                    <ul className="space-y-2 mb-6">
                      {FREE_FEATURES.map((f) => (
                        <li key={f} className="flex items-start gap-2 text-xs">
                          <Check className="w-3 h-3 text-primary mt-0.5 shrink-0" />
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <Button
                    variant="outline"
                    className="w-full mt-4"
                    disabled={currentTier === "free"}
                  >
                    {currentTier === "free"
                      ? t("subscription.currentPlan")
                      : "Commencer gratuitement"}
                  </Button>
                </CardContent>
              </Card>

              {/* Premium */}
              <Card
                className="border-primary/60 relative"
                style={{ boxShadow: "0 0 40px rgba(76,175,80,0.08)" }}
              >
                <CardContent className="p-6 flex flex-col h-full">
                  <div className="mb-auto">
                    <h3 className="font-bold text-lg mb-1">PREMIUM</h3>
                    <p className="text-xs text-muted-foreground mb-5">
                      Accès complet à RunIndex
                    </p>
                    <div className="mb-1">
                      <span className="text-3xl font-bold">4,99 €</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        / mois
                      </span>
                    </div>
                    <p className="text-xs text-primary mb-6">
                      TRIAL : 30 jours Premium après connexion Garmin éligible
                    </p>
                    <ul className="space-y-2 mb-6">
                      {PREMIUM_FEATURES.map((f) => (
                        <li key={f} className="flex items-start gap-2 text-xs">
                          <Check className="w-3 h-3 text-primary mt-0.5 shrink-0" />
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  {isCurrentlyPremium ? (
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
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        )}

        <div className="mt-6 text-center space-y-1">
          <p className="text-xs text-muted-foreground">
            Le plan TRIAL donne 30 jours Premium après connexion Garmin éligible.
          </p>
          <p className="text-xs text-muted-foreground">
            Un seul essai est disponible par compte Garmin.
          </p>
        </div>
      </section>

      {/* ── FAQ ───────────────────────────────────────────────────────────── */}
      <section
        id="faq"
        className="px-4 py-16"
        style={{ background: "hsl(var(--card))" }}
      >
        <div className="max-w-2xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold mb-3">
              Questions fréquentes
            </h2>
          </div>

          <div className="space-y-3">
            {FAQ_ITEMS.map(({ q, a }, idx) => (
              <div
                key={idx}
                className="rounded-xl border border-border overflow-hidden"
              >
                <button
                  className="w-full flex items-center justify-between px-5 py-4 text-left text-sm font-medium hover:bg-muted/50 transition-colors"
                  onClick={() => setOpenFaq(openFaq === idx ? null : idx)}
                  aria-expanded={openFaq === idx}
                  aria-controls={`faq-answer-${idx}`}
                >
                  <span>{q}</span>
                  {openFaq === idx ? (
                    <ChevronUp className="w-4 h-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="w-4 h-4 shrink-0 text-muted-foreground" />
                  )}
                </button>
                {openFaq === idx && (
                  <div
                    id={`faq-answer-${idx}`}
                    className="px-5 pb-4 text-xs text-muted-foreground leading-relaxed border-t border-border pt-3"
                  >
                    {a}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA FINAL ─────────────────────────────────────────────────────── */}
      <section id="cta" className="px-4 py-20 max-w-2xl mx-auto text-center">
        <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold mb-4">
          Prêt à voir vos données Garmin dans RunIndex ?
        </h2>
        <p className="text-muted-foreground text-sm mb-8 max-w-md mx-auto leading-relaxed">
          Connectez Garmin pour activer votre espace RunIndex et, si votre
          compte est éligible, l&apos;essai Premium de 30 jours.
        </p>
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

        <div className="flex flex-wrap items-center justify-center gap-6 mt-6 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Shield className="w-3 h-3" />
            Paiement sécurisé Paddle
          </span>
          <span className="flex items-center gap-1">
            <Check className="w-3 h-3" />
            Essai 30 jours si éligible
          </span>
        </div>
      </section>
    </div>
  );
}

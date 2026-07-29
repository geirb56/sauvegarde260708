import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import { useAuth } from "@/context/AuthContext";
import { useSubscription } from "@/context/SubscriptionContext";
const API = API_BASE_URL;

// ─── Static data ──────────────────────────────────────────────────────────────

const FREE_FEATURES = [
  "Synchronisation Garmin",
  "Tableau de bord",
  "Analyse automatique des séances",
  "Revue hebdomadaire",
  "Historique récent",
  "Jusqu'à 10 questions au coach IA par mois",
];

const PREMIUM_FEATURES = [
  "Tout le contenu Gratuit",
  "Analyses IA avancées",
  "Recommandations personnalisées",
  "Prévisions 5 km",
  "Prévisions 10 km",
  "Prévisions Semi-marathon",
  "Prévisions Marathon",
  "Évolution du RunIndex",
  "Estimation de la VMA",
  "Analyse fatigue / récupération",
  "Historique complet",
  "Tendances",
  "Coach IA prioritaire",
];

const WHY_FEATURES = [
  {
    icon: Activity,
    title: "Analyse automatique",
    desc: "Chaque séance est analysée automatiquement dès sa synchronisation Garmin.",
  },
  {
    icon: Brain,
    title: "Coach IA",
    desc: "Posez vos questions et obtenez des conseils personnalisés adaptés à votre état de forme.",
  },
  {
    icon: TrendingUp,
    title: "Suivi de progression",
    desc: "Visualisez l'évolution de votre RunIndex et de vos performances.",
  },
  {
    icon: Target,
    title: "Prévisions de course",
    desc: "Estimation de vos chronos sur : 5 km, 10 km, Semi-marathon, Marathon.",
  },
  {
    icon: Heart,
    title: "Fatigue & récupération",
    desc: "Comprenez quand pousser... et quand récupérer.",
  },
  {
    icon: Calendar,
    title: "Plan d'entraînement intelligent",
    desc: "Le plan s'adapte automatiquement à votre récupération.",
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    title: "Connectez Garmin",
    desc: "Liez votre compte Garmin en moins d'une minute via OAuth sécurisé.",
  },
  {
    step: "02",
    title: "Synchronisation automatique",
    desc: "Vos activités, fréquence cardiaque, sommeil et charge d'entraînement sont récupérés automatiquement.",
  },
  {
    step: "03",
    title: "RunIndex analyse vos données",
    desc: "Notre IA analyse chaque séance et calcule votre RunIndex en temps réel.",
  },
  {
    step: "04",
    title: "Recommandations personnalisées",
    desc: "Recevez des conseils adaptés à votre état de forme actuel.",
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
    a: "Absolument. Vos données sont transmises via OAuth sécurisé et stockées de manière chiffrée. Nous ne partageons jamais vos données personnelles avec des tiers.",
  },
  {
    q: "Puis-je annuler à tout moment ?",
    a: "Oui, sans engagement ni frais. L'annulation prend effet à la fin de la période de facturation en cours.",
  },
  {
    q: "Comment fonctionne l'essai gratuit ?",
    a: "Vous bénéficiez de 30 jours d'accès Premium complet. À l'issue de l'essai, vous passez automatiquement sur le plan Gratuit sauf si vous choisissez de continuer en Premium.",
  },
  {
    q: "Le coach IA remplace-t-il un entraîneur ?",
    a: "Non. Le coach IA est un outil complémentaire qui analyse vos données et répond à vos questions. Pour un suivi approfondi, un entraîneur humain reste irremplaçable.",
  },
];

// Tiers whose subscription counts as "premium" in the UI.
// Legacy tiers (starter, confort, pro) are kept for backward compatibility with
// existing subscribers who may still be on those plans in the backend.
const PREMIUM_TIERS = new Set(["premium", "starter", "confort", "pro", "early_adopter"]);

// ─── Component ────────────────────────────────────────────────────────────────

export default function Subscription() {
  const { user } = useAuth();
  const userId = user?.id;
  const { t } = useLanguage();
  const { refreshSubscription } = useSubscription();
  const [searchParams, setSearchParams] = useSearchParams();
  const [currentTier, setCurrentTier] = useState("free");
  const [loading, setLoading] = useState(true);
  const [subscribing, setSubscribing] = useState(false);
  const [openFaq, setOpenFaq] = useState(null);

  useEffect(() => {
    const prevTitle = document.title;
    document.title =
      "RunIndex – Analysez vos entraînements Garmin et progressez plus vite";

    loadStatus();

    // Clean up any stale Stripe-era query params
    const sessionId = searchParams.get("session_id");
    const subParam = searchParams.get("subscription");
    if (sessionId || subParam) {
      setSearchParams({});
    }

    return () => {
      document.title = prevTitle;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadStatus = async () => {
    try {
      const res = await axios.get(API + "/subscription/info");
      setCurrentTier(res.data.status || "free");
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

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
            Analysez vos entraînements.{" "}
            <span className="text-primary">Progressez plus vite.</span>
          </h1>

          <p className="text-muted-foreground text-base sm:text-lg max-w-xl mx-auto leading-relaxed">
            Connectez votre montre Garmin et laissez RunIndex analyser
            automatiquement votre récupération, votre charge d'entraînement et
            vos performances grâce à l'intelligence artificielle.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
            <Button
              onClick={isCurrentlyPremium ? () => scrollTo("pricing") : handleSubscribe}
              disabled={subscribing}
              className="h-12 px-8 text-base font-semibold rounded-xl"
            >
              {subscribing && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
              {isCurrentlyPremium ? "Voir mon abonnement" : "Démarrer mon essai gratuit"}
            </Button>
            <Button
              variant="outline"
              className="h-12 px-8 text-base rounded-xl border-border"
              onClick={() => scrollTo("features")}
            >
              Voir les fonctionnalités
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </div>

          <div className="flex flex-wrap items-center justify-center gap-4 pt-2 text-xs text-muted-foreground">
            {[
              "30 jours gratuits",
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
          <div className="grid grid-cols-3 gap-3">
            {[
              { icon: Activity, label: "RunIndex", value: "87", color: "text-primary" },
              { icon: Heart, label: "Récupération", value: "94 %", color: "text-rose-400" },
              { icon: TrendingUp, label: "Progression", value: "+12 %", color: "text-amber-400" },
            ].map(({ icon: Icon, label, value, color }) => (
              <div
                key={label}
                className="rounded-xl border border-border bg-card/60 p-4 text-center backdrop-blur-sm"
              >
                <Icon className={`w-5 h-5 mx-auto mb-2 ${color}`} />
                <div className={`text-xl font-bold ${color}`}>{value}</div>
                <div className="text-[10px] text-muted-foreground mt-1">{label}</div>
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
            Une plateforme intelligente qui comprend vos entraînements en profondeur.
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
            <p className="text-muted-foreground text-sm">En 4 étapes simples.</p>
          </div>

          <div className="space-y-8">
            {HOW_IT_WORKS.map(({ step, title, desc }, idx) => (
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
              Intégration officielle
            </div>
            <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold">
              Connectez votre montre Garmin en moins d'une minute
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              RunIndex récupère automatiquement vos activités, votre fréquence
              cardiaque, votre sommeil, votre charge d'entraînement et vos autres
              données afin de produire des analyses personnalisées.
            </p>
            <div className="space-y-3 pt-1">
              {[
                "Synchronisation automatique",
                "Données sécurisées",
                "Connexion OAuth",
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
                Synchronisation sécurisée via OAuth 2.0
              </p>
            </div>
            <div className="flex gap-8">
              {[
                { value: "∞", label: "Activités" },
                { value: "24/7", label: "Sync auto" },
                { value: "🔒", label: "Chiffré" },
              ].map(({ value, label }) => (
                <div key={label} className="text-center">
                  <p className="text-primary font-bold text-lg">{value}</p>
                  <p className="text-xs text-muted-foreground">{label}</p>
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
                Votre coach personnel disponible 24h/24
              </h2>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Posez vos questions à votre coach IA qui connaît parfaitement
                vos données Garmin et peut vous répondre à tout moment.
              </p>
            </div>

            <div className="space-y-3">
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
            Simple, transparent, sans engagement.
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
          <Card className="border-border">
            <CardContent className="p-6 flex flex-col h-full">
              <div className="mb-auto">
                <h3 className="font-bold text-lg mb-1">Gratuit</h3>
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
            <div className="absolute -top-3 left-1/2 -translate-x-1/2">
              <Badge className="bg-amber-500 text-white text-xs px-3 py-1">
                ⭐ Recommandé
              </Badge>
            </div>
            <CardContent className="p-6 flex flex-col h-full">
              <div className="mb-auto">
                <h3 className="font-bold text-lg mb-1">Premium</h3>
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
                  30 jours d'essai gratuit · sans engagement
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
                >
                  {subscribing ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  ) : (
                    <Zap className="w-4 h-4 mr-2" />
                  )}
                  Démarrer l'essai gratuit
                </Button>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="mt-6 text-center space-y-1">
          <p className="text-xs text-muted-foreground">
            Aucun paiement pendant les 30 premiers jours.
          </p>
          <p className="text-xs text-muted-foreground">
            Résiliable à tout moment.
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
          Prêt à progresser plus intelligemment ?
        </h2>
        <p className="text-muted-foreground text-sm mb-8 max-w-md mx-auto leading-relaxed">
          Rejoignez les coureurs qui utilisent déjà RunIndex pour mieux
          comprendre leurs entraînements et atteindre leurs objectifs.
        </p>
        <Button
          onClick={isCurrentlyPremium ? () => scrollTo("pricing") : handleSubscribe}
          disabled={subscribing}
          className="h-12 px-10 text-base font-semibold rounded-xl"
        >
          {subscribing && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
          {isCurrentlyPremium ? "Voir mon abonnement" : "Commencer mon essai gratuit"}
        </Button>

        <div className="flex flex-wrap items-center justify-center gap-6 mt-6 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Shield className="w-3 h-3" />
            Paiement sécurisé Paddle
          </span>
          <span className="flex items-center gap-1">
            <Check className="w-3 h-3" />
            30 jours gratuits
          </span>
        </div>
      </section>
    </div>
  );
}

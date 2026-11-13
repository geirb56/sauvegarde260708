/**
 * Presentation-only commercial sections shared by the public Landing page and
 * the authenticated Subscription page. No API call, auth or routing here:
 * actions are injected by the caller through slots.
 */
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
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
  MessageSquare,
  Target,
  Sparkles,
} from "lucide-react";

export const FREE_FEATURES = [
  "Connexion Garmin",
  "Synchronisation automatique",
  "Tableau de bord",
  "RunIndex",
  "Historique récent des activités",
  "Statistiques de base",
  "Jusqu'à 10 questions au coach IA par mois",
];

export const PREMIUM_FEATURES = [
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

const TRUST_LABELS = [
  "Essai Premium 30 jours si Garmin éligible",
  "Sans engagement",
  "Résiliable à tout moment",
];

const ILLUSTRATION_CARDS = [
  { icon: Activity, label: "RunIndex", value: "87", color: "text-primary" },
  { icon: Heart, label: "Récupération", value: "94 %", color: "text-rose-400" },
  { icon: TrendingUp, label: "Progression", value: "+12 %", color: "text-amber-400" },
];

export const scrollToSection = (id) => {
  const el = document.getElementById(id);
  if (!el) return;
  const prefersReducedMotion = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth" });
};

/** `actions` = CTA row, `children` = optional panel rendered under the CTAs. */
export function SalesHero({ actions, children }) {
  return (
    <section
      id="hero"
      className="relative flex flex-col items-center justify-center px-4 py-20 text-center overflow-hidden"
    >
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
          {actions}
        </div>

        {children}

        <div className="flex flex-wrap items-center justify-center gap-4 pt-2 text-xs text-muted-foreground">
          {TRUST_LABELS.map((label) => (
            <span key={label} className="flex items-center gap-1">
              <Check className="w-3 h-3 text-primary" />
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="relative mt-14 w-full max-w-lg mx-auto px-4">
        <p className="mb-3 text-center text-sm leading-relaxed text-muted-foreground">
          Exemples illustratifs
        </p>
        <div className="grid grid-cols-3 gap-2 sm:gap-3">
          {ILLUSTRATION_CARDS.map(({ icon: Icon, label, value, color }) => (
            <div
              key={label}
              className="rounded-xl border border-border bg-card/60 p-3 sm:p-4 text-center backdrop-blur-sm min-w-0"
            >
              <Icon className={`w-5 h-5 mx-auto mb-2 ${color}`} />
              <div className={`text-lg sm:text-xl font-bold ${color} break-words`}>{value}</div>
              <div className="text-[11px] text-muted-foreground mt-1">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function WhySection() {
  return (
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
              <p className="font-sans text-sm text-muted-foreground leading-relaxed">{desc}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

export function HowItWorksSection() {
  return (
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
                <p className="font-sans text-sm text-muted-foreground leading-relaxed">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function GarminSection() {
  return (
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
            <p className="text-sm leading-relaxed text-muted-foreground mt-1">
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
  );
}

export function CoachSection() {
  return (
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
                  <span className={idx % 2 === 0 ? "" : "text-muted-foreground"}>
                    {question}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * `error` replaces the plans when set. `banner` is shown above the plans;
 * `freeAction` / `premiumAction` are the plan CTAs injected by the caller.
 */
export function PricingSection({ error = null, banner = null, freeAction, premiumAction }) {
  return (
    <section id="pricing" className="px-4 py-16 max-w-6xl mx-auto">
      <div className="text-center mb-10">
        <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold mb-3">
          Tarifs
        </h2>
        <p className="text-muted-foreground text-sm">
          Trois états d&apos;abonnement : FREE, TRIAL et PREMIUM.
        </p>
      </div>

      {error ? (
        error
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

          {banner}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
            <Card className="border-border" data-testid="subscription-free-card">
              <CardContent className="p-6 flex flex-col h-full">
                <div className="mb-auto">
                  <h3 className="font-bold text-lg mb-1">FREE</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground mb-5">
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
                {freeAction}
              </CardContent>
            </Card>

            <Card
              className="border-primary/60 relative"
              style={{ boxShadow: "0 0 40px rgba(76,175,80,0.08)" }}
            >
              <CardContent className="p-6 flex flex-col h-full">
                <div className="mb-auto">
                  <h3 className="font-bold text-lg mb-1">PREMIUM</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground mb-5">
                    Accès complet à RunIndex
                  </p>
                  <div className="mb-1">
                    <span className="text-3xl font-bold">4,99 €</span>
                    <span className="text-xs text-muted-foreground ml-2">/ mois</span>
                  </div>
                  <p className="text-sm leading-relaxed text-primary mb-6">
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
                {premiumAction}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <div className="mt-6 text-center space-y-1">
        <p className="text-sm leading-relaxed text-muted-foreground">
          Le plan TRIAL donne 30 jours Premium après connexion Garmin éligible.
        </p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Un seul essai est disponible par compte Garmin.
        </p>
      </div>
    </section>
  );
}

export function FaqSection() {
  const [openFaq, setOpenFaq] = useState(null);
  return (
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
            <div key={idx} className="rounded-xl border border-border overflow-hidden">
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
                  className="px-5 pb-4 font-sans text-sm text-muted-foreground leading-relaxed border-t border-border pt-3"
                >
                  {a}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** `children` = optional CTA rendered between the copy and the trust labels. */
export function FinalCtaSection({ title, description, children }) {
  return (
    <section id="cta" className="px-4 py-20 max-w-2xl mx-auto text-center">
      <h2 className="font-heading text-2xl sm:text-3xl md:text-4xl uppercase tracking-tight font-bold mb-4">
        {title}
      </h2>
      <p className="text-muted-foreground text-sm mb-8 max-w-md mx-auto leading-relaxed">
        {description}
      </p>
      {children}

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
  );
}

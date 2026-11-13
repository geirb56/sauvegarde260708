import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
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

/**
 * Public sales page served on "/" for anonymous visitors.
 * Navigation only: it never calls an API, nor starts Garmin, trial or Paddle.
 */
export default function Landing() {
  const trialCta = (testId, className = "") => (
    <Button
      asChild
      className={`h-12 px-8 text-base font-semibold rounded-xl ${className}`.trim()}
    >
      <Link to="/register" data-testid={testId}>
        Essayer gratuitement
      </Link>
    </Button>
  );

  const loginCta = (testId, className = "") => (
    <Button
      asChild
      variant="outline"
      className={`h-12 px-8 text-base rounded-xl border-border ${className}`.trim()}
    >
      <Link to="/login" data-testid={testId}>
        Se connecter
      </Link>
    </Button>
  );

  return (
    <div className="min-h-screen" data-testid="landing-page">
      <header className="flex items-center justify-between gap-3 px-4 py-3 max-w-6xl mx-auto">
        <img
          src="/runindex-logo.png"
          alt="RunIndex"
          className="h-8 w-auto max-w-[140px] object-contain"
        />
        <Link
          to="/login"
          className="text-sm font-medium text-muted-foreground hover:text-foreground"
          data-testid="landing-header-login"
        >
          Se connecter
        </Link>
      </header>

      <SalesHero
        actions={(
          <>
            {trialCta("landing-hero-trial", "w-full sm:w-auto")}
            {loginCta("landing-hero-login", "w-full sm:w-auto")}
          </>
        )}
      >
        <button
          type="button"
          onClick={() => scrollToSection("features")}
          className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
        >
          Voir les fonctionnalités
          <ArrowRight className="w-4 h-4 ml-2" />
        </button>
      </SalesHero>
      <WhySection />
      <HowItWorksSection />
      <GarminSection />
      <CoachSection />
      <PricingSection
        freeAction={trialCta("landing-free-trial", "w-full mt-4")}
        premiumAction={trialCta("landing-premium-trial", "w-full mt-4")}
      />
      <FaqSection />
      <FinalCtaSection
        title="Prêt à voir vos données Garmin dans RunIndex ?"
        description="Créez votre compte RunIndex, connectez Garmin et, si votre compte est éligible, profitez de l'essai Premium de 30 jours sans carte bancaire."
      >
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          {trialCta("landing-final-trial", "w-full sm:w-auto")}
          {loginCta("landing-final-login", "w-full sm:w-auto")}
        </div>
      </FinalCtaSection>
    </div>
  );
}

/**
 * AccessGate — Access Control Frontend V2
 * ========================================
 * Conditionally renders children based on the user's subscription tier and/or
 * a named feature flag from the backend access_control module.
 *
 * Replaces the `withSubscription` HOC pattern with a declarative component
 * that is easier to test and compose.
 *
 * Usage examples:
 *
 *   // Require any premium access (trial OR premium)
 *   <AccessGate>
 *     <PremiumContent />
 *   </AccessGate>
 *
 *   // Require a specific backend feature flag
 *   <AccessGate feature="training_plan">
 *     <TrainingPlan />
 *   </AccessGate>
 *
 *   // Custom fallback instead of the default Paywall
 *   <AccessGate feature="race_predictions" fallback={<UpgradeBanner />}>
 *     <RacePredictions />
 *   </AccessGate>
 *
 *   // Require a specific minimum tier
 *   <AccessGate minTier="premium">
 *     <PremiumOnlyContent />
 *   </AccessGate>
 *
 * Security contract:
 *   The gate is display-only. The backend enforces access on every API call.
 *   Never rely solely on this component for access control.
 */

import { Loader2 } from "lucide-react";
import Paywall from "@/components/Paywall";
import { useAccessTier } from "@/hooks/useAccessTier";

const TIER_ORDER = { free: 0, trial: 1, premium: 2 };

/**
 * @param {object}        props
 * @param {React.ReactNode} props.children   - Content to render when access is granted
 * @param {string}        [props.feature]    - Backend feature flag that must be true
 * @param {"trial"|"premium"} [props.minTier] - Minimum tier required (default: "trial")
 * @param {React.ReactNode} [props.fallback] - What to show when access is denied
 *                                            (default: <Paywall />)
 * @param {React.ReactNode} [props.loadingNode] - What to show while loading
 */
export default function AccessGate({
  children,
  feature,
  minTier = "trial",
  fallback,
  loadingNode,
}) {
  const { tier, hasPremiumAccess, hasFeature, loading } = useAccessTier();

  if (loading) {
    return loadingNode ?? (
      <div className="p-4 flex justify-center text-muted-foreground" data-testid="access-gate-loading">
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );
  }

  // Tier check: user must be at or above minTier
  const tierOk = (TIER_ORDER[tier] ?? 0) >= (TIER_ORDER[minTier] ?? 1);

  // Feature check: if a specific feature is requested, it must be true
  const featureOk = feature ? hasFeature(feature) : hasPremiumAccess;

  if (!tierOk || !featureOk) {
    return fallback ?? <Paywall />;
  }

  return children;
}

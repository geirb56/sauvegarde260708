/**
 * useAccessTier — Access Control Frontend V2
 * ===========================================
 * Thin wrapper around SubscriptionContext that exposes exactly the three
 * canonical tiers (FREE / TRIAL / PREMIUM) defined by the backend
 * access_control module.
 *
 * Usage:
 *   const { isFree, isTrial, isPremium, hasFeature, tier } = useAccessTier();
 *
 * All access decisions are still enforced server-side. This hook is
 * display-only: use it to show/hide UI elements or redirect to the Paywall.
 */

import { useSubscription } from "@/context/SubscriptionContext";

/**
 * @typedef {Object} AccessTier
 * @property {"free"|"trial"|"premium"} tier        - Current plan tier
 * @property {boolean} isFree                        - True when plan === "free"
 * @property {boolean} isTrial                       - True when plan === "trial"
 * @property {boolean} isPremium                     - True when plan === "premium"
 * @property {boolean} hasPremiumAccess              - True for trial OR premium
 * @property {number|null} trialDaysRemaining        - Days left in trial (null if not trial)
 * @property {(feature: string) => boolean} hasFeature - Feature-flag check
 * @property {Object} featureAccess                  - Raw feature_access map from backend
 * @property {boolean} loading                       - True while fetching from backend
 */

/**
 * Returns the current user's access tier and feature flags.
 * Fail-closed: returns free/no-access when loading or on error.
 *
 * @returns {AccessTier}
 */
export function useAccessTier() {
  const {
    plan,
    isFree,
    isTrial,
    isPremium,
    hasPremiumAccess,
    trialDaysRemaining,
    hasFeature,
    featureAccess,
    loading,
  } = useSubscription();

  return {
    tier: plan,
    isFree,
    isTrial,
    isPremium,
    hasPremiumAccess,
    trialDaysRemaining,
    hasFeature,
    featureAccess,
    loading,
  };
}

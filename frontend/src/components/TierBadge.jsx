/**
 * TierBadge — Access Control Frontend V2
 * ========================================
 * Displays a visual badge representing the user's current subscription tier:
 * FREE | TRIAL | PREMIUM.
 *
 * Usage:
 *   <TierBadge />                     — auto-detects tier from context
 *   <TierBadge tier="trial" />        — explicit tier (for Storybook/tests)
 *   <TierBadge showDaysRemaining />   — also shows trial countdown
 */

import { Crown, Sparkles, Lock } from "lucide-react";
import { useAccessTier } from "@/hooks/useAccessTier";

// ── Tier configuration ──────────────────────────────────────────────────────

const TIER_CONFIG = {
  free: {
    label: "FREE",
    Icon: Lock,
    className:
      "bg-slate-700/60 text-slate-300 border border-slate-600/50",
    iconClass: "text-slate-400",
  },
  trial: {
    label: "TRIAL",
    Icon: Sparkles,
    className:
      "bg-blue-900/40 text-blue-300 border border-blue-500/40",
    iconClass: "text-blue-400",
  },
  premium: {
    label: "PREMIUM",
    Icon: Crown,
    className:
      "bg-amber-900/30 text-amber-300 border border-amber-500/40",
    iconClass: "text-amber-400",
  },
};

// ── Component ───────────────────────────────────────────────────────────────

/**
 * @param {object}  props
 * @param {"free"|"trial"|"premium"} [props.tier]  - Override tier (default: from context)
 * @param {boolean} [props.showDaysRemaining]       - Show trial countdown label
 * @param {string}  [props.className]              - Extra class names
 */
export default function TierBadge({ tier: tierProp, showDaysRemaining = false, className = "" }) {
  const { tier: ctxTier, trialDaysRemaining, loading } = useAccessTier();

  const tier = tierProp ?? ctxTier;

  if (loading && !tierProp) return null;

  const config = TIER_CONFIG[tier] ?? TIER_CONFIG.free;
  const { label, Icon, className: baseClass, iconClass } = config;

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold tracking-wide ${baseClass} ${className}`}
      data-testid="tier-badge"
      data-tier={tier}
    >
      <Icon className={`w-3 h-3 ${iconClass}`} />
      {label}
      {showDaysRemaining && tier === "trial" && trialDaysRemaining != null && (
        <span className="ml-1 font-normal opacity-80">
          · {trialDaysRemaining}j
        </span>
      )}
    </span>
  );
}

import { Badge } from "@/components/ui/badge";
import { Crown, Sparkles } from "lucide-react";

export const PremiumBadge = ({ isPremium, messagesRemaining, maxMessages = 30 }) => {
  if (!isPremium) return null;

  const percentage = (messagesRemaining / maxMessages) * 100;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-amber-500" />
        <span className="font-mono text-xs">
          {messagesRemaining}/{maxMessages}
        </span>
      </div>
      <div className="w-full h-2 bg-muted rounded-sm overflow-hidden">
        <div 
          className="h-full bg-gradient-to-r from-amber-500 to-orange-500 transition-all"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};

export const PremiumUpgradeCard = ({ t, onUpgrade }) => {
  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        <li className="flex items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="w-3 h-3 text-amber-500 flex-shrink-0" />
          {t("premium.feature1")}
        </li>
        <li className="flex items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="w-3 h-3 text-amber-500 flex-shrink-0" />
          {t("premium.feature2")}
        </li>
        <li className="flex items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="w-3 h-3 text-amber-500 flex-shrink-0" />
          {t("premium.feature3")}
        </li>
      </ul>
      <button
        onClick={onUpgrade}
        className="w-full bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white rounded-sm uppercase font-bold tracking-wider text-xs h-9 flex items-center justify-center gap-2 px-4 transition-all"
      >
        <Crown className="w-4 h-4" />
        {t("premium.subscribe")}
      </button>
    </div>
  );
};

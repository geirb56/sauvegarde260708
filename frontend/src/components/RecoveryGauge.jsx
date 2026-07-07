import { Card, CardContent } from "@/components/ui/card";
import { BatteryFull, BatteryMedium, BatteryLow } from "lucide-react";

const getRecoveryStyles = (status) => {
  const styles = {
    ready: {
      color: "text-emerald-400",
      bgColor: "bg-emerald-400/10",
      icon: BatteryFull
    },
    moderate: {
      color: "text-amber-400",
      bgColor: "bg-amber-400/10",
      icon: BatteryMedium
    },
    low: {
      color: "text-red-400",
      bgColor: "bg-red-400/10",
      icon: BatteryLow
    }
  };
  return styles[status] || styles.low;
};

export const RecoveryGauge = ({ score, status, phrase }) => {
  const styles = getRecoveryStyles(status);
  const Icon = styles.icon;
  const circumference = 2 * Math.PI * 36;
  const progress = (score / 100) * circumference;

  const statusLabel = {
    ready: "Ready",
    moderate: "Moderate",
    low: "Low"
  }[status];

  return (
    <Card className={`border-border ${styles.bgColor} animate-in`}>
      <CardContent className="p-4 md:p-5">
        <div className="flex items-center gap-4">
          <div className="relative w-20 h-20 flex-shrink-0">
            <svg className="w-20 h-20 transform -rotate-90" viewBox="0 0 80 80">
              <circle
                cx="40"
                cy="40"
                r="36"
                fill="none"
                stroke="currentColor"
                strokeWidth="6"
                className="text-muted/30"
              />
              <circle
                cx="40"
                cy="40"
                r="36"
                fill="none"
                stroke="currentColor"
                strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={circumference - progress}
                className={`${styles.color} transition-all duration-1000`}
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className={`font-mono text-xl font-bold ${styles.color}`}>
                {score}
              </span>
            </div>
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <Icon className={`w-4 h-4 ${styles.color} flex-shrink-0`} />
              <span className={`font-mono text-xs uppercase tracking-wider font-semibold ${styles.color}`}>
                {statusLabel}
              </span>
            </div>
            <p className="font-mono text-xs text-muted-foreground leading-relaxed">
              {phrase}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

import { Card, CardContent } from "@/components/ui/card";
import { ANIMATION_DELAYS } from "@/utils/constants";

export const MetricCard = ({ 
  icon: Icon, 
  label, 
  value, 
  unit,
  animationDelay = ANIMATION_DELAYS.xs,
  className = "",
  onClick = null
}) => (
  <Card 
    className={`metric-card bg-card border-border animate-in cursor-pointer ${className}`} 
    style={{ animationDelay }}
    onClick={onClick}
  >
    <CardContent className="p-4 md:p-5">
      {Icon && <Icon className="w-4 h-4 text-muted-foreground mx-auto mb-2 flex-shrink-0" />}
      <p className="font-heading text-2xl md:text-3xl font-bold mb-1 text-center">
        {value}
      </p>
      <p className="font-mono text-[9px] uppercase text-muted-foreground text-center">
        {unit}
      </p>
      {label && <p className="font-mono text-xs text-muted-foreground mt-2 text-center">{label}</p>}
    </CardContent>
  </Card>
);

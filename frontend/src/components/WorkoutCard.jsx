import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { ChevronRight } from "lucide-react";
import { getWorkoutIcon, formatDuration, formatDate } from "@/utils/workoutHelpers";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";

export const WorkoutCard = ({ 
  workout, 
  dateLocale, 
  t, 
  index = 0,
  path = "/workout"
}) => {
  const { unitSystem } = useUnitSystem();
  const Icon = getWorkoutIcon(workout.type);
  const typeLabel = t(`workoutTypes.${workout.type}`) || workout.type;
  const dateStr = formatDate(workout.date, dateLocale);

  return (
    <Link
      to={`${path}/${workout.id}`}
      data-testid={`workout-card-${workout.id}`}
      className="block animate-in"
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <Card className="metric-card bg-card border-border hover:border-primary/30 transition-all duration-200">
        <CardContent className="p-3 md:p-4">
          <div className="flex items-center gap-3 md:gap-4">
            <div className="flex-shrink-0 w-8 h-8 md:w-10 md:h-10 flex items-center justify-center bg-muted border border-border rounded-sm">
              <Icon className="w-4 h-4 md:w-5 md:h-5 text-muted-foreground" />
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className="workout-type-badge text-[9px] md:text-[10px]">
                  {typeLabel}
                </span>
                <span className="font-mono text-[9px] md:text-[10px] text-muted-foreground">
                  {dateStr}
                </span>
              </div>
              <p className="font-mono text-xs md:text-sm font-medium truncate">
                {workout.name}
              </p>
            </div>

            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="text-right">
                <p className="font-mono text-xs md:text-sm font-medium">
                  {formatDistance(workout.distance_km || 0, { unitSystem })}
                </p>
                <p className="font-mono text-[9px] md:text-[10px] text-muted-foreground">
                  {formatDuration(workout.duration_minutes)}
                </p>
              </div>
              <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
};

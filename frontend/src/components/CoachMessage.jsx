import { Card, CardContent } from "@/components/ui/card";
import { Activity } from "lucide-react";

export const UserMessage = ({ content, workoutId, lang, t, index }) => (
  <div 
    className="text-right animate-in"
    style={{ animationDelay: `${index * 50}ms` }}
  >
    <div className="inline-block text-left max-w-[90%] md:max-w-[70%]">
      <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
        {t("coach.you")}
      </p>
      <Card className="bg-muted border-border animate-scale-in">
        <CardContent className="p-3 md:p-4">
          <p className="font-mono text-sm leading-relaxed whitespace-pre-wrap break-words">
            {content}
          </p>
          {workoutId && (
            <div className="mt-3 flex items-center gap-1.5 text-primary pt-3 border-t border-border/50">
              <Activity className="w-3 h-3 flex-shrink-0" />
              <span className="font-mono text-[9px] uppercase tracking-wider">
                {t("coachExtended.workoutAnalyzed")}
              </span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  </div>
);

export const AssistantMessage = ({ content, isLoading, lang, t, index }) => (
  <div 
    className="text-left animate-in"
    style={{ animationDelay: `${index * 50}ms` }}
  >
    <p className="font-mono text-[10px] uppercase tracking-widest text-primary mb-2">
      CardioCoach
    </p>
    <div className="coach-message bg-card/50 border-l-2 border-primary pl-4 py-3 rounded-sm">
      {isLoading ? (
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-primary rounded-full animate-bounce" />
          <span className="font-mono text-xs text-muted-foreground">
            {t("coachExtended.thinking")}
          </span>
        </div>
      ) : (
        <p className="font-mono text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground">
          {content}
        </p>
      )}
    </div>
  </div>
);

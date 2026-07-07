import { Card, CardContent } from "@/components/ui/card";
import { Sparkles, Target, AlertTriangle } from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";

export const RAGSummary = ({ rag }) => {
  const { t } = useLanguage();
  if (!rag?.rag_summary) return null;

  return (
    <Card className="bg-card border-border mb-5 animate-in" style={{ animationDelay: "100ms" }}>
      <CardContent className="p-4 md:p-5">
        <div className="flex items-center gap-2 mb-3">
          <Sparkles className="w-4 h-4 text-amber-400 flex-shrink-0" />
          <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
            {t("ragSummary.personalizedAnalysis")}
          </p>
        </div>

        <p className="font-mono text-xs text-muted-foreground leading-relaxed whitespace-pre-line mb-4">
          {rag.rag_summary.split('\n').slice(0, 4).join('\n')}
        </p>

        {(rag.points_forts?.length > 0 || rag.points_ameliorer?.length > 0) && (
          <div className="pt-4 border-t border-border flex flex-wrap gap-2">
            {rag.points_forts?.slice(0, 2).map((point, i) => (
              <span key={`fort-${i}`} className="inline-flex items-center gap-1 px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded-sm">
                <Target className="w-3 h-3 flex-shrink-0" />
                <span className="font-mono text-[10px]">{point}</span>
              </span>
            ))}
            {rag.points_ameliorer?.slice(0, 1).map((point, i) => (
              <span key={`ameliorer-${i}`} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-500/10 text-amber-400 rounded-sm">
                <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                <span className="font-mono text-[10px]">{point}</span>
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

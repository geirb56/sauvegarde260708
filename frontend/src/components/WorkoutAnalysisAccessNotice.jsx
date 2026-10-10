import { Link } from "react-router-dom";

export default function WorkoutAnalysisAccessNotice({ t }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-card/30 p-3 text-sm" data-testid="analysis-upgrade-notice">
      <p className="text-muted-foreground">{t("workoutDetailExtended.analysisPremiumRequired")}</p>
      <Link to="/subscription" className="min-h-11 content-center text-primary underline underline-offset-4">
        {t("workoutDetailExtended.unlockAnalysis")}
      </Link>
    </div>
  );
}

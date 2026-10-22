export default function WorkoutCoachPending({ t }) {
  return <p role="status" data-testid="coach-pending" className="text-sm text-muted-foreground">
    {t("workoutNarrative.pending")}
  </p>;
}

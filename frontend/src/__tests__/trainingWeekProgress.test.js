import { computeTrainingWeekProgress } from "../lib/trainingWeekProgress";

describe("computeTrainingWeekProgress served-week denominators", () => {
  test("uses served week planned_km instead of weekly target when reduced", () => {
    const progress = computeTrainingWeekProgress({
      weekly_target: { target_basis: "distance", target_km: 20, session_count: 4 },
      week: {
        planned_km: 5,
        session_count: 1,
        sessions: [
          { workout_type: "easy", actual: { activity_id: "a1", distance_km: 2.5 } },
        ],
        unmatched_actuals: [],
      },
    });

    expect(progress.planned_value).toBe(5);
    expect(progress.planned_session_count).toBe(1);
    expect(progress.progress_percent).toBe(50);
  });

  test("preserves a real served zero instead of falling back to weekly target", () => {
    const progress = computeTrainingWeekProgress({
      weekly_target: { target_basis: "distance", target_km: 20, session_count: 4 },
      week: {
        planned_km: 0,
        session_count: 0,
        sessions: [],
        unmatched_actuals: [],
      },
    });

    expect(progress.planned_value).toBe(0);
    expect(progress.planned_session_count).toBe(0);
    expect(progress.progress_state).toBe("unavailable");
    expect(progress.progress_percent).toBeNull();
  });

  test("uses served duration denominator for reduced duration weeks", () => {
    const progress = computeTrainingWeekProgress({
      weekly_target: { target_basis: "duration", target_duration_minutes: 180, session_count: 4 },
      week: {
        planned_duration_minutes: 45,
        session_count: 1,
        sessions: [
          { workout_type: "easy", actual: { activity_id: "a1", duration_minutes: 15 } },
        ],
        unmatched_actuals: [],
      },
    });

    expect(progress.planned_value).toBe(45);
    expect(progress.planned_session_count).toBe(1);
    expect(progress.progress_percent).toBe(33);
  });

  test("keeps existing normal-week behavior when served plan totals are absent", () => {
    const progress = computeTrainingWeekProgress({
      weekly_target: { target_basis: "distance", target_km: 20, session_count: 4 },
      week: {
        sessions: [
          { workout_type: "easy", actual: { activity_id: "a1", distance_km: 5 } },
          { workout_type: "race", actual: { activity_id: "r1", distance_km: 10 } },
        ],
        unmatched_actuals: [{ activity_id: "u1", distance_km: 3 }],
      },
    });

    expect(progress.planned_value).toBe(20);
    expect(progress.planned_session_count).toBe(4);
    expect(progress.completed_planned_value).toBe(5);
    expect(progress.completed_session_count).toBe(1);
    expect(progress.unmatched_value).toBe(3);
  });
});

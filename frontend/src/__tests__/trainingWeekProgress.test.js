import { computeTrainingWeekProgress } from "../lib/trainingWeekProgress";

describe("computeTrainingWeekProgress served-week denominators", () => {
  test.each(["distance", "duration"])("never replaces an unknown effective %s aggregate with a live target", (targetBasis) => {
    const progress = computeTrainingWeekProgress({
      weekly_target: { target_basis: targetBasis, target_km: 9.3, target_duration_minutes: 90 },
      week: {
        planned_km: null,
        planned_duration_minutes: null,
        sessions: [
          { execution_status: "prescription_unavailable" },
          { workout_type: "easy", distance_km: 5.6, duration_minutes: 30 },
        ],
      },
    });

    expect(progress.planned_value).toBeNull();
    expect(progress.progress_state).toBe("unavailable");
    expect(progress.progress_percent).toBeNull();
  });

  test("uses the effective snapshot plus future total even when the live target is 9.3", () => {
    const progress = computeTrainingWeekProgress({
      weekly_target: { target_basis: "distance", target_km: 9.3, session_count: 2 },
      week: {
        planned_km: 18.3,
        session_count: 2,
        sessions: [
          { workout_type: "easy", distance_km: 12.7 },
          { workout_type: "easy", distance_km: 5.6 },
        ],
      },
    });
    expect(progress.planned_value).toBeCloseTo(12.7 + 5.6);
  });

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

  test("keeps absent effective totals unknown while counting only published training sessions", () => {
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

    expect(progress.planned_value).toBeNull();
    expect(progress.planned_session_count).toBe(1);
    expect(progress.completed_planned_value).toBe(5);
    expect(progress.completed_session_count).toBe(1);
    expect(progress.unmatched_value).toBe(3);
  });

  test("preserves an explicitly unknown effective session count", () => {
    const progress = computeTrainingWeekProgress({
      weekly_target: { target_basis: "distance", target_km: 9.3, session_count: 3 },
      week: { planned_km: null, session_count: null, sessions: [] },
    });
    expect(progress.planned_session_count).toBeNull();
  });
});

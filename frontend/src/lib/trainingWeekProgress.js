const isKnownNumber = (value) => typeof value === "number" && Number.isFinite(value);

const getSessionType = (session) => session?.workout_type || session?.session_type || session?.type || null;

const isRestSessionType = (value) => {
  const type = (typeof value === "string" ? value : "").trim().toLowerCase();
  return type === "rest" || type.includes("repos");
};

const isTrainingSessionType = (value) => {
  const type = (typeof value === "string" ? value : "").trim().toLowerCase();
  return type !== "" && !isRestSessionType(type) && type !== "race";
};

const hasAttributedActivity = (actual) => Boolean(actual && actual.activity_id != null && actual.activity_id !== "");

export const aggregateKnownMetric = (rows, field) => {
  const list = Array.isArray(rows) ? rows : [];
  if (list.length === 0) {
    return { state: "empty", value: 0 };
  }
  let sum = 0;
  let hasUnknown = false;
  for (const row of list) {
    const value = row?.[field];
    if (isKnownNumber(value)) {
      sum += value;
    } else {
      hasUnknown = true;
    }
  }
  return hasUnknown ? { state: "partial", value: null } : { state: "complete", value: sum };
};

export function computeTrainingWeekProgress(trainingWeekV2) {
  const weeklyTarget = trainingWeekV2?.weekly_target || null;
  const week = trainingWeekV2?.week || {};
  const sessions = Array.isArray(week.sessions) ? week.sessions : [];
  const unmatched = Array.isArray(week.unmatched_actuals) ? week.unmatched_actuals : [];

  if (!weeklyTarget) {
    return null;
  }

  const targetBasis = weeklyTarget.target_basis;
  const metricField = targetBasis === "duration" ? "duration_minutes" : "distance_km";
  const plannedValue = targetBasis === "duration"
    ? weeklyTarget.target_duration_minutes
    : weeklyTarget.target_km;

  const matchedActuals = sessions
    .filter((session) => isTrainingSessionType(getSessionType(session)))
    .map((session) => session?.actual)
    .filter((actual) => hasAttributedActivity(actual));
  const completed = aggregateKnownMetric(matchedActuals, metricField);
  const unmatchedCompleted = aggregateKnownMetric(unmatched, metricField);

  const fallbackPlannedSessionCount = sessions.filter((session) => isTrainingSessionType(getSessionType(session))).length;

  let progressState = "unavailable";
  let progressPercent = null;
  if (isKnownNumber(plannedValue) && plannedValue > 0) {
    if (completed.state === "empty") {
      progressState = "empty";
      progressPercent = 0;
    } else if (completed.state === "complete") {
      progressState = "complete";
      progressPercent = Math.max(0, Math.min(100, Math.round((completed.value / plannedValue) * 100)));
    } else if (completed.state === "partial") {
      progressState = "partial";
      progressPercent = null;
    }
  }

  return {
    target_basis: targetBasis,
    planned_value: plannedValue,
    completed_planned_value: completed.value,
    completed_state: completed.state,
    unmatched_value: unmatchedCompleted.value,
    unmatched_state: unmatchedCompleted.state,
    completed_session_count: matchedActuals.length,
    planned_session_count: weeklyTarget.session_count ?? fallbackPlannedSessionCount,
    progress_state: progressState,
    progress_percent: progressPercent,
  };
}

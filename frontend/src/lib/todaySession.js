export function getCanonicalTodaySession(todayData) {
  return todayData?.served_prescription
    ?? todayData?.adapted_prescription
    ?? todayData?.adaptive_session
    ?? todayData?.planned_session
    ?? todayData?.original_prescription
    ?? null;
}

export function getTodayCardState(todayData, t) {
  const session = getCanonicalTodaySession(todayData);
  if (session) {
    return { kind: "session", session };
  }

  const message = typeof todayData?.message === "string" && todayData.message.trim()
    ? todayData.message
    : null;

  if (todayData?.status === "no_session") {
    return {
      kind: "no_session",
      title: t("dashboard.todayNoSessionTitle"),
      subtitle: message || t("dashboard.todayNoSessionSubtitle"),
    };
  }

  if (todayData?.status === "error") {
    return {
      kind: "error",
      title: t("dashboard.todayErrorTitle"),
      subtitle: message || t("dashboard.todayErrorSubtitle"),
    };
  }

  return {
    kind: "unavailable",
    title: t("dashboard.todayUnavailableTitle"),
    subtitle: message || t("dashboard.todayUnavailableSubtitle"),
  };
}

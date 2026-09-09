import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { CalendarDays, ChevronDown, ChevronUp, Gauge, MapPin } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import Paywall from "@/components/Paywall";
import StructuredWorkoutView, {
  getPrimaryStructuredPace,
} from "@/components/training/StructuredWorkoutView";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { API_BASE_URL } from "@/config";
import { aggregateKnownMetric, computeTrainingWeekProgress } from "@/lib/trainingWeekProgress";
import { formatDistance, formatPace } from "@/utils/units";

const API = API_BASE_URL;
const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const DAY_INDEX = {
  sunday: 0,
  monday: 1,
  tuesday: 2,
  wednesday: 3,
  thursday: 4,
  friday: 5,
  saturday: 6,
};

const isKnownNumber = (value) => typeof value === "number" && Number.isFinite(value);

const normalizeGoalType = (goalType) => {
  if (!goalType || typeof goalType !== "string") return null;
  const normalized = goalType.trim().toLowerCase();
  if (normalized === "half_marathon" || normalized === "semi_marathon") return "semi";
  return normalized;
};

const getTranslatedValue = (t, path, fallbackKey = "trainingV2.notAvailable") => {
  const translated = t(path);
  return translated === path ? t(fallbackKey) : translated;
};

const getSessionType = (session) => session?.workout_type || session?.session_type || session?.type || null;

const getStructuredWorkoutTypeKey = (structured) => {
  if (!structured || typeof structured !== "object") return null;
  if (structured.workout_type === "quality" && typeof structured.quality_kind === "string") {
    return structured.quality_kind;
  }
  return structured.workout_type || null;
};

const getDisplayableStructured = (session) => {
  if (!session || typeof session !== "object") return null;
  if (
    session.structured_status === "historical_unavailable"
    || session.structured_status === "prescription_unavailable"
  ) {
    return null;
  }
  return session.structured && typeof session.structured === "object" ? session.structured : null;
};

const getPrescriptionText = (session) => {
  if (!session || typeof session !== "object") return null;
  return session.prescription || session.description || session.details || session.label || session.name || null;
};

/**
 * PR232A/C231 — Maps the real `/training/v2/week` contract
 * (matching_status + adherence_status from training_v2.performed_workout)
 * to a UI-only status key. Never fabricates DONE/MISSED: everything mirrors
 * the backend's factual PR230 execution state. No "past day => done"
 * fallback — an unresolved session stays unresolved (null).
 *
 * Mapping:
 *   execution_status === "prescription_unavailable"            -> unavailable
 *   workout_type === "rest"                                   -> rest
 *   matching_status planned    (+ not_applicable)              -> planned
 *   matching_status matched    + completed_as_planned          -> done
 *   matching_status matched    + completed_modified            -> modified
 *   matching_status matched    + completed_unverified          -> unverified
 *   matching_status missed     (+ missed)                      -> missed
 *   matching_status ambiguous  (+ ambiguous)                   -> ambiguous
 *   anything else / unresolved                                 -> null
 */
const getSessionStatusKey = (session) => {
  if (!session || typeof session !== "object") return null;

  // C231 (round 2, item 3) — a past day whose real historical prescription
  // was never frozen/served is neutral: never Done/Missed/Modified, never a
  // fabricated distance/duration. Checked BEFORE the rest check since
  // workout_type is itself None/unreliable for this state (see backend
  // training_v2.week_execution.EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE).
  if (session.execution_status === "prescription_unavailable") return "unavailable";

  if (session.workout_type === "rest") return "rest";

  const matching = typeof session.matching_status === "string" ? session.matching_status.toLowerCase() : null;
  const adherence = typeof session.adherence_status === "string" ? session.adherence_status.toLowerCase() : null;

  if (matching === "planned") return "planned";
  if (matching === "missed") return "missed";
  if (matching === "ambiguous") return "ambiguous";
  if (matching === "matched") {
    if (adherence === "completed_as_planned") return "done";
    if (adherence === "completed_modified") return "modified";
    if (adherence === "completed_unverified") return "unverified";
    // C231 — item 5 BLOCKER FIX: unknown/null/invalid adherence must never
    // be fabricated into "done". Surface it as unresolved instead.
    return "unverified";
  }
  return null;
};

// C233 (blocker #1) — actual.activity_id (WeekV2ActualResponse, both on a
// matched session and on unmatched_actuals) is the raw Garmin external_id.
// But GET /workout/:id reads db.workouts.id, which the fan-out worker always
// builds as f"garmin-{external_id}" (backend/garmin/service.py:544,
// activity_to_workout). Linking to `/workout/${external_id}` is therefore a
// dead link. No new backend contract is introduced here — this mirrors an
// EXISTING, stable backend id-construction convention.
const buildWorkoutDetailPath = (activityId) => {
  if (activityId == null || activityId === "") return null;
  return `/workout/garmin-${activityId}`;
};

// PR233 — the only real, non-fabricated identifier for "view analysis" is
// the matched Garmin activity id (PR230 boundary). WeekV2SessionResponse has
// no workout_id/session_id field — inventing one would create a dead link.
const getSessionDetailRoute = (session) => buildWorkoutDetailPath(session?.actual?.activity_id);

const parseIsoDateUTC = (isoDate) => {
  if (typeof isoDate !== "string") return null;
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return null;
  return new Date(Date.UTC(year, month - 1, day));
};

const formatDate = (value, locale) => {
  const parsed = parseIsoDateUTC(value);
  if (!parsed) return typeof value === "string" ? value : null;
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
};

// C233 (blocker #4) — real day + real date on each week card, e.g.
// "Wednesday · 9 Sep". The weekday name is already locale-aware
// (trainingPlanDays.*); the date comes ONLY from the backend's own
// session.planned_date — never reconstructed from the browser clock. No
// date suffix is shown when planned_date is unavailable (never fabricated).
const formatShortDate = (isoDate, locale) => {
  const parsed = parseIsoDateUTC(isoDate);
  if (!parsed) return null;
  // Day-first "9 Sep" style consistently across locales (rather than
  // Intl's locale-default month/day order, which would render "Sep 9" for
  // en-US) — only the month name itself is locale-translated.
  const monthName = new Intl.DateTimeFormat(locale, { month: "short", timeZone: "UTC" }).format(parsed);
  return `${parsed.getUTCDate()} ${monthName}`;
};

const formatDayHeading = (t, day, plannedDate, locale) => {
  const weekday = t(`trainingPlanDays.${day}`);
  const shortDate = formatShortDate(plannedDate, locale);
  return shortDate ? `${weekday} · ${shortDate}` : weekday;
};

// PR233 — replaces all occurrences of each {token}, unlike String.replace
// (which only replaces the first match).
const formatTemplate = (template, values) =>
  Object.entries(values).reduce(
    (result, [token, value]) => result.split(`{${token}}`).join(String(value)),
    template
  );

// C233 (blocker #3) — pure calendar math on an ISO 'YYYY-MM-DD' string only:
// never reads the browser clock/timezone. Date.UTC + getUTCDay is
// deterministic for a given calendar date regardless of where the browser
// runs.
const weekdayKeyFromIsoDate = (isoDate) => {
  const parsed = parseIsoDateUTC(isoDate);
  if (!parsed) return null;
  const utcDay = parsed.getUTCDay();
  return Object.keys(DAY_INDEX).find((key) => DAY_INDEX[key] === utcDay) || null;
};

// C233 (blocker #3) — the ONLY authority for "which day is Today" is the
// backend's own weekData.reference_date (never `new Date()`). Prefer the
// session whose real planned_date exactly equals reference_date (exact
// match survives any gap/reorder in the sessions array); fall back to the
// deterministic weekday of reference_date itself when no planned_date lines
// up (e.g. a day missing from the payload). Returns null (no badge at all)
// when reference_date itself is unavailable — never guesses from the
// client's clock/timezone.
const resolveTodayDayKey = (weekData) => {
  const referenceDate = weekData?.reference_date;
  if (typeof referenceDate !== "string") return null;
  const sessions = Array.isArray(weekData?.week?.sessions) ? weekData.week.sessions : [];
  const exact = sessions.find((session) => session?.planned_date === referenceDate);
  if (exact && typeof exact.day === "string") return exact.day.toLowerCase();
  return weekdayKeyFromIsoDate(referenceDate);
};

const getSessionPaceOrZone = (session) => {
  if (!session || typeof session !== "object") return null;
  const pace = session.pace_target || session.pace || session.pace_range || session.target_pace || session.pace_str;
  if (pace && typeof pace === "string") return pace;
  const zone = session.target_zone || session.zone || session.hr_zone || session.intensity_zone;
  if (zone && typeof zone === "string") return zone;
  return null;
};

// C233 (blocker #2) — mirrors backend RUNTIME_TYPE_TO_WORKOUT_TYPE
// (backend/training_v2/daily_runtime_helpers.py) verbatim. This is the
// REAL, stable mapping the backend itself uses between /training/today's
// runtime `type` vocabulary and the domain `workout_type` vocabulary used
// everywhere else (Week, i18n keys) — not a frontend invention.
const RUNTIME_TYPE_TO_WORKOUT_TYPE = {
  rest: "rest",
  recovery: "recovery",
  endurance: "easy",
  tempo: "steady",
  threshold: "quality",
  long_run: "long_easy",
};

const TODAY_ZERO_DURATION_SENTINEL = "0min";

// C233 (blocker #2) — /training/today's `duration` is a string ("Xmin"),
// never a numeric duration_minutes field. "0min" is the canonical runtime
// sentinel for "no meaningful duration" (rest / no-duration sessions) and
// must never be displayed as a real duration.
const getTodayDurationLabel = (session) => {
  const raw = session?.duration;
  if (typeof raw !== "string" || raw === TODAY_ZERO_DURATION_SENTINEL) return null;
  const match = /^(\d+)min$/.exec(raw.trim());
  if (!match) return null;
  const minutes = Number(match[1]);
  return Number.isFinite(minutes) && minutes > 0 ? `${minutes} min` : null;
};

// C233 (blocker #2) — /training/today's `distance_km` uses 0 as the runtime
// sentinel for "no distance" (rest / duration-only sessions); 0 is never a
// real distance and must never be displayed as "0 km".
const getTodayDistanceKm = (session) => {
  const value = session?.distance_km;
  return isKnownNumber(value) && value > 0 ? value : null;
};

// PR233 — shared min/km -> unit-aware formatted pace string conversion.
const minPerKmToFormattedPace = (minPerKm, unitSystem) => {
  if (!isKnownNumber(minPerKm) || minPerKm <= 0) return null;
  return formatPace(minPerKm * 60, { unitSystem });
};

// PR233 — real Garmin pace (min per km, from PR230's own actual boundary),
// reformatted unit-aware. Never invented: null in -> null out.
const formatActualPace = (paceMinPerKm, unitSystem) => minPerKmToFormattedPace(paceMinPerKm, unitSystem);

const formatActualDuration = (durationMinutes) => {
  if (!isKnownNumber(durationMinutes) || durationMinutes < 0) return null;
  const totalSeconds = Math.round(durationMinutes * 60);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds > 0 ? `${minutes}:${String(seconds).padStart(2, "0")}` : `${minutes} min`;
};

// PR233 — /training/v2/paces already exposes a raw min_per_km alongside the
// metric-only pace_str text. Prefer the raw value so imperial mode never
// shows a hardcoded "/km" suffix; pace_str is only a defensive metric fallback.
const formatVdotPace = (paceValue, unitSystem) => {
  if (!paceValue || typeof paceValue !== "object") return null;
  const fromMinPerKm = minPerKmToFormattedPace(paceValue.min_per_km, unitSystem);
  if (fromMinPerKm) return fromMinPerKm;
  if (typeof paceValue.pace_str === "string" && paceValue.pace_str) {
    // Deliberately dropped (not shown, never converted) in imperial mode:
    // pace_str is a metric-only "MM:SS" string with no unit metadata, so it
    // cannot be safely converted to min/mile here. This path only exists as
    // a defensive fallback for payloads older than the min_per_km field
    // (training_paces_to_api_dict always emits both today) — omitting the
    // row is preferred over ever rendering a hardcoded "/km" in imperial.
    return unitSystem === "imperial" ? null : `${paceValue.pace_str} /km`;
  }
  return null;
};

export { aggregateKnownMetric };

function LoadingState() {
  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="training-v2-loading">
      <Skeleton className="h-20" />
      <Skeleton className="h-44" />
      <Skeleton className="h-60" />
      <Skeleton className="h-44" />
    </div>
  );
}

function SessionStatePill({ t, state }) {
  if (!state) return null;

  const labels = {
    done: t("trainingV2.sessionStates.done"),
    planned: t("trainingV2.sessionStates.planned"),
    rest: t("trainingV2.sessionStates.rest"),
    missed: t("trainingV2.sessionStates.missed"),
    modified: t("trainingV2.sessionStates.modified"),
    unverified: t("trainingV2.sessionStates.unverified"),
    ambiguous: t("trainingV2.sessionStates.ambiguous"),
    unavailable: t("trainingV2.sessionStates.unavailable"),
  };

  return (
    <span
      className="text-[10px] uppercase tracking-wide text-muted-foreground"
      data-testid={`session-status-${state}`}
    >
      {labels[state]}
    </span>
  );
}

function AdaptedBadge({ modified, t }) {
  if (modified !== true) return null;
  return <Badge variant="outline" className="text-[10px]" data-testid="session-adapted-badge">{t("trainingV2.adapted")}</Badge>;
}

function WeekSessionRow({ session, day, isToday, unitSystem, t, locale }) {
  const [expanded, setExpanded] = useState(false);
  const workoutType = getSessionType(session);
  const structured = getDisplayableStructured(session);
  const isExplicitRest = workoutType === "rest" || getSessionStatusKey(session) === "rest";
  const statusKey = getSessionStatusKey(session);
  // C231 (round 2, item 3) — a past day whose real historical prescription
  // was never frozen/served: neutral display, no fabricated distance/
  // duration/workout type, no Done/Missed/Modified badge.
  const isUnavailable = statusKey === "unavailable";

  // C231 — no "past day => done" fallback: an unresolved status stays
  // unresolved (null), it is never fabricated from the day's position in
  // the calendar relative to today.
  const timelineState = !session
    ? "absent"
    : (isToday ? "today" : statusKey);

  const stateMarker = timelineState === "done"
    ? "✓"
    : timelineState === "today"
      ? "●"
      : timelineState === "rest"
        ? "—"
        : timelineState === "missed"
          ? "✕"
          : timelineState === "modified"
            ? "△"
            : timelineState === "ambiguous"
              ? "?"
              : "";

  const typeKey = getStructuredWorkoutTypeKey(structured) || workoutType;
  const typeLabel = !session
    ? t("trainingV2.noSessionLabel")
    : isUnavailable
      ? t("trainingV2.sessionStates.unavailable")
      : isExplicitRest
        ? t("trainingV2.restDay")
        : getTranslatedValue(t, `trainingV2.workoutTypes.${typeKey}`, "trainingV2.noSessionType");

  const prescription = getPrescriptionText(session);
  const distance = isKnownNumber(session?.distance_km) ? formatDistance(session.distance_km, { unitSystem }) : null;
  const duration = isKnownNumber(session?.duration_minutes) ? `${session.duration_minutes} min` : null;
  const compactMetric = isUnavailable
    ? ""
    : distance || duration || (isExplicitRest ? t("trainingV2.restDay") : (session ? "" : t("trainingV2.noSessionLabel")));

  // PR233 — no invented pace/structure for "quality" (or any type): only
  // rendered when the backend prescription itself carries it (never true
  // today for WeekV2SessionResponse, which has no pace field at all).
  const prescribedPaceOrZone = getPrimaryStructuredPace(structured, unitSystem)
    || getSessionPaceOrZone(session);
  const structuredSummary = structured
    ? <StructuredWorkoutView structured={structured} unitSystem={unitSystem} t={t} compact />
    : null;

  const actual = session?.actual || null;
  const actualDistance = isKnownNumber(actual?.distance_km) ? formatDistance(actual.distance_km, { unitSystem }) : null;
  const actualDuration = formatActualDuration(actual?.duration_minutes);
  const actualPace = formatActualPace(actual?.pace_min_per_km, unitSystem);
  const analysisRoute = getSessionDetailRoute(session);

  // PR233 — rest days and prescription_unavailable days carry nothing real
  // to expand (no prescription detail, no actual to compare): both stay
  // collapsed/non-interactive rather than exposing an empty detail panel.
  const canExpand = Boolean(session) && !isUnavailable && !isExplicitRest;
  const detailId = `training-v2-day-detail-${day}`;

  return (
    <div
      data-testid={`training-v2-day-${day}`}
      data-day-state={timelineState}
      className={`rounded-md border ${isToday ? "border-primary bg-primary/10" : "border-border bg-card"}`}
    >
      <button
        type="button"
        onClick={() => canExpand && setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={detailId}
        data-testid={`session-detail-toggle-${day}`}
        disabled={!canExpand}
        className={`grid min-h-14 w-full grid-cols-[76px_minmax(0,1fr)_auto] items-center gap-2 px-3 py-3 text-left text-sm ${
          canExpand ? "cursor-pointer hover:brightness-110" : "cursor-default"
        }`}
      >
        <span className="text-xs text-muted-foreground" data-testid={`training-v2-day-label-${day}`}>
          {formatDayHeading(t, day, session?.planned_date, locale)}
        </span>
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <p className="truncate font-medium" data-testid={`training-v2-day-type-${day}`}>{typeLabel}</p>
            <AdaptedBadge modified={session?.session_modified_from_planned} t={t} />
          </div>
          {(compactMetric || prescribedPaceOrZone) && (
            <p className="text-xs text-foreground" data-testid={`training-v2-day-metrics-${day}`}>
              {[compactMetric, prescribedPaceOrZone].filter(Boolean).join(" · ")}
            </p>
          )}
          {structuredSummary}
          {prescription && !isExplicitRest && !isUnavailable && (
            <p className="truncate text-xs text-muted-foreground" data-testid={`training-v2-day-prescription-${day}`}>{prescription}</p>
          )}
        </div>
        <div className="text-right">
          {isToday ? (
            <Badge className="mb-1 text-[10px]" data-testid="today-highlight-badge">{t("trainingV2.todayBadge")}</Badge>
          ) : (
            <span className="block text-xs text-muted-foreground">{stateMarker}</span>
          )}
          {statusKey && <SessionStatePill t={t} state={statusKey} />}
        </div>
      </button>
      {canExpand && (
        <div
          id={detailId}
          data-testid={`training-v2-day-detail-${day}`}
          style={expanded ? undefined : { display: "none" }}
          className="space-y-2 border-t border-border px-2 py-2 text-xs"
        >
          <div>
            <p className="uppercase tracking-wide text-muted-foreground">{t("trainingV2.sessionDetailPrescribed")}</p>
            <p className="text-foreground">{prescription || typeLabel}</p>
            <div className="flex flex-wrap gap-x-3 text-muted-foreground">
              {distance && <span>{distance}</span>}
              {duration && <span>{duration}</span>}
              {prescribedPaceOrZone && <span>{prescribedPaceOrZone}</span>}
            </div>
            {structured && (
             <div className="mt-3">
               <StructuredWorkoutView structured={structured} unitSystem={unitSystem} t={t} />
             </div>
            )}
          </div>
          <div>
            <p className="uppercase tracking-wide text-muted-foreground">{t("trainingV2.sessionDetailActual")}</p>
            {actual ? (
              <>
                <div className="flex flex-wrap gap-x-3 text-foreground">
                  {actualDistance && <span data-testid={`session-actual-distance-${day}`}>{actualDistance}</span>}
                  {actualDuration && <span data-testid={`session-actual-duration-${day}`}>{actualDuration}</span>}
                  {actualPace && <span data-testid={`session-actual-pace-${day}`}>{actualPace}</span>}
                </div>
                {analysisRoute && (
                  <Link
                    to={analysisRoute}
                    data-testid={`session-analysis-link-${day}`}
                    className="text-primary underline"
                  >
                    {t("trainingV2.sessionDetailViewAnalysis")}
                  </Link>
                )}
              </>
            ) : (
              <p className="text-muted-foreground" data-testid={`session-no-actual-${day}`}>{t("trainingV2.sessionDetailNoActual")}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// PR233 — Volume summary: strictly separates plan accomplishment (matched
// Garmin activities attributed to a prescribed session) from extra Garmin
// volume that was never part of the plan (unmatched_actuals). An unmatched
// activity is NEVER counted towards "completed" plan volume.
function WeekVolumeSummary({ t, weekPlan, weeklyTarget, unitSystem }) {
  if (!weekPlan || !weeklyTarget) return null;

  const weekProgress = computeTrainingWeekProgress({
    weekly_target: weeklyTarget,
    week: weekPlan,
  });
  if (!weekProgress) return null;

  const isDistanceBasis = weekProgress.target_basis === "distance";
  const plannedValue = weekProgress.planned_value;
  const plannedLabel = isKnownNumber(plannedValue)
    ? (isDistanceBasis ? formatDistance(plannedValue, { unitSystem }) : `${Math.round(plannedValue)} min`)
    : t("trainingV2.notAvailable");

  // "empty" (0 matched activities) is a real, complete zero and must render
  // as "0 km"/"0 min", not "—". "partial" (at least one matched activity has
  // a missing metric) must never render the sum of the known-only values as
  // if it were the full total — C233's "None != 0" doctrine.
  const completedLabel = weekProgress.completed_state === "partial"
    ? t("trainingV2.incompleteData")
    : (isDistanceBasis
      ? formatDistance(weekProgress.completed_planned_value, { unitSystem })
      : `${Math.round(weekProgress.completed_planned_value)} min`);
  // Extra Garmin volume is only rendered when there is at least one
  // unmatched row this week; a genuinely empty unmatched list keeps the
  // existing "no extra line" behavior (unchanged), but a partial aggregate
  // must show the incomplete-data marker rather than a partial sum.
  const extraLabel = weekProgress.unmatched_state === "empty"
    ? null
    : (weekProgress.unmatched_state === "partial"
      ? t("trainingV2.incompleteData")
      : (isDistanceBasis
        ? formatDistance(weekProgress.unmatched_value, { unitSystem })
        : `${Math.round(weekProgress.unmatched_value)} min`));

  return (
    <div data-testid="training-v2-week-volume" className="space-y-2 border-b border-border pb-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{t("trainingV2.volumeTitle")}</p>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">{t("trainingV2.volumePlanned")}</span>
        <span className="font-semibold" data-testid="week-volume-planned">{plannedLabel}</span>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">{t("trainingV2.volumeCompleted")}</span>
        <span className="font-semibold" data-testid="week-volume-completed">{completedLabel}</span>
      </div>
      <Progress value={weekProgress.progress_percent} data-testid="week-volume-progress" />
      <p className="text-xs text-muted-foreground" data-testid="week-volume-sessions">
        {/* weekly_target.session_count is the canonical prescribed target;
            fallback count is derived from week.sessions when missing. */}
        {formatTemplate(t("trainingV2.volumeSessions"), {
          done: weekProgress.completed_session_count,
          total: weekProgress.planned_session_count ?? 0,
        })}
      </p>
      {extraLabel && (
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm text-muted-foreground">
          <span>{t("trainingV2.volumeExtra")}</span>
          <span data-testid="week-volume-extra">{extraLabel} · {t("trainingV2.volumeExtraNote")}</span>
        </div>
      )}
    </div>
  );
}

// PR233 — real Garmin activities this week that could not be attributed to
// any prescribed session. Rendered in a separate section and NEVER merged
// into a planned session's card.
function UnmatchedActualsSection({ t, unitSystem, unmatchedActuals, locale }) {
  const rows = Array.isArray(unmatchedActuals) ? unmatchedActuals : [];

  return (
    <Card data-testid="training-v2-unmatched">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t("trainingV2.unmatchedTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">{t("trainingV2.unmatchedNote")}</p>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="unmatched-empty-state">{t("trainingV2.unmatchedEmpty")}</p>
        ) : (
          rows.map((row, index) => {
            const distance = isKnownNumber(row?.distance_km) ? formatDistance(row.distance_km, { unitSystem }) : null;
            const duration = isKnownNumber(row?.duration_minutes) ? `${Math.round(row.duration_minutes)} min` : null;
            const pace = formatActualPace(row?.pace_min_per_km, unitSystem);
            const dateLabel = row?.start_time ? formatDate(row.start_time.slice(0, 10), locale) : null;
            const key = row?.activity_id
              ? `${row.activity_id}-${index}`
              : `unmatched-${row?.start_time || "unknown"}-${index}`;
            const analysisRoute = buildWorkoutDetailPath(row?.activity_id);
            return (
              <div
                key={key}
                data-testid="unmatched-activity-row"
                className="rounded-md border border-border bg-card px-2 py-2 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-muted-foreground">{dateLabel || t("trainingV2.notAvailable")}</span>
                  {row?.activity_type && <Badge variant="outline">{row.activity_type}</Badge>}
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-foreground">
                  {distance && <span>{distance}</span>}
                  {duration && <span>{duration}</span>}
                  {pace && <span>{pace}</span>}
                </div>
                {analysisRoute && (
                  <Link to={analysisRoute} className="text-primary underline">
                    {t("trainingV2.sessionDetailViewAnalysis")}
                  </Link>
                )}
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

function FullCycleSection({ t, locale, weeks }) {
  const [open, setOpen] = useState(false);

  return (
    <Card data-testid="training-v2-cycle">
      <CardHeader className="pb-2">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-center justify-between text-left"
          data-testid="cycle-collapsible-trigger"
          aria-expanded={open}
          aria-controls="cycle-collapsible-content"
        >
          <CardTitle className="flex items-center gap-2 text-base">
            <MapPin className="h-4 w-4" />
            {t("trainingV2.fullCycleTitle")}
          </CardTitle>
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </CardHeader>
      <CardContent>
        <div
          id="cycle-collapsible-content"
          data-testid="cycle-collapsible-content"
          style={open ? undefined : { display: "none" }}
          className="space-y-2"
        >
          {weeks.map((week) => {
            const phaseLabel = week.phase
              ? getTranslatedValue(t, `trainingV2.cyclePhases.${week.phase}`)
              : t("trainingV2.notAvailable");
            const target = isKnownNumber(week.weekly_target_km)
              ? `${week.weekly_target_km} km`
              : (isKnownNumber(week.weekly_target_minutes) ? `${week.weekly_target_minutes} min` : null);
            return (
              <div
                key={week.week_number}
                data-testid={`cycle-week-${week.week_number}`}
                className={`grid grid-cols-[auto_1fr_auto] items-center gap-2 rounded-md border px-2 py-2 text-xs ${week.is_current ? "border-primary bg-primary/10" : "border-border bg-card"}`}
              >
                <span className="font-semibold">{t("trainingV2.cycleWeekShort")} {week.week_number}</span>
                <span className="truncate text-muted-foreground">{phaseLabel}</span>
                <span className="text-muted-foreground">{target || (week.start_date && week.end_date ? `${formatDate(week.start_date, locale)}–${formatDate(week.end_date, locale)}` : t("trainingV2.notAvailable"))}</span>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

export default function TrainingPlanV2() {
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading } = useSubscription();
  const { unitSystem } = useUnitSystem();

  const [todayData, setTodayData] = useState(null);
  const [pacesData, setPacesData] = useState(null);
  const [weekData, setWeekData] = useState(null);
  const [cycleData, setCycleData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [pacesOpen, setPacesOpen] = useState(false);

  useEffect(() => {
    if (subLoading || isFree) return;

    let ignore = false;

    const loadData = async () => {
      setLoading(true);
      setHasError(false);
      try {
        const [todayRes, pacesRes, weekRes, cycleRes] = await Promise.all([
          axios.get(`${API}/training/today`).catch(() => ({ data: null })),
          axios.get(`${API}/training/v2/paces`).catch(() => ({ data: null })),
          axios.get(`${API}/training/v2/week`),
          axios.get(`${API}/training/v2/cycle`).catch(() => ({ data: null })),
        ]);

        if (!ignore) {
          setTodayData(todayRes.data);
          setPacesData(pacesRes.data);
          setWeekData(weekRes.data);
          setCycleData(cycleRes.data);
        }
      } catch {
        if (!ignore) setHasError(true);
      } finally {
        if (!ignore) setLoading(false);
      }
    };

    loadData();

    return () => {
      ignore = true;
    };
  }, [isFree, subLoading]);

  const locale = lang === "fr" ? "fr-FR" : lang === "es" ? "es-ES" : "en-US";
  // C233 (blocker #3) — resolveTodayDayKey derives Today exclusively from
  // weekData.reference_date (+ sessions[].planned_date); never the browser
  // clock/timezone.
  const todayKey = resolveTodayDayKey(weekData);

  const orderedSessions = useMemo(() => {
    const sessions = weekData?.week?.sessions ?? [];
    return DAYS.map((day) => sessions.find((session) => session.day === day) ?? null);
  }, [weekData]);

  if (subLoading || (!isFree && (loading || (!weekData && !hasError)))) return <LoadingState />;
  if (isFree) return <Paywall returnPath="/training" />;

  if (hasError || !weekData) {
    return (
      <div className="p-4 md:p-6">
        <Card className="border-border bg-card">
          <CardHeader>
            <CardTitle>{t("trainingV2.planHeader")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{t("trainingV2.loadingError")}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const cycle = cycleData?.cycle;
  const cycleWeeks = Array.isArray(cycleData?.weeks) ? cycleData.weeks : [];
  const currentCycleWeek = cycleWeeks.find((week) => week?.is_current) || null;

  const goalTypeKey = normalizeGoalType(cycleData?.goal?.goal_type || weekData?.goal?.goal_type);
  const goalLabel = goalTypeKey
    ? getTranslatedValue(t, `trainingV2.goalTypes.${goalTypeKey}`, "trainingV2.unknownGoal")
    : t("trainingV2.unknownGoal");

  const isMaintenanceGoal = goalTypeKey === "maintenance";

  const phaseLabel = currentCycleWeek?.phase
    ? getTranslatedValue(t, `trainingV2.cyclePhases.${currentCycleWeek.phase}`)
    : t("trainingV2.notAvailable");

  // C233 (blocker #2) — /training/today's served_prescription (and its
  // sibling keys: adapted_prescription/adaptive_session/planned_session/
  // original_prescription) are ALL the SAME real runtime shape produced by
  // prescription_to_runtime_session() (backend/training_v2/
  // daily_runtime_helpers.py): { day, type, duration, intensity,
  // distance_km, estimated_tss }. There is NO workout_type/duration_minutes/
  // prescription/pace_target/target_zone field on this object — those
  // belonged to a fictitious frontend mock, never to the real backend
  // contract. served_prescription is read FIRST and is the only
  // ALWAYS-authoritative session for today (frozen once, never superseded by
  // a later readiness recompute); the other keys are only a last-resort
  // fallback for the same real shape when no served prescription exists yet
  // (should not normally happen once /training/today has been called at
  // least once for today).
  const todaySession = todayData?.served_prescription
    || todayData?.adapted_prescription
    || todayData?.adaptive_session
    || todayData?.planned_session
    || todayData?.original_prescription;

  // `type` uses the RUNTIME vocabulary (rest/recovery/endurance/tempo/
  // threshold/long_run) — mirrors backend RUNTIME_TYPE_TO_WORKOUT_TYPE
  // (daily_runtime_helpers.py) verbatim so the label uses the SAME domain
  // vocabulary (rest/recovery/easy/steady/quality/long_easy) already shown
  // by Week's workout_type, never a frontend invention.
  const todayWorkoutTypeKey = RUNTIME_TYPE_TO_WORKOUT_TYPE[todaySession?.type] || null;
  const todayStructured = todayData?.structured_prescription || null;
  const resolvedTodayWorkoutTypeKey = getStructuredWorkoutTypeKey(todayStructured)
    || todayWorkoutTypeKey;
  const todayTypeLabel = resolvedTodayWorkoutTypeKey
    ? getTranslatedValue(t, `trainingV2.workoutTypes.${resolvedTodayWorkoutTypeKey}`)
    : t("trainingV2.noSessionType");

  // The runtime parent has no prescription text or pace. Numeric pace and
  // step detail are rendered only from the backend's structured_prescription.
  const todayDurationLabel = isKnownNumber(todayStructured?.total_duration_minutes)
    ? `${todayStructured.total_duration_minutes} min`
    : getTodayDurationLabel(todaySession);
  const todayDistanceKm = isKnownNumber(todayStructured?.total_distance_km)
    ? todayStructured.total_distance_km
    : getTodayDistanceKm(todaySession);
  const todayDistance = todayDistanceKm != null ? formatDistance(todayDistanceKm, { unitSystem }) : null;
  const todayIsExplicitRest = resolvedTodayWorkoutTypeKey === "rest";
  const todayPace = getPrimaryStructuredPace(todayStructured, unitSystem);
  const todayDate = formatDate(todayData?.date || weekData?.reference_date, locale);

  const showRaceCountdown = !isMaintenanceGoal
    && cycle?.days_to_race !== null
    && cycle?.days_to_race !== undefined
    && Number.isFinite(Number(cycle?.days_to_race));

  const progressValue = (cycle?.current_week && cycle?.total_weeks)
    ? Math.max(0, Math.min(100, Math.round((cycle.current_week / cycle.total_weeks) * 100)))
    : 0;

  const confidenceLabel = pacesData?.confidence
    ? getTranslatedValue(t, `trainingV2.pacesConfidence.${String(pacesData.confidence).toLowerCase()}`)
    : t("trainingV2.notAvailable");

  return (
    <div className="space-y-4 p-4 md:p-6" data-testid="training-v2-page">
      <Card data-testid="training-v2-plan-status">
        <CardContent className="space-y-3 pt-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarDays className="h-4 w-4" />
            <span>{t("trainingV2.planHeader")}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2" data-testid="training-v2-header-summary">
            <h1 className="text-xl font-semibold">{goalLabel}</h1>
            <span className="text-muted-foreground">·</span>
            <span className="font-medium" data-testid="header-week-ratio">
              {cycle?.current_week != null && cycle?.total_weeks != null
                ? `${t("trainingV2.week")} ${cycle.current_week}/${cycle.total_weeks}`
                : `${t("trainingV2.week")} ${t("trainingV2.notAvailable")}`}
            </span>
          </div>
          <p className="text-sm text-muted-foreground" data-testid="header-phase-label">{phaseLabel}</p>
          <Progress value={progressValue} />
          {showRaceCountdown && (
            <p className="text-xs text-muted-foreground" data-testid="header-race-countdown">
              {formatTemplate(t("trainingV2.raceCountdownValue"), { days: cycle.days_to_race })}
            </p>
          )}
        </CardContent>
      </Card>

      <Card className="border-primary/40" data-testid="training-v2-today">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-base">{t("trainingV2.todayTitle")}</CardTitle>
            <AdaptedBadge modified={todayData?.session_modified_from_planned} t={t} />
          </div>
          {todayDate && <p className="text-xs uppercase tracking-wide text-muted-foreground">{todayDate}</p>}
        </CardHeader>
        <CardContent className="space-y-2">
          {!todaySession ? (
            <div className="rounded-md border border-border px-3 py-3" data-testid="today-no-session-state">
              <p className="font-medium">{t("trainingV2.noSessionLabel")}</p>
            </div>
          ) : (
            <>
              <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t("trainingV2.sessionType")}</p>
              <p className="text-lg font-semibold" data-testid="today-session-type">{todayIsExplicitRest ? t("trainingV2.restDay") : todayTypeLabel}</p>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {todayDurationLabel && <Badge variant="outline" data-testid="today-session-duration">{todayDurationLabel}</Badge>}
                {todayDistance && <Badge variant="outline" data-testid="today-session-distance">{todayDistance}</Badge>}
               {todayPace && <Badge variant="outline" data-testid="today-session-pace">{todayPace}</Badge>}
              </div>
              {Array.isArray(todayStructured?.steps) && todayStructured.steps.length > 0 && (
                <div className="pt-2">
                  <StructuredWorkoutView structured={todayStructured} unitSystem={unitSystem} t={t} />
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card data-testid="training-v2-week">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t("trainingV2.weekTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <WeekVolumeSummary
            t={t}
            weekPlan={weekData?.week}
            weeklyTarget={weekData?.weekly_target}
            unitSystem={unitSystem}
          />
          <div className="space-y-2" data-testid="week-sessions-list">
            {orderedSessions.map((session, index) => {
              const day = DAYS[index];
              return (
                <WeekSessionRow
                  key={session?.prescription_id || day}
                  session={session}
                  day={day}
                  isToday={day === todayKey}
                  unitSystem={unitSystem}
                  t={t}
                  locale={locale}
                />
              );
            })}
          </div>
        </CardContent>
      </Card>

      <UnmatchedActualsSection
        t={t}
        locale={locale}
        unitSystem={unitSystem}
        unmatchedActuals={weekData?.week?.unmatched_actuals}
      />

      <Card data-testid="training-v2-paces">
        <CardHeader className="pb-2">
          <button
            type="button"
            className="flex w-full items-center justify-between text-left"
            data-testid="paces-collapsible-trigger"
            aria-expanded={pacesOpen}
            aria-controls="paces-collapsible-content"
            onClick={() => setPacesOpen((v) => !v)}
          >
            <CardTitle className="flex items-center gap-2 text-base">
              <Gauge className="h-4 w-4" />
              {t("trainingV2.pacesTitle")}
            </CardTitle>
            {pacesOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        </CardHeader>
        <CardContent>
          <div
            id="paces-collapsible-content"
            className="space-y-3"
            data-testid="paces-collapsible-content"
            style={pacesOpen ? undefined : { display: "none" }}
          >
            <div className="flex items-start justify-between gap-4 text-sm">
              <span className="text-muted-foreground">{t("trainingV2.confidence")}</span>
              <span className="text-right font-medium text-foreground">{confidenceLabel}</span>
            </div>
            {pacesData?.confidence === "INSUFFICIENT" ? (
              <p className="text-sm text-muted-foreground">{t("trainingV2.pacesInsufficient")}</p>
            ) : (
              <div className="space-y-2 text-sm">
                {(() => {
                  const easyLower = formatVdotPace(pacesData?.paces?.easy?.lower, unitSystem);
                  const easyUpper = formatVdotPace(pacesData?.paces?.easy?.upper, unitSystem);
                  return easyLower && easyUpper ? (
                    <div className="flex items-start justify-between gap-4">
                      <span className="text-muted-foreground">{t("trainingV2.paceEasy")}</span>
                      <span className="text-right font-medium">{`${easyLower} - ${easyUpper}`}</span>
                    </div>
                  ) : null;
                })()}
                {(() => {
                  const marathon = formatVdotPace(pacesData?.paces?.marathon, unitSystem);
                  return marathon ? (
                    <div className="flex items-start justify-between gap-4">
                      <span className="text-muted-foreground">{t("trainingV2.paceMarathon")}</span>
                      <span className="text-right font-medium">{marathon}</span>
                    </div>
                  ) : null;
                })()}
                {(() => {
                  const threshold = formatVdotPace(pacesData?.paces?.threshold, unitSystem);
                  return threshold ? (
                    <div className="flex items-start justify-between gap-4">
                      <span className="text-muted-foreground">{t("trainingV2.paceThreshold")}</span>
                      <span className="text-right font-medium">{threshold}</span>
                    </div>
                  ) : null;
                })()}
                {(() => {
                  const intervalLower = formatVdotPace(pacesData?.paces?.interval?.lower, unitSystem);
                  const intervalUpper = formatVdotPace(pacesData?.paces?.interval?.upper, unitSystem);
                  return intervalLower && intervalUpper ? (
                    <div className="flex items-start justify-between gap-4">
                      <span className="text-muted-foreground">{t("trainingV2.paceInterval")}</span>
                      <span className="text-right font-medium">{`${intervalLower} - ${intervalUpper}`}</span>
                    </div>
                  ) : null;
                })()}
                {(() => {
                  const repetition = formatVdotPace(pacesData?.paces?.repetition, unitSystem);
                  return repetition ? (
                    <div className="flex items-start justify-between gap-4">
                      <span className="text-muted-foreground">{t("trainingV2.paceRepetition")}</span>
                      <span className="text-right font-medium">{repetition}</span>
                    </div>
                  ) : null;
                })()}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <FullCycleSection t={t} locale={locale} weeks={cycleWeeks} />
    </div>
  );
}

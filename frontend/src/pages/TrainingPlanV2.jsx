import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { CalendarDays, ChevronDown, ChevronUp, Gauge, MapPin } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import Paywall from "@/components/Paywall";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { API_BASE_URL } from "@/config";
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

// PR233 — the only real, non-fabricated identifier for "view analysis" is
// the matched Garmin activity id (PR230 boundary). WeekV2SessionResponse has
// no workout_id/session_id field — inventing one would create a dead link.
const getSessionDetailRoute = (session) => {
  const activityId = session?.actual?.activity_id;
  if (activityId != null && activityId !== "") return `/workout/${activityId}`;
  return null;
};

const formatDate = (value, locale) => {
  if (!value || typeof value !== "string") return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
};

// PR233 — replaces all occurrences of each {token}, unlike String.replace
// (which only replaces the first match).
const formatTemplate = (template, values) =>
  Object.entries(values).reduce(
    (result, [token, value]) => result.split(`{${token}}`).join(String(value)),
    template
  );

const getTodayDayKey = () => {
  const day = new Date().getDay();
  return Object.keys(DAY_INDEX).find((key) => DAY_INDEX[key] === day) || "monday";
};

const getSessionPaceOrZone = (session) => {
  if (!session || typeof session !== "object") return null;
  const pace = session.pace_target || session.pace || session.pace_range || session.target_pace || session.pace_str;
  if (pace && typeof pace === "string") return pace;
  const zone = session.target_zone || session.zone || session.hr_zone || session.intensity_zone;
  if (zone && typeof zone === "string") return zone;
  return null;
};

// PR233 — shared min/km -> unit-aware formatted pace string conversion.
const minPerKmToFormattedPace = (minPerKm, unitSystem) => {
  if (!isKnownNumber(minPerKm) || minPerKm <= 0) return null;
  return formatPace(minPerKm * 60, { unitSystem });
};

// PR233 — real Garmin pace (min per km, from PR230's own actual boundary),
// reformatted unit-aware. Never invented: null in -> null out.
const formatActualPace = (paceMinPerKm, unitSystem) => minPerKmToFormattedPace(paceMinPerKm, unitSystem);

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

// PR233 — sums a numeric field across a list of rows, ignoring null/unknown
// values (None != 0: an entirely-empty list yields null, never a fabricated 0).
const sumKnown = (rows, field) => {
  const known = rows.map((row) => row?.[field]).filter(isKnownNumber);
  if (known.length === 0) return null;
  return known.reduce((total, value) => total + value, 0);
};

// Defensive: PR230's WeekV2ActualResponse always has activity_id when the
// row is a real attributed activity; treat a bare object with no id as
// "nothing real to count" rather than fabricating a match.
const sessionHasActivity = (actual) => Boolean(actual && actual.activity_id != null && actual.activity_id !== "");

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

function WeekSessionRow({ session, day, isToday, unitSystem, t }) {
  const [expanded, setExpanded] = useState(false);
  const workoutType = getSessionType(session);
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

  const typeLabel = !session
    ? t("trainingV2.noSessionLabel")
    : isUnavailable
      ? t("trainingV2.sessionStates.unavailable")
      : isExplicitRest
        ? t("trainingV2.restDay")
        : getTranslatedValue(t, `trainingV2.workoutTypes.${workoutType}`, "trainingV2.noSessionType");

  const prescription = getPrescriptionText(session);
  const distance = isKnownNumber(session?.distance_km) ? formatDistance(session.distance_km, { unitSystem }) : null;
  const duration = isKnownNumber(session?.duration_minutes) ? `${session.duration_minutes} min` : null;
  const compactMetric = isUnavailable
    ? ""
    : distance || duration || (isExplicitRest ? t("trainingV2.restDay") : (session ? "" : t("trainingV2.noSessionLabel")));

  // PR233 — no invented pace/structure for "quality" (or any type): only
  // rendered when the backend prescription itself carries it (never true
  // today for WeekV2SessionResponse, which has no pace field at all).
  const prescribedPaceOrZone = getSessionPaceOrZone(session);

  const actual = session?.actual || null;
  const actualDistance = isKnownNumber(actual?.distance_km) ? formatDistance(actual.distance_km, { unitSystem }) : null;
  const actualDuration = isKnownNumber(actual?.duration_minutes) ? `${Math.round(actual.duration_minutes)} min` : null;
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
        className={`grid w-full grid-cols-[56px_minmax(0,1fr)_auto] items-center gap-2 px-2 py-2 text-left text-sm ${
          canExpand ? "cursor-pointer hover:brightness-110" : "cursor-default"
        }`}
      >
        <span className="text-xs text-muted-foreground">{t(`trainingPlanDays.${day}`)}</span>
        <div className="min-w-0">
          <p className="truncate font-medium" data-testid={`training-v2-day-type-${day}`}>{typeLabel}</p>
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
          <p className="text-xs text-muted-foreground">{compactMetric}</p>
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

  const sessions = Array.isArray(weekPlan.sessions) ? weekPlan.sessions : [];
  const unmatched = Array.isArray(weekPlan.unmatched_actuals) ? weekPlan.unmatched_actuals : [];
  const matchedActuals = sessions
    .map((session) => session?.actual)
    .filter((actual) => actual && sessionHasActivity(actual));

  const isDistanceBasis = weeklyTarget.target_basis === "distance";

  const plannedValue = isDistanceBasis ? weekPlan.planned_km : weekPlan.planned_duration_minutes;
  const plannedLabel = isKnownNumber(plannedValue)
    ? (isDistanceBasis ? formatDistance(plannedValue, { unitSystem }) : `${Math.round(plannedValue)} min`)
    : t("trainingV2.notAvailable");

  const completedValue = isDistanceBasis
    ? sumKnown(matchedActuals, "distance_km")
    : sumKnown(matchedActuals, "duration_minutes");
  const completedLabel = isKnownNumber(completedValue)
    ? (isDistanceBasis ? formatDistance(completedValue, { unitSystem }) : `${Math.round(completedValue)} min`)
    : t("trainingV2.notAvailable");

  const extraDistance = sumKnown(unmatched, "distance_km");
  const extraDuration = sumKnown(unmatched, "duration_minutes");
  const extraLabel = isDistanceBasis
    ? (isKnownNumber(extraDistance) ? formatDistance(extraDistance, { unitSystem }) : null)
    : (isKnownNumber(extraDuration) ? `${Math.round(extraDuration)} min` : null);

  const completedSessionCount = matchedActuals.length;

  const progressValue = isKnownNumber(plannedValue) && plannedValue > 0 && isKnownNumber(completedValue)
    ? Math.max(0, Math.min(100, Math.round((completedValue / plannedValue) * 100)))
    : 0;

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
      <Progress value={progressValue} data-testid="week-volume-progress" />
      <p className="text-xs text-muted-foreground" data-testid="week-volume-sessions">
        {/* weekly_target.session_count is the recommended/prescribed target
            (canonical source); week.session_count (sum of non-rest sessions
            actually scheduled this week) is only a defensive fallback for
            the rare case the target is unset. */}
        {formatTemplate(t("trainingV2.volumeSessions"), {
          done: completedSessionCount,
          total: weeklyTarget.session_count ?? weekPlan.session_count ?? 0,
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
            const analysisRoute = row?.activity_id != null && row.activity_id !== "" ? `/workout/${row.activity_id}` : null;
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
  const todayKey = getTodayDayKey();

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

  // C231 (round 2, item 1 BLOCKER FIX) — the served_prescription is the
  // canonical, ALWAYS-authoritative session for today (frozen once, never
  // superseded by a later readiness recompute). adaptation_applied is
  // informative only and must NEVER decide which session gets displayed:
  // planned_session is only used as a last-resort fallback when no served
  // prescription exists yet (should not normally happen once /training/today
  // has been called at least once for today).
  const todaySession = todayData?.served_prescription
    || todayData?.adapted_prescription
    || todayData?.adaptive_session
    || todayData?.planned_session
    || todayData?.original_prescription;

  const todayType = getSessionType(todaySession);
  const todayTypeLabel = todayType
    ? getTranslatedValue(t, `trainingV2.workoutTypes.${todayType}`)
    : t("trainingV2.noSessionType");

  const todayPrescription = getPrescriptionText(todaySession)
    || getPrescriptionText(todayData?.adapted_prescription)
    || getPrescriptionText(todayData?.original_prescription)
    || null;

  const todayPaceOrZone = getSessionPaceOrZone(todaySession);
  const todayDuration = isKnownNumber(todaySession?.duration_minutes) ? `${todaySession.duration_minutes} min` : null;
  const todayDistance = isKnownNumber(todaySession?.distance_km) ? formatDistance(todaySession.distance_km, { unitSystem }) : null;
  const todayIsExplicitRest = todayType === "rest" || getSessionStatusKey(todaySession) === "rest";

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
              {t("trainingV2.raceCountdownValue").replace("{days}", String(cycle.days_to_race))}
            </p>
          )}
        </CardContent>
      </Card>

      <Card className="border-primary/40" data-testid="training-v2-today">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t("trainingV2.todayTitle")}</CardTitle>
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
              {todayPrescription && !todayIsExplicitRest && (
                <p className="text-base" data-testid="today-session-prescription">{todayPrescription}</p>
              )}
              {todayPaceOrZone && !todayIsExplicitRest && (
                <p className="text-sm text-muted-foreground" data-testid="today-session-pace-zone">{todayPaceOrZone}</p>
              )}
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {todayDuration && <Badge variant="outline" data-testid="today-session-duration">{todayDuration}</Badge>}
                {todayDistance && <Badge variant="outline" data-testid="today-session-distance">{todayDistance}</Badge>}
              </div>
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
                  key={day}
                  session={session}
                  day={day}
                  isToday={day === todayKey}
                  unitSystem={unitSystem}
                  t={t}
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

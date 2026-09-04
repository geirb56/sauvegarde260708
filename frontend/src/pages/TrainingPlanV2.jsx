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
import { formatDistance, formatPace, convertPace } from "@/utils/units";

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

// PR232 — Training UX V3: semantic status color/dot classes.
// green = completed as prescribed, orange = modified/attention,
// red = missed, blue/neutral = planned, gray = unavailable/unknown.
const STATUS_DOT_CLASSES = {
  done: "bg-emerald-400",
  modified: "bg-amber-400",
  missed: "bg-rose-400",
  planned: "bg-sky-400",
  unverified: "bg-slate-400",
  ambiguous: "bg-slate-400",
  unavailable: "bg-slate-500",
  rest: "bg-slate-600",
};

const STATUS_TEXT_CLASSES = {
  done: "text-emerald-400",
  modified: "text-amber-400",
  missed: "text-rose-400",
  planned: "text-sky-400",
  unverified: "text-slate-400",
  ambiguous: "text-slate-400",
  unavailable: "text-slate-500",
  rest: "text-slate-500",
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

const getSessionDetailRoute = (session) => {
  if (!session || typeof session !== "object") return null;

  const workoutId = session.actual?.activity_id ?? session.workout_id ?? session.workoutId;
  if (workoutId != null && workoutId !== "") return `/workout/${workoutId}`;

  const sessionId = session.session_id ?? session.sessionId ?? session.id;
  if (sessionId != null && sessionId !== "") return `/sessions/${sessionId}`;

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

// ---------------------------------------------------------------------------
// PR232 — pace formatting. The API always transports metric min/km; the
// user's unit system (metric/imperial) is only applied here, at display
// time — never on the wire. Imperial NEVER shows a "/km" suffix (#8).
// ---------------------------------------------------------------------------

const formatPaceValueLabel = (minPerKm, unitSystem) => {
  if (!isKnownNumber(minPerKm)) return null;
  return formatPace(minPerKm * 60, { unitSystem });
};

// Numeric-only "M:SS" portion of a pace value, with no unit suffix — used to
// build a range label ("6:15–6:40 /km") without string-matching the suffix
// out of formatPace's output (which would be fragile to format changes).
const formatPaceNumericOnly = (minPerKm, unitSystem) => {
  if (!isKnownNumber(minPerKm)) return null;
  const convertedSeconds = convertPace(minPerKm * 60, unitSystem);
  if (!convertedSeconds) return null;
  const mins = Math.floor(convertedSeconds / 60);
  const secs = Math.round(convertedSeconds - mins * 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
};

const formatPaceRangeLabel = (paceRange, unitSystem) => {
  if (!paceRange || !isKnownNumber(paceRange.lower_min_per_km) || !isKnownNumber(paceRange.upper_min_per_km)) {
    return null;
  }
  const upperLabel = formatPaceValueLabel(paceRange.upper_min_per_km, unitSystem);
  if (!upperLabel) return null;
  if (Math.abs(paceRange.lower_min_per_km - paceRange.upper_min_per_km) < 0.001) {
    return upperLabel;
  }
  const lowerNumeric = formatPaceNumericOnly(paceRange.lower_min_per_km, unitSystem);
  if (!lowerNumeric) return upperLabel;
  return `${lowerNumeric}–${upperLabel}`;
};

function LoadingState() {
  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="training-v2-loading">
      <Skeleton className="h-20" />
      <Skeleton className="h-24" />
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
      className={`inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide ${STATUS_TEXT_CLASSES[state] || "text-muted-foreground"}`}
      data-testid={`session-status-${state}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT_CLASSES[state] || "bg-muted-foreground"}`} aria-hidden="true" />
      {labels[state]}
    </span>
  );
}

// PR232 — compact prescribed-vs-real comparison. Only rendered once a real
// Garmin activity has actually been matched to this session (never for
// planned/missed/unavailable/ambiguous). unmatched_actuals are never
// attached here — they surface separately, unlinked.
function ActualComparison({ session, t, unitSystem }) {
  const actual = session.actual;
  if (!actual) return null;

  const actualDistance = isKnownNumber(actual.distance_km) ? formatDistance(actual.distance_km, { unitSystem }) : null;
  const actualDuration = isKnownNumber(actual.duration_minutes) ? `${Math.round(actual.duration_minutes)} min` : null;
  const actualPace = isKnownNumber(actual.pace_min_per_km) ? formatPaceValueLabel(actual.pace_min_per_km, unitSystem) : null;

  return (
    <div className="rounded-md border border-border bg-muted/30 p-2 text-sm" data-testid="session-actual-comparison">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("trainingV2.actualTitle")}</p>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {actualDistance && (
          <span data-testid="session-actual-distance">
            <span className="text-muted-foreground">{t("trainingV2.actualDistance")}: </span>{actualDistance}
          </span>
        )}
        {actualDuration && (
          <span data-testid="session-actual-duration">
            <span className="text-muted-foreground">{t("trainingV2.actualDuration")}: </span>{actualDuration}
          </span>
        )}
        {actualPace && (
          <span data-testid="session-actual-pace">
            <span className="text-muted-foreground">{t("trainingV2.actualPace")}: </span>{actualPace}
          </span>
        )}
      </div>
    </div>
  );
}

function SessionCard({ session, day, isToday, unitSystem, t, locale, open, onToggle }) {
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

  const typeLabel = !session
    ? t("trainingV2.noSessionLabel")
    : isUnavailable
      ? t("trainingV2.sessionStates.unavailable")
      : isExplicitRest
        ? t("trainingV2.restDay")
        : getTranslatedValue(t, `trainingV2.workoutTypes.${workoutType}`, "trainingV2.noSessionType");

  const distance = isKnownNumber(session?.distance_km) ? formatDistance(session.distance_km, { unitSystem }) : null;
  const duration = isKnownNumber(session?.duration_minutes) ? `${session.duration_minutes} min` : null;
  const primaryPace = !isUnavailable && !isExplicitRest ? formatPaceRangeLabel(session?.primary_pace, unitSystem) : null;
  const compactMetric = isUnavailable
    ? ""
    : distance || duration || (isExplicitRest ? t("trainingV2.restDay") : (session ? "" : t("trainingV2.noSessionLabel")));

  const detailRoute = getSessionDetailRoute(session);
  const hasExpandableDetail = Boolean(session) && !isExplicitRest && (Boolean(session?.actual) || Boolean(detailRoute));
  const dateLabel = session?.planned_date ? formatDate(session.planned_date, locale) : null;

  return (
    <div
      data-testid={`training-v2-day-${day}`}
      data-day-state={timelineState}
      className={`rounded-lg border px-3 py-2.5 text-sm transition-colors ${
        isToday ? "border-primary bg-primary/10" : "border-border bg-card"
      }`}
    >
      <button
        type="button"
        onClick={hasExpandableDetail ? onToggle : undefined}
        data-testid={`training-v2-day-toggle-${day}`}
        aria-expanded={hasExpandableDetail ? open : undefined}
        aria-controls={hasExpandableDetail ? `training-v2-day-details-${day}` : undefined}
        className={`grid w-full grid-cols-[64px_minmax(0,1fr)_auto] items-center gap-2 text-left ${hasExpandableDetail ? "cursor-pointer" : "cursor-default"}`}
      >
        <span className="text-xs text-muted-foreground">
          {t(`trainingPlanDays.${day}`)}
          {dateLabel && <span className="block text-[10px] text-muted-foreground/70">{dateLabel}</span>}
        </span>
        <div className="min-w-0">
          <p className="truncate font-medium" data-testid={`training-v2-day-type-${day}`}>{typeLabel}</p>
          {primaryPace && (
            <p className="truncate text-xs text-muted-foreground" data-testid={`training-v2-day-pace-${day}`}>{primaryPace}</p>
          )}
        </div>
        <div className="text-right">
          {isToday && (
            <Badge className="mb-1 text-[10px]" data-testid="today-highlight-badge">{t("trainingV2.todayBadge")}</Badge>
          )}
          <p className="text-xs font-medium text-foreground">{compactMetric}</p>
          {statusKey && <SessionStatePill t={t} state={statusKey} />}
        </div>
      </button>

      {hasExpandableDetail && open && (
        <div className="mt-3 space-y-3 border-t border-border pt-3" data-testid={`training-v2-day-details-${day}`}>
          <ActualComparison session={session} t={t} unitSystem={unitSystem} />
          {detailRoute && (
            <Link to={detailRoute} className="inline-block text-xs font-medium text-primary hover:underline" data-testid={`session-detail-link-${day}`}>
              {t("trainingV2.showDetails")}
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

// PR232 — real Garmin activities this week that could not be attributed to
// any prescribed session. Shown as extra activities, never artificially
// attached to a session card.
function UnmatchedActualsSection({ unmatchedActuals, t, locale, unitSystem }) {
  if (!Array.isArray(unmatchedActuals) || unmatchedActuals.length === 0) return null;

  return (
    <Card data-testid="training-v2-unmatched-actuals">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{t("trainingV2.unmatchedActualsTitle")}</CardTitle>
        <p className="text-xs text-muted-foreground">{t("trainingV2.unmatchedActualsHint")}</p>
      </CardHeader>
      <CardContent className="space-y-2">
        {unmatchedActuals.map((actual, index) => {
          const distance = isKnownNumber(actual.distance_km) ? formatDistance(actual.distance_km, { unitSystem }) : null;
          const duration = isKnownNumber(actual.duration_minutes) ? `${Math.round(actual.duration_minutes)} min` : null;
          const dateLabel = actual.start_time ? formatDate(actual.start_time.slice(0, 10), locale) : null;
          return (
            <div
              key={actual.activity_id || index}
              className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-2 py-2 text-sm"
              data-testid={`unmatched-actual-${index}`}
            >
              <span className="text-xs text-muted-foreground">{dateLabel || t("trainingV2.notAvailable")}</span>
              <span className="flex-1 truncate px-2">{actual.activity_type || t("trainingV2.notAvailable")}</span>
              <span className="text-xs font-medium">{[distance, duration].filter(Boolean).join(" · ") || t("trainingV2.notAvailable")}</span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// PR232 — "Vue Semaine" synthesis: understand the week WITHOUT opening any
// session card. Planned volume, session count and a factual (never
// fabricated) completion progress built solely from real `actual` data.
function WeekSummaryCard({ weekPlan, orderedSessions, todayKey, t, unitSystem }) {
  const plannedKm = isKnownNumber(weekPlan?.planned_km) ? formatDistance(weekPlan.planned_km, { unitSystem }) : null;
  const plannedDuration = isKnownNumber(weekPlan?.planned_duration_minutes) ? `${weekPlan.planned_duration_minutes} min` : null;
  const sessionCount = isKnownNumber(weekPlan?.session_count) ? weekPlan.session_count : null;

  const completedKmSum = orderedSessions.reduce((total, session) => {
    const actualKm = session?.actual?.distance_km;
    return isKnownNumber(actualKm) ? total + actualKm : total;
  }, 0);
  const completedSessionCount = orderedSessions.filter((session) => session?.actual != null).length;
  const progressPct = isKnownNumber(weekPlan?.planned_km) && weekPlan.planned_km > 0
    ? Math.max(0, Math.min(100, Math.round((completedKmSum / weekPlan.planned_km) * 100)))
    : 0;

  return (
    <Card data-testid="training-v2-week-summary">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{t("trainingV2.weekSummaryTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {(plannedKm || plannedDuration) && (
            <span data-testid="week-summary-planned">
              <span className="text-muted-foreground">{t("trainingV2.weekPlannedVolume")}: </span>
              <span className="font-semibold">{plannedKm || plannedDuration}</span>
            </span>
          )}
          {sessionCount != null && (
            <span data-testid="week-summary-session-count">
              <span className="text-muted-foreground">{t("trainingV2.sessionCount")}: </span>
              <span className="font-semibold">{completedSessionCount}/{sessionCount}</span>
            </span>
          )}
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
            <span>{t("trainingV2.weekProgressLabel")}</span>
            <span data-testid="week-summary-progress-value">{formatDistance(completedKmSum, { unitSystem })}</span>
          </div>
          <Progress value={progressPct} data-testid="week-summary-progress-bar" />
        </div>
        <div className="flex items-center justify-between gap-1" data-testid="week-summary-day-dots">
          {DAYS.map((day, index) => {
            const session = orderedSessions[index];
            const statusKey = getSessionStatusKey(session);
            const isToday = day === todayKey;
            const dotClass = isToday
              ? "bg-primary"
              : STATUS_DOT_CLASSES[statusKey] || "bg-slate-700";
            return (
              <div key={day} className="flex flex-col items-center gap-1" data-testid={`week-summary-dot-${day}`}>
                <span className={`h-2.5 w-2.5 rounded-full ${dotClass}`} aria-hidden="true" />
                <span className="text-[9px] uppercase text-muted-foreground">{t(`trainingPlanDays.${day}`).slice(0, 1)}</span>
              </div>
            );
          })}
        </div>
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
  const [openDays, setOpenDays] = useState({});

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

  const toggleDay = (day) => setOpenDays((prev) => ({ ...prev, [day]: !prev[day] }));

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

  const unmatchedActuals = Array.isArray(weekData?.week?.unmatched_actuals) ? weekData.week.unmatched_actuals : [];

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

      <WeekSummaryCard
        weekPlan={weekData?.week}
        orderedSessions={orderedSessions}
        todayKey={todayKey}
        t={t}
        unitSystem={unitSystem}
      />

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
        <CardContent className="space-y-2" data-testid="week-sessions-list">
          {orderedSessions.map((session, index) => {
            const day = DAYS[index];
            return (
              <SessionCard
                key={day}
                session={session}
                day={day}
                isToday={day === todayKey}
                unitSystem={unitSystem}
                t={t}
                locale={locale}
                open={Boolean(openDays[day])}
                onToggle={() => toggleDay(day)}
              />
            );
          })}
        </CardContent>
      </Card>

      <UnmatchedActualsSection unmatchedActuals={unmatchedActuals} t={t} locale={locale} unitSystem={unitSystem} />

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
                {pacesData?.paces?.easy?.lower?.min_per_km != null && pacesData?.paces?.easy?.upper?.min_per_km != null && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceEasy")}</span>
                    <span className="text-right font-medium">
                      {formatPaceRangeLabel(
                        { lower_min_per_km: pacesData.paces.easy.lower.min_per_km, upper_min_per_km: pacesData.paces.easy.upper.min_per_km },
                        unitSystem,
                      )}
                    </span>
                  </div>
                )}
                {pacesData?.paces?.marathon?.min_per_km != null && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceMarathon")}</span>
                    <span className="text-right font-medium">{formatPaceValueLabel(pacesData.paces.marathon.min_per_km, unitSystem)}</span>
                  </div>
                )}
                {pacesData?.paces?.threshold?.min_per_km != null && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceThreshold")}</span>
                    <span className="text-right font-medium">{formatPaceValueLabel(pacesData.paces.threshold.min_per_km, unitSystem)}</span>
                  </div>
                )}
                {pacesData?.paces?.interval?.lower?.min_per_km != null && pacesData?.paces?.interval?.upper?.min_per_km != null && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceInterval")}</span>
                    <span className="text-right font-medium">
                      {formatPaceRangeLabel(
                        { lower_min_per_km: pacesData.paces.interval.lower.min_per_km, upper_min_per_km: pacesData.paces.interval.upper.min_per_km },
                        unitSystem,
                      )}
                    </span>
                  </div>
                )}
                {pacesData?.paces?.repetition?.min_per_km != null && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceRepetition")}</span>
                    <span className="text-right font-medium">{formatPaceValueLabel(pacesData.paces.repetition.min_per_km, unitSystem)}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <FullCycleSection t={t} locale={locale} weeks={cycleWeeks} />
    </div>
  );
}

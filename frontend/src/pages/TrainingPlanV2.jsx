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
import { formatDistance } from "@/utils/units";

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
    return "done";
  }
  return null;
};

const getSessionDetailRoute = (session) => {
  if (!session || typeof session !== "object") return null;

  const workoutId = session.workout_id ?? session.workoutId;
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
  const workoutType = getSessionType(session);
  const isExplicitRest = workoutType === "rest" || getSessionStatusKey(session) === "rest";
  const statusKey = getSessionStatusKey(session);

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
    : isExplicitRest
      ? t("trainingV2.restDay")
      : getTranslatedValue(t, `trainingV2.workoutTypes.${workoutType}`, "trainingV2.noSessionType");

  const prescription = getPrescriptionText(session);
  const distance = isKnownNumber(session?.distance_km) ? formatDistance(session.distance_km, { unitSystem }) : null;
  const duration = isKnownNumber(session?.duration_minutes) ? `${session.duration_minutes} min` : null;
  const compactMetric = distance || duration || (isExplicitRest ? t("trainingV2.restDay") : (session ? "" : t("trainingV2.noSessionLabel")));

  const detailRoute = getSessionDetailRoute(session);
  const Wrapper = detailRoute ? Link : "div";

  return (
    <Wrapper
      {...(detailRoute ? { to: detailRoute } : {})}
      data-testid={`training-v2-day-${day}`}
      data-day-state={timelineState}
      className={`grid grid-cols-[56px_minmax(0,1fr)_auto] items-center gap-2 rounded-md border px-2 py-2 text-sm ${
        isToday ? "border-primary bg-primary/10" : "border-border bg-card"
      } ${detailRoute ? "hover:brightness-110" : ""}`}
    >
      <span className="text-xs text-muted-foreground">{t(`trainingPlanDays.${day}`)}</span>
      <div className="min-w-0">
        <p className="truncate font-medium" data-testid={`training-v2-day-type-${day}`}>{typeLabel}</p>
        {prescription && !isExplicitRest && (
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
    </Wrapper>
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

  const todaySession = todayData?.adaptation_applied
    ? todayData?.adapted_prescription || todayData?.adaptive_session || todayData?.planned_session
    : todayData?.planned_session || todayData?.original_prescription;

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
        <CardContent className="space-y-2" data-testid="week-sessions-list">
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
        </CardContent>
      </Card>

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
                {pacesData?.paces?.easy?.lower?.pace_str && pacesData?.paces?.easy?.upper?.pace_str && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceEasy")}</span>
                    <span className="text-right font-medium">{`${pacesData.paces.easy.lower.pace_str} - ${pacesData.paces.easy.upper.pace_str} /km`}</span>
                  </div>
                )}
                {pacesData?.paces?.marathon?.pace_str && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceMarathon")}</span>
                    <span className="text-right font-medium">{`${pacesData.paces.marathon.pace_str} /km`}</span>
                  </div>
                )}
                {pacesData?.paces?.threshold?.pace_str && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceThreshold")}</span>
                    <span className="text-right font-medium">{`${pacesData.paces.threshold.pace_str} /km`}</span>
                  </div>
                )}
                {pacesData?.paces?.interval?.lower?.pace_str && pacesData?.paces?.interval?.upper?.pace_str && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceInterval")}</span>
                    <span className="text-right font-medium">{`${pacesData.paces.interval.lower.pace_str} - ${pacesData.paces.interval.upper.pace_str} /km`}</span>
                  </div>
                )}
                {pacesData?.paces?.repetition?.pace_str && (
                  <div className="flex items-start justify-between gap-4">
                    <span className="text-muted-foreground">{t("trainingV2.paceRepetition")}</span>
                    <span className="text-right font-medium">{`${pacesData.paces.repetition.pace_str} /km`}</span>
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

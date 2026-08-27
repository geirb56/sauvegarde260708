import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { CalendarDays, ChevronDown, ChevronUp, Gauge, MapPin, Sparkles } from "lucide-react";

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

const WORKOUT_STYLES = {
  rest: "border-indigo-500/40 bg-indigo-500/10 text-indigo-100",
  recovery: "border-cyan-500/40 bg-cyan-500/10 text-cyan-100",
  easy: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100",
  steady: "border-amber-500/40 bg-amber-500/10 text-amber-100",
  quality: "border-orange-500/40 bg-orange-500/10 text-orange-100",
  long_easy: "border-blue-500/40 bg-blue-500/10 text-blue-100",
};

const DAY_INDEX = {
  sunday: 0,
  monday: 1,
  tuesday: 2,
  wednesday: 3,
  thursday: 4,
  friday: 5,
  saturday: 6,
};
const DEFAULT_VISIBLE_WEEKS = 4;

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

const getSessionStatusKey = (session) => {
  if (!session || typeof session !== "object") return null;
  const raw = session.status || session.state || session.completion_status || session.execution_status;
  if (!raw || typeof raw !== "string") return null;

  const normalized = raw.toLowerCase();
  if (normalized === "done" || normalized === "completed") return "done";
  if (normalized === "planned" || normalized === "upcoming") return "planned";
  if (normalized === "rest") return "rest";
  if (normalized === "missed" || normalized === "skipped") return "missed";
  return null;
};

const getSessionDetailRoute = (session) => {
  if (!session || typeof session !== "object") return null;

  const workoutId = session.workout_id ?? session.workoutId;
  if (workoutId != null && workoutId !== "") {
    return `/workout/${workoutId}`;
  }

  const sessionId = session.session_id ?? session.sessionId ?? session.id;
  if (sessionId != null && sessionId !== "") {
    return `/sessions/${sessionId}`;
  }

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

function DetailRow({ label, value, valueClassName = "" }) {
  return (
    <div className="flex items-start justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={`text-right font-medium text-foreground ${valueClassName}`}>{value}</span>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="training-v2-loading">
      <Skeleton className="h-10 w-48" />
      <Skeleton className="h-44" />
      <Skeleton className="h-60" />
      <Skeleton className="h-44" />
    </div>
  );
}

function SessionStatusBadge({ t, status }) {
  if (!status) return null;

  const styles = {
    done: "bg-emerald-500/15 text-emerald-200 border-emerald-400/30",
    planned: "bg-blue-500/15 text-blue-200 border-blue-400/30",
    rest: "bg-indigo-500/15 text-indigo-200 border-indigo-400/30",
    missed: "bg-red-500/15 text-red-200 border-red-400/30",
  };

  return (
    <Badge
      variant="outline"
      className={`text-[10px] uppercase tracking-wider ${styles[status] || "border-border text-foreground"}`}
      data-testid={`session-status-${status}`}
    >
      {t(`trainingV2.sessionStates.${status}`)}
    </Badge>
  );
}

function SessionDayCard({ session, day, isToday, t, unitSystem }) {
  const workoutType = session?.workout_type;
  const isExplicitRest = workoutType === "rest" || getSessionStatusKey(session) === "rest";
  const workoutTypeLabel = session
    ? getTranslatedValue(t, `trainingV2.workoutTypes.${workoutType}`)
    : t("trainingV2.noSessionLabel");

  const metricParts = [];
  if (session && isKnownNumber(session.distance_km)) metricParts.push(formatDistance(session.distance_km, { unitSystem }));
  if (session && isKnownNumber(session.duration_minutes)) metricParts.push(`${session.duration_minutes} min`);
  if (session && session.estimated_tss !== null && session.estimated_tss !== undefined && Number.isFinite(Number(session.estimated_tss))) {
    metricParts.push(`${Number(session.estimated_tss)} TSS`);
  }

  const state = getSessionStatusKey(session)
    || (isExplicitRest ? "rest" : null);

  const detailRoute = getSessionDetailRoute(session);
  const containerClassName = `rounded-xl border p-4 transition-colors ${
    session ? (WORKOUT_STYLES[session.workout_type] ?? "border-border bg-card text-foreground") : "border-border bg-card text-foreground"
  } ${isToday ? "ring-2 ring-primary/70" : ""}`;

  const content = (
    <>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t(`trainingPlanDays.${day}`)}</p>
          <p className="mt-1 text-base font-semibold" data-testid={`training-v2-day-type-${day}`}>{workoutTypeLabel}</p>
        </div>
        <div className="flex items-center gap-2">
          {isToday && (
            <Badge className="text-[10px]" data-testid="today-highlight-badge">
              {t("trainingV2.todayBadge")}
            </Badge>
          )}
          <SessionStatusBadge t={t} status={state} />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        {metricParts.length > 0 ? metricParts.map((part) => (
          <span key={part} className="rounded-full border border-current/20 px-2.5 py-1">{part}</span>
        )) : (
          <span className="rounded-full border border-current/20 px-2.5 py-1">
            {isExplicitRest ? t("trainingV2.restDay") : t("trainingV2.noSessionLabel")}
          </span>
        )}
      </div>
    </>
  );

  if (!detailRoute) {
    return (
      <div className={containerClassName} data-testid={`training-v2-day-${day}`}>
        {content}
      </div>
    );
  }

  return (
    <Link
      to={detailRoute}
      className={`${containerClassName} block hover:brightness-110`}
      data-testid={`training-v2-day-${day}`}
      data-detail-route={detailRoute}
    >
      {content}
    </Link>
  );
}

function FullCycleSection({ t, locale, weeks, openAll, setOpenAll }) {
  const currentWeek = weeks.find((week) => week?.is_current) || null;
  const visibleWeeks = openAll
    ? weeks
    : weeks.filter((week) => {
      if (week.is_current) return true;
      if (!currentWeek) return week.week_number <= DEFAULT_VISIBLE_WEEKS;
      return Math.abs((week.week_number || 0) - (currentWeek.week_number || 0)) <= 2;
    });

  return (
    <Card data-testid="training-v2-cycle">
      <CardHeader className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <MapPin className="h-4 w-4" />
            {t("trainingV2.fullCycleTitle")}
          </CardTitle>
          <button
            type="button"
            onClick={() => setOpenAll((value) => !value)}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground"
            data-testid="cycle-toggle-button"
          >
            {openAll ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            {openAll ? t("trainingV2.collapse") : t("trainingV2.showAll")}
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {visibleWeeks.map((week) => {
          const phaseLabel = week.phase
            ? getTranslatedValue(t, `trainingV2.cyclePhases.${week.phase}`)
            : t("trainingV2.notAvailable");
          return (
            <div
              key={week.week_number}
              data-testid={`cycle-week-${week.week_number}`}
              className={`rounded-lg border p-3 ${week.is_current ? "border-primary bg-primary/10" : "border-border bg-card"}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-medium">
                  {t("trainingV2.cycleWeekLabel")} {week.week_number}
                  {week.is_current && (
                    <span className="ml-2 rounded-full bg-primary px-2 py-0.5 text-xs font-semibold text-primary-foreground" data-testid="cycle-current-badge">
                      {t("trainingV2.cycleCurrentBadge")}
                    </span>
                  )}
                </span>
                <span className="text-muted-foreground">{phaseLabel}</span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {week.start_date && week.end_date
                  ? `${formatDate(week.start_date, locale)} – ${formatDate(week.end_date, locale)}`
                  : t("trainingV2.notAvailable")}
              </div>
            </div>
          );
        })}
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
  const [cycleOpenAll, setCycleOpenAll] = useState(false);

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

  useEffect(() => {
    if (typeof window === "undefined") return;
    setPacesOpen(window.innerWidth >= 768);
  }, []);

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

  const weeklyTargetValue = weekData?.weekly_target?.target_basis === "distance"
    ? (isKnownNumber(weekData?.weekly_target?.target_km) ? formatDistance(weekData.weekly_target.target_km, { unitSystem }) : t("trainingV2.notAvailable"))
    : (isKnownNumber(weekData?.weekly_target?.target_duration_minutes) ? `${weekData.weekly_target.target_duration_minutes} min` : t("trainingV2.notAvailable"));

  const weeklyCompleted = isKnownNumber(weekData?.week?.completed_km)
    ? formatDistance(weekData.week.completed_km, { unitSystem })
    : (isKnownNumber(weekData?.week?.completed_duration_minutes) ? `${weekData.week.completed_duration_minutes} min` : t("trainingV2.notAvailable"));

  const hasAnySessionLink = orderedSessions.some((session) => Boolean(getSessionDetailRoute(session)));

  const progressValue = (cycle?.current_week && cycle?.total_weeks)
    ? Math.max(0, Math.min(100, Math.round((cycle.current_week / cycle.total_weeks) * 100)))
    : 0;

  const confidenceLabel = pacesData?.confidence
    ? getTranslatedValue(t, `trainingV2.pacesConfidence.${String(pacesData.confidence).toLowerCase()}`)
    : t("trainingV2.notAvailable");

  const showRaceCountdown = !isMaintenanceGoal
    && cycle?.days_to_race !== null
    && cycle?.days_to_race !== undefined
    && Number.isFinite(Number(cycle?.days_to_race));

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="training-v2-page">
      <Card data-testid="training-v2-plan-status">
        <CardContent className="pt-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="rounded-xl border border-border bg-card p-3">
              <CalendarDays className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-foreground">{t("trainingV2.planHeader")}</h1>
              <p className="text-sm text-muted-foreground">{t("trainingV2.planSubheader")}</p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <DetailRow label={t("trainingV2.goalLabel")} value={goalLabel} />
            <DetailRow label={t("trainingV2.currentPhase")} value={phaseLabel} />
            {showRaceCountdown && (
              <DetailRow
                label={t("trainingV2.raceCountdownLabel")}
                value={t("trainingV2.raceCountdownValue").replace("{days}", String(cycle.days_to_race))}
              />
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="border-primary/40" data-testid="training-v2-today">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4" />
            {t("trainingV2.todayTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {todayData?.status === "no_session" ? (
            <div className="rounded-lg border border-border bg-card p-3" data-testid="today-rest-state">
              <p className="font-medium">{t("trainingV2.restDay")}</p>
              <p className="text-sm text-muted-foreground">{t("trainingV2.noSessionToday")}</p>
            </div>
          ) : (
            <>
              <DetailRow label={t("trainingV2.sessionType")} value={todayTypeLabel} valueClassName="text-base" />
              <DetailRow
                label={t("trainingV2.sessionPrescription")}
                value={todayPrescription || t("trainingV2.notAvailable")}
                valueClassName="max-w-[70%]"
              />
              {isKnownNumber(todaySession?.duration_minutes) && (
                <DetailRow label={t("trainingV2.sessionDuration")} value={`${todaySession.duration_minutes} min`} />
              )}
              {isKnownNumber(todaySession?.distance_km) && (
                <DetailRow
                  label={t("trainingV2.sessionDistance")}
                  value={formatDistance(todaySession.distance_km, { unitSystem })}
                />
              )}
              {todayData?.adaptation_applied && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" data-testid="today-adapted">
                  <p className="font-medium text-amber-200">{t("trainingV2.adaptationApplied")}</p>
                  {todayData?.adaptation_reason && (
                    <p className="mt-1 text-amber-100/90">{todayData.adaptation_reason}</p>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card data-testid="training-v2-week">
        <CardHeader>
          <CardTitle>{t("trainingV2.weekTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <DetailRow label={t("trainingV2.weekGoal")} value={weeklyTargetValue} />
            <DetailRow label={t("trainingV2.weekCompleted")} value={weeklyCompleted} />
            <DetailRow
              label={t("trainingV2.weekPlannedSessions")}
              value={isKnownNumber(weekData?.weekly_target?.session_count) ? String(weekData.weekly_target.session_count) : t("trainingV2.notAvailable")}
            />
            <DetailRow
              label={t("trainingV2.weekCompletedSessions")}
              value={isKnownNumber(weekData?.week?.completed_session_count) ? String(weekData.week.completed_session_count) : t("trainingV2.notAvailable")}
            />
          </div>

          <div className="space-y-3" data-testid="week-sessions-list">
            {orderedSessions.map((session, index) => {
              const day = DAYS[index];
              return (
                <SessionDayCard
                  key={day}
                  session={session}
                  day={day}
                  isToday={day === todayKey}
                  t={t}
                  unitSystem={unitSystem}
                />
              );
            })}
          </div>

          <p className="text-xs text-muted-foreground" data-testid="session-detail-support">
            {hasAnySessionLink ? t("trainingV2.sessionDetailLinkAvailable") : t("trainingV2.sessionDetailLinkUnavailable")}
          </p>
        </CardContent>
      </Card>

      <Card data-testid="training-v2-cycle-progress">
        <CardHeader>
          <CardTitle>{t("trainingV2.cycleProgressTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{t("trainingV2.cycleWeekProgress")}</span>
            <span className="font-semibold">
              {cycle?.current_week != null && cycle?.total_weeks != null ? `${cycle.current_week} / ${cycle.total_weeks}` : t("trainingV2.notAvailable")}
            </span>
          </div>
          <Progress value={progressValue} />
          <p className="text-sm text-muted-foreground" data-testid="cycle-progress-percent">{progressValue}%</p>
        </CardContent>
      </Card>

      <Card data-testid="training-v2-paces">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gauge className="h-4 w-4" />
            {t("trainingV2.pacesTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div>
            <button
              type="button"
              className="mb-3 flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-sm"
              data-testid="paces-collapsible-trigger"
              aria-expanded={pacesOpen}
              aria-controls="paces-collapsible-content"
              onClick={() => setPacesOpen((v) => !v)}
            >
              <span>{t("trainingV2.pacesSummary")}</span>
              {pacesOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            <div
              id="paces-collapsible-content"
              className="space-y-3"
              data-testid="paces-collapsible-content"
              style={pacesOpen ? undefined : { display: "none" }}
            >
              <DetailRow label={t("trainingV2.confidence")} value={confidenceLabel} />
              {pacesData?.confidence === "INSUFFICIENT" ? (
                <p className="text-sm text-muted-foreground">{t("trainingV2.pacesInsufficient")}</p>
              ) : (
                <div className="space-y-2 text-sm">
                  <DetailRow
                    label={t("trainingV2.paceEasy")}
                    value={pacesData?.paces?.easy?.lower?.pace_str && pacesData?.paces?.easy?.upper?.pace_str
                      ? `${pacesData.paces.easy.lower.pace_str} - ${pacesData.paces.easy.upper.pace_str} /km`
                      : t("trainingV2.notAvailable")}
                  />
                  <DetailRow
                    label={t("trainingV2.paceMarathon")}
                    value={pacesData?.paces?.marathon?.pace_str ? `${pacesData.paces.marathon.pace_str} /km` : t("trainingV2.notAvailable")}
                  />
                  <DetailRow
                    label={t("trainingV2.paceThreshold")}
                    value={pacesData?.paces?.threshold?.pace_str ? `${pacesData.paces.threshold.pace_str} /km` : t("trainingV2.notAvailable")}
                  />
                  <DetailRow
                    label={t("trainingV2.paceInterval")}
                    value={pacesData?.paces?.interval?.lower?.pace_str && pacesData?.paces?.interval?.upper?.pace_str
                      ? `${pacesData.paces.interval.lower.pace_str} - ${pacesData.paces.interval.upper.pace_str} /km`
                      : t("trainingV2.notAvailable")}
                  />
                  <DetailRow
                    label={t("trainingV2.paceRepetition")}
                    value={pacesData?.paces?.repetition?.pace_str ? `${pacesData.paces.repetition.pace_str} /km` : t("trainingV2.notAvailable")}
                  />
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <FullCycleSection
        t={t}
        locale={locale}
        weeks={cycleWeeks}
        openAll={cycleOpenAll}
        setOpenAll={setCycleOpenAll}
      />
    </div>
  );
}

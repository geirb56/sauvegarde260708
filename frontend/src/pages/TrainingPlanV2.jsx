import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { CalendarDays, Gauge, MapPin, Sparkles } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

const isKnownNumber = (value) => typeof value === "number" && Number.isFinite(value);

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

const getTranslatedValue = (t, path, fallbackKey = "trainingV2.notAvailable") => {
  const translated = t(path);
  return translated === path ? t(fallbackKey) : translated;
};

const normalizeGoalType = (goalType) => {
  if (!goalType || typeof goalType !== "string") return null;
  const normalized = goalType.trim().toLowerCase();
  if (normalized === "half_marathon") return "semi";
  if (normalized === "semi_marathon") return "semi";
  return normalized;
};

const getSessionType = (session) => session?.workout_type || session?.session_type || session?.type || null;

const getPrescriptionText = (session) => {
  if (!session || typeof session !== "object") return null;
  return session.prescription || session.description || session.details || session.label || session.name || null;
};

function DetailRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{value}</span>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="training-v2-loading">
      <Skeleton className="h-10 w-48" />
      <div className="space-y-4">
        <Skeleton className="h-36" />
        <Skeleton className="h-36" />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

function CycleWeekRow({ week, t, locale }) {
  const phaseLabel = week.phase
    ? (() => {
        const translated = t(`trainingV2.cyclePhases.${week.phase}`);
        return translated === `trainingV2.cyclePhases.${week.phase}` ? t("trainingV2.notAvailable") : translated;
      })()
    : t("trainingV2.notAvailable");
  return (
    <div
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
        {week.start_date && week.end_date && (
          <span className="text-xs text-muted-foreground">
            {formatDate(week.start_date, locale)} – {formatDate(week.end_date, locale)}
          </span>
        )}
      </div>
    </div>
  );
}

function CycleSection({ cycleData, t, locale }) {
  if (!cycleData) return null;
  const cycle = cycleData?.cycle;
  const goalTypeKey = normalizeGoalType(cycleData?.goal?.goal_type);
  const goalLabel = goalTypeKey
    ? getTranslatedValue(t, `trainingV2.goalTypes.${goalTypeKey}`, "trainingV2.unknownGoal")
    : t("trainingV2.unknownGoal");
  const weeks = Array.isArray(cycleData?.weeks) ? cycleData.weeks : [];
  return (
    <Card data-testid="training-v2-cycle">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MapPin className="h-4 w-4" />
          {t("trainingV2.cycleTitle")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <DetailRow label={t("trainingV2.goalLabel")} value={goalLabel} />
          {cycle?.current_week != null && cycle?.total_weeks != null && (
            <DetailRow label={t("trainingV2.cycleWeekProgress")} value={`${cycle.current_week} / ${cycle.total_weeks}`} />
          )}
          {cycle?.mode && <DetailRow label={t("trainingV2.cycleMode")} value={getTranslatedValue(t, `trainingV2.cycleModes.${cycle.mode}`)} />}
          {cycle?.status && <DetailRow label={t("trainingV2.cycleStatus")} value={getTranslatedValue(t, `trainingV2.cycleStatuses.${cycle.status}`)} />}
          {cycle?.start_date && <DetailRow label={t("trainingV2.cycleStart")} value={formatDate(cycle.start_date, locale) ?? cycle.start_date} />}
          {cycle?.end_date && <DetailRow label={t("trainingV2.cycleEnd")} value={formatDate(cycle.end_date, locale) ?? cycle.end_date} />}
          {cycleData?.goal?.race_date && <DetailRow label={t("trainingV2.raceDate")} value={formatDate(cycleData.goal.race_date, locale) ?? cycleData.goal.race_date} />}
        </div>
        {weeks.length > 0 && (
          <div className="space-y-2 pt-2">
            <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">{t("trainingV2.cycleWeeks")}</p>
            {weeks.map((week) => (
              <CycleWeekRow key={week.week_number} week={week} t={t} locale={locale} />
            ))}
          </div>
        )}
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
            <CardTitle>{t("trainingV2.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{t("trainingV2.loadingError")}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const todaySession = todayData?.adaptation_applied
    ? todayData?.adapted_prescription || todayData?.adaptive_session || todayData?.planned_session
    : todayData?.planned_session || todayData?.original_prescription;
  const todayType = getSessionType(todaySession);
  const todayTypeLabel = todayType
    ? getTranslatedValue(t, `trainingV2.workoutTypes.${todayType}`)
    : t("trainingV2.notAvailable");
  const readinessBand = todayData?.readiness?.band
    ? getTranslatedValue(t, `trainingV2.readinessBands.${String(todayData.readiness.band).toLowerCase()}`)
    : t("trainingV2.notAvailable");
  const confidenceLabel = pacesData?.confidence
    ? getTranslatedValue(t, `trainingV2.pacesConfidence.${String(pacesData.confidence).toLowerCase()}`)
    : t("trainingV2.notAvailable");

  const weeklyTargetValue = weekData?.weekly_target?.target_basis === "distance"
    ? (isKnownNumber(weekData?.weekly_target?.target_km) ? formatDistance(weekData.weekly_target.target_km, { unitSystem }) : t("trainingV2.notAvailable"))
    : (isKnownNumber(weekData?.weekly_target?.target_duration_minutes) ? `${weekData.weekly_target.target_duration_minutes} min` : t("trainingV2.notAvailable"));

  const weeklyCompleted = isKnownNumber(weekData?.week?.completed_km)
    ? formatDistance(weekData.week.completed_km, { unitSystem })
    : (isKnownNumber(weekData?.week?.completed_duration_minutes) ? `${weekData.week.completed_duration_minutes} min` : t("trainingV2.notAvailable"));

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="training-v2-page">
      <div className="flex items-center gap-3">
        <div className="rounded-xl border border-border bg-card p-3">
          <CalendarDays className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold text-foreground">{t("trainingV2.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("trainingV2.subtitle")}</p>
        </div>
      </div>

      <Card data-testid="training-v2-today">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4" />
            {t("trainingV2.todayTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {todayData?.status === "no_session" ? (
            <p className="text-sm text-muted-foreground">{t("trainingV2.noSessionToday")}</p>
          ) : (
            <>
              <DetailRow label={t("trainingV2.sessionType")} value={todayTypeLabel} />
              <DetailRow label={t("trainingV2.readinessBand")} value={readinessBand} />
              <DetailRow
                label={t("trainingV2.sessionDuration")}
                value={isKnownNumber(todaySession?.duration_minutes) ? `${todaySession.duration_minutes} min` : t("trainingV2.notAvailable")}
              />
              <DetailRow
                label={t("trainingV2.sessionDistance")}
                value={isKnownNumber(todaySession?.distance_km) ? formatDistance(todaySession.distance_km, { unitSystem }) : t("trainingV2.notAvailable")}
              />
              <DetailRow
                label={t("trainingV2.sessionPrescription")}
                value={getPrescriptionText(todayData?.adapted_prescription) || getPrescriptionText(todayData?.original_prescription) || getPrescriptionText(todaySession) || t("trainingV2.notAvailable")}
              />
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

      <Card data-testid="training-v2-paces">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gauge className="h-4 w-4" />
            {t("trainingV2.pacesTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
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

          <div className="space-y-3">
            {orderedSessions.map((session, index) => {
              const day = DAYS[index];
              const workoutTypeLabel = session
                ? getTranslatedValue(t, `trainingV2.workoutTypes.${session.workout_type}`)
                : t("trainingV2.notAvailable");
              const metricParts = [];

              if (session && isKnownNumber(session.distance_km)) metricParts.push(formatDistance(session.distance_km, { unitSystem }));
              if (session && isKnownNumber(session.duration_minutes)) metricParts.push(`${session.duration_minutes} min`);
              if (session && isKnownNumber(session.estimated_tss)) metricParts.push(`${session.estimated_tss} TSS`);

              return (
                <div
                  key={day}
                  className={`rounded-xl border p-4 ${session ? (WORKOUT_STYLES[session.workout_type] ?? "border-border bg-card text-foreground") : "border-border bg-card text-foreground"}`}
                  data-testid={`training-v2-day-${day}`}
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t(`trainingPlanDays.${day}`)}</p>
                      <p className="mt-1 text-base font-semibold">{workoutTypeLabel}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      {metricParts.length > 0 ? metricParts.map((part) => (
                        <span key={part} className="rounded-full border border-current/20 px-2.5 py-1">{part}</span>
                      )) : (
                        <span className="rounded-full border border-current/20 px-2.5 py-1">{t("trainingV2.notAvailable")}</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <CycleSection cycleData={cycleData} t={t} locale={locale} />
    </div>
  );
}

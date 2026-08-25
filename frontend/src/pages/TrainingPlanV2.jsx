import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { CalendarDays, Flag, Gauge, Info, MapPin, Sparkles, Timer, Zap } from "lucide-react";

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

const CONFIDENCE_STYLES = {
  HIGH: "text-emerald-400 bg-emerald-400/10 border border-emerald-400/30",
  MEDIUM: "text-amber-400 bg-amber-400/10 border border-amber-400/30",
  LOW: "text-orange-400 bg-orange-400/10 border border-orange-400/30",
  INSUFFICIENT: "text-red-400 bg-red-400/10 border border-red-400/30",
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

const formatTargetTime = (totalSeconds) => {
  if (!isKnownNumber(totalSeconds) || totalSeconds <= 0) return null;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h${minutes.toString().padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m${seconds.toString().padStart(2, "0")}s`;
  return `${seconds}s`;
};

const formatPace = (paceMinPerKm) => {
  if (!isKnownNumber(paceMinPerKm) || paceMinPerKm <= 0) return null;
  const mins = Math.floor(paceMinPerKm);
  const secs = Math.round((paceMinPerKm - mins) * 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
};

const getTranslatedValue = (t, path, fallbackKey = "trainingV2.notAvailable") => {
  const translated = t(path);
  return translated === path ? t(fallbackKey) : translated;
};

const normalizeGoalType = (goalType) => {
  if (!goalType || typeof goalType !== "string") return null;
  const normalized = goalType.trim().toLowerCase();
  if (normalized === "semi") return "semi";
  if (normalized === "half_marathon") return "semi";
  if (normalized === "semi_marathon") return "semi";
  return normalized;
};

// ─── H1: Today's session ────────────────────────────────────────────────────

function TodaySection({ todayData, todayError, t }) {
  const readinessKey = todayData?.readiness_band
    ? `trainingV2.todayReadiness${todayData.readiness_band.charAt(0).toUpperCase() + todayData.readiness_band.slice(1).toLowerCase()}`
    : null;
  const readinessLabel = readinessKey ? t(readinessKey) : t("trainingV2.todayNoReadiness");

  const isAdapted =
    todayData?.adapted_session &&
    todayData.adapted_session !== todayData.original_session;

  const sessionToShow = isAdapted ? todayData.adapted_session : todayData?.original_session;
  const workoutTypeLabel = sessionToShow?.workout_type
    ? getTranslatedValue(t, `trainingV2.workoutTypes.${sessionToShow.workout_type}`)
    : null;

  return (
    <Card data-testid="training-v2-today">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Timer className="h-4 w-4" />
          {t("trainingV2.todayTitle")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {todayError ? (
          <p className="text-sm text-muted-foreground" data-testid="today-loading-error">
            {t("trainingV2.todayLoadingError")}
          </p>
        ) : !todayData || !sessionToShow ? (
          <p className="text-sm text-muted-foreground" data-testid="today-no-session">
            {t("trainingV2.todayNoSession")}
          </p>
        ) : (
          <>
            {isAdapted && (
              <div className="flex items-center gap-2">
                <span
                  className="rounded-full bg-amber-500/10 border border-amber-500/30 px-2.5 py-0.5 text-xs font-semibold text-amber-400"
                  data-testid="today-adapted-badge"
                >
                  {t("trainingV2.todayAdapted")}
                </span>
              </div>
            )}
            <div
              className={`rounded-xl border p-4 ${WORKOUT_STYLES[sessionToShow.workout_type] ?? "border-border bg-card text-foreground"}`}
              data-testid="today-session-card"
            >
              <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                {isAdapted ? t("trainingV2.todayAdaptedSession") : t("trainingV2.todayOriginal")}
              </p>
              <p className="mt-1 text-base font-semibold">{workoutTypeLabel}</p>
              <div className="mt-2 flex flex-wrap gap-2 text-sm">
                {isKnownNumber(sessionToShow.distance_km) && (
                  <span className="rounded-full border border-current/20 px-2.5 py-1">
                    {formatDistance(sessionToShow.distance_km, {})}
                  </span>
                )}
                {isKnownNumber(sessionToShow.duration_minutes) && (
                  <span className="rounded-full border border-current/20 px-2.5 py-1">
                    {sessionToShow.duration_minutes} min
                  </span>
                )}
              </div>
            </div>
            {isAdapted && todayData?.adaptation_reason && (
              <p className="text-xs text-muted-foreground" data-testid="today-adapted-reason">
                {t("trainingV2.todayAdaptedBecause")} {todayData.adaptation_reason}
              </p>
            )}
            <p className="text-xs text-muted-foreground" data-testid="today-readiness">
              {readinessLabel}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ─── H2: Training Paces ─────────────────────────────────────────────────────

const PACE_ZONES = [
  {
    key: "easy",
    dataKey: "easy",
    labelKey: "trainingV2.pacesEasyLabel",
    descKey: "trainingV2.pacesEasyDesc",
    isRange: true,
    colorClass: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100",
  },
  {
    key: "marathon",
    dataKey: "marathon",
    labelKey: "trainingV2.pacesMarathonLabel",
    descKey: "trainingV2.pacesMarathonDesc",
    isRange: false,
    colorClass: "border-blue-500/40 bg-blue-500/10 text-blue-100",
  },
  {
    key: "threshold",
    dataKey: "threshold",
    labelKey: "trainingV2.pacesThresholdLabel",
    descKey: "trainingV2.pacesThresholdDesc",
    isRange: false,
    colorClass: "border-amber-500/40 bg-amber-500/10 text-amber-100",
  },
  {
    key: "interval",
    dataKey: "interval",
    labelKey: "trainingV2.pacesIntervalLabel",
    descKey: "trainingV2.pacesIntervalDesc",
    isRange: true,
    colorClass: "border-orange-500/40 bg-orange-500/10 text-orange-100",
  },
  {
    key: "repetition",
    dataKey: "repetition",
    labelKey: "trainingV2.pacesRepetitionLabel",
    descKey: "trainingV2.pacesRepetitionDesc",
    isRange: false,
    colorClass: "border-red-500/40 bg-red-500/10 text-red-100",
  },
];

function PaceCard({ zone, paceData, t }) {
  const zoneData = paceData?.[zone.dataKey];
  const paceDisplay = useMemo(() => {
    if (!zoneData) return null;
    if (zone.isRange && isKnownNumber(zoneData.lower?.min_per_km) && isKnownNumber(zoneData.upper?.min_per_km)) {
      const faster = formatPace(zoneData.lower.min_per_km);  // lower = faster (lower min/km)
      const slower = formatPace(zoneData.upper.min_per_km);  // upper = slower (higher min/km)
      if (faster && slower) return `${faster} – ${slower}`;
    }
    if (isKnownNumber(zoneData.min_per_km)) {
      return formatPace(zoneData.min_per_km);
    }
    return null;
  }, [zoneData, zone.isRange]);

  return (
    <div
      className={`rounded-xl border p-4 ${zone.colorClass}`}
      data-testid={`pace-zone-${zone.key}`}
    >
      <p className="text-xs uppercase tracking-widest text-muted-foreground">{t(zone.labelKey)}</p>
      {paceDisplay ? (
        <p className="mt-1 text-xl font-bold" data-testid={`pace-value-${zone.key}`}>
          {paceDisplay}
          <span className="ml-1 text-sm font-normal opacity-70">{t("trainingV2.pacesPerKm")}</span>
        </p>
      ) : (
        <p className="mt-1 text-sm opacity-60">—</p>
      )}
      <p className="mt-1 text-xs opacity-70">{t(zone.descKey)}</p>
    </div>
  );
}

function TrainingPacesSection({ pacesData, pacesError, t }) {
  const confidence = pacesData?.confidence;
  const confidenceKey = confidence
    ? `trainingV2.pacesConfidence${confidence.charAt(0).toUpperCase() + confidence.slice(1).toLowerCase()}`
    : null;
  const confidenceLabel = confidenceKey ? t(confidenceKey) : null;
  const confidenceStyle = CONFIDENCE_STYLES[confidence] ?? CONFIDENCE_STYLES.INSUFFICIENT;

  const isInsufficient = !pacesData || confidence === "INSUFFICIENT" || pacesError;

  return (
    <Card data-testid="training-v2-paces">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <Zap className="h-4 w-4" />
            {t("trainingV2.pacesTitle")}
          </span>
          {confidenceLabel && !isInsufficient && (
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${confidenceStyle}`}
              data-testid="paces-confidence-badge"
            >
              {confidenceLabel}
            </span>
          )}
        </CardTitle>
        {!isInsufficient && (
          <p className="text-xs text-muted-foreground">{t("trainingV2.pacesSubtitle")}</p>
        )}
      </CardHeader>
      <CardContent>
        {isInsufficient ? (
          <p className="text-sm text-muted-foreground" data-testid="paces-insufficient-message">
            {t("trainingV2.pacesInsufficientMessage")}
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5" data-testid="paces-grid">
            {PACE_ZONES.map((zone) => (
              <PaceCard key={zone.key} zone={zone} paceData={pacesData?.paces} t={t} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── H4: This Week ──────────────────────────────────────────────────────────

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

// ─── H5: Training Cycle / Plan ──────────────────────────────────────────────

function CycleSection({ cycleData, t, locale }) {
  const getTranslated = (key) => {
    const translated = t(key);
    return translated === key ? t("trainingV2.notAvailable") : translated;
  };
  const cycle = cycleData?.cycle;
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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cycle?.mode && (
            <DetailRow label={t("trainingV2.cycleMode")} value={getTranslated(`trainingV2.cycleModes.${cycle.mode}`)} />
          )}
          {cycle?.status && (
            <DetailRow label={t("trainingV2.cycleStatus")} value={getTranslated(`trainingV2.cycleStatuses.${cycle.status}`)} />
          )}
          {cycle?.start_date && (
            <DetailRow label={t("trainingV2.cycleStart")} value={formatDate(cycle.start_date, locale) ?? cycle.start_date} />
          )}
          {cycle?.end_date && (
            <DetailRow label={t("trainingV2.cycleEnd")} value={formatDate(cycle.end_date, locale) ?? cycle.end_date} />
          )}
          {isKnownNumber(cycle?.current_week) && isKnownNumber(cycle?.total_weeks) && (
            <DetailRow
              label={t("trainingV2.cycleWeekProgress")}
              value={`${cycle.current_week} / ${cycle.total_weeks}`}
            />
          )}
          {isKnownNumber(cycle?.days_to_race) && (
            <DetailRow label={t("trainingV2.cycleDaysToRace")} value={String(cycle.days_to_race)} />
          )}
        </div>
        {weeks.length > 0 && (
          <div className="space-y-2 pt-2">
            <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              {t("trainingV2.cycleWeeks")}
            </p>
            {weeks.map((week) => (
              <CycleWeekRow key={week.week_number} week={week} t={t} locale={locale} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}


function LoadingState() {
  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="training-v2-loading">
      <Skeleton className="h-10 w-48" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
      <Skeleton className="h-80" />
    </div>
  );
}

function DetailRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{value}</span>
    </div>
  );
}

export default function TrainingPlanV2() {
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading } = useSubscription();
  const { unitSystem } = useUnitSystem();
  const [weekData, setWeekData] = useState(null);
  const [cycleData, setCycleData] = useState(null);
  const [todayData, setTodayData] = useState(null);
  const [todayError, setTodayError] = useState(false);
  const [pacesData, setPacesData] = useState(null);
  const [pacesError, setPacesError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    if (subLoading || isFree) return;

    let ignore = false;

    const loadData = async () => {
      setLoading(true);
      setHasError(false);
      setTodayError(false);
      setPacesError(false);
      try {
        const [weekRes, cycleRes, todayRes, pacesRes] = await Promise.all([
          axios.get(`${API}/training/v2/week`),
          axios.get(`${API}/training/v2/cycle`).catch(() => ({ data: null })),
          axios.get(`${API}/training/today`).catch(() => null),
          axios.get(`${API}/training/v2/paces`).catch(() => null),
        ]);
        if (!ignore) {
          setWeekData(weekRes.data);
          setCycleData(cycleRes.data);
          if (todayRes) {
            setTodayData(todayRes.data);
          } else {
            setTodayError(true);
          }
          if (pacesRes) {
            setPacesData(pacesRes.data);
          } else {
            setPacesError(true);
          }
        }
      } catch (error) {
        if (!ignore) {
          setHasError(true);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
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

  if (subLoading || (!isFree && (loading || (!weekData && !hasError)))) {
    return <LoadingState />;
  }

  if (isFree) {
    return <Paywall returnPath="/training" />;
  }

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

  const goalTypeKey = normalizeGoalType(weekData.goal?.goal_type);
  const goalLabel = goalTypeKey
    ? getTranslatedValue(t, `trainingV2.goalTypes.${goalTypeKey}`, "trainingV2.unknownGoal")
    : t("trainingV2.unknownGoal");
  const continuityLabel = getTranslatedValue(t, `trainingV2.continuityStates.${weekData.state?.continuity_state}`);
  const confidenceLabel = getTranslatedValue(t, `trainingV2.confidenceValues.${weekData.weekly_target?.confidence}`);
  const allowIntensityLabel = weekData.state?.allow_intensity == null
    ? t("trainingV2.notAvailable")
    : (weekData.state.allow_intensity ? t("trainingV2.allowIntensityValues.yes") : t("trainingV2.allowIntensityValues.no"));
  const targetBasis = weekData.weekly_target?.target_basis;
  const weeklyTargetValue = targetBasis === "distance"
    ? (isKnownNumber(weekData.weekly_target?.target_km) ? formatDistance(weekData.weekly_target.target_km, { unitSystem }) : t("trainingV2.notAvailable"))
    : (isKnownNumber(weekData.weekly_target?.target_duration_minutes) ? `${weekData.weekly_target.target_duration_minutes} min` : t("trainingV2.notAvailable"));

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

      {/* H1: Today */}
      <TodaySection todayData={todayData} todayError={todayError} t={t} />

      {/* H2: Training Paces */}
      <TrainingPacesSection pacesData={pacesData} pacesError={pacesError} t={t} />

      {/* H4: This Week — Objective + State + Target */}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Flag className="h-4 w-4" />
              {t("trainingV2.objective")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <DetailRow label={t("trainingV2.goalLabel")} value={goalLabel} />
            {weekData.goal?.race_date && (
              <DetailRow
                label={t("trainingV2.raceDate")}
                value={formatDate(weekData.goal.race_date, locale) ?? t("trainingV2.notAvailable")}
              />
            )}
            {isKnownNumber(weekData.goal?.target_time_seconds) && (
              <DetailRow
                label={t("trainingV2.targetTime")}
                value={formatTargetTime(weekData.goal.target_time_seconds) ?? t("trainingV2.notAvailable")}
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4" />
              {t("trainingV2.state")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <DetailRow label={t("trainingV2.continuity")} value={continuityLabel} />
            <DetailRow label={t("trainingV2.allowIntensity")} value={allowIntensityLabel} />
            <DetailRow label={t("trainingV2.confidence")} value={confidenceLabel} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Gauge className="h-4 w-4" />
              {t("trainingV2.weeklyTarget")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <DetailRow label={t("trainingV2.targetLabel")} value={weeklyTargetValue} />
            <DetailRow label={t("trainingV2.targetBasis")} value={getTranslatedValue(t, `trainingV2.targetBasisValues.${targetBasis}`)} />
            <DetailRow
              label={t("trainingV2.sessionCount")}
              value={isKnownNumber(weekData.weekly_target?.session_count) ? String(weekData.weekly_target.session_count) : t("trainingV2.notAvailable")}
            />
          </CardContent>
        </Card>
      </div>

      {/* H4: Weekly Sessions */}
      <Card>
        <CardHeader>
          <CardTitle>{t("trainingV2.week")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {orderedSessions.map((session, index) => {
            const day = DAYS[index];
            const workoutTypeLabel = session
              ? getTranslatedValue(t, `trainingV2.workoutTypes.${session.workout_type}`)
              : t("trainingV2.notAvailable");
            const metricParts = [];

            if (session && isKnownNumber(session.distance_km)) {
              metricParts.push(formatDistance(session.distance_km, { unitSystem }));
            }
            if (session && isKnownNumber(session.duration_minutes)) {
              metricParts.push(`${session.duration_minutes} min`);
            }
            if (session && isKnownNumber(session.estimated_tss)) {
              metricParts.push(`${session.estimated_tss} TSS`);
            }

            return (
              <div
                key={day}
                className={`rounded-xl border p-4 ${session ? (WORKOUT_STYLES[session.workout_type] ?? "border-border bg-card text-foreground") : "border-border bg-card text-foreground"}`}
                data-testid={`training-v2-day-${day}`}
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                      {t(`trainingPlanDays.${day}`)}
                    </p>
                    <p className="mt-1 text-base font-semibold">{workoutTypeLabel}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    {metricParts.length > 0 ? metricParts.map((part) => (
                      <span key={part} className="rounded-full border border-current/20 px-2.5 py-1">
                        {part}
                      </span>
                    )) : !session ? (
                      <span className="rounded-full border border-current/20 px-2.5 py-1">
                        {t("trainingV2.notAvailable")}
                      </span>
                    ) : null}
                  </div>
                </div>
                {session?.reason_codes?.length > 0 && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    <Info className="mr-1 inline h-3 w-3" />
                    {t("trainingV2.reasonCodesHidden")}
                  </p>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* H5: Training Cycle / Plan */}
      {cycleData && (
        <CycleSection cycleData={cycleData} t={t} locale={locale} />
      )}
    </div>
  );
}

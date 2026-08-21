import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { CalendarDays, Flag, Gauge, Sparkles, Timer } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import Paywall from "@/components/Paywall";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { API_BASE_URL } from "@/config";

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

const formatTargetTime = (totalSeconds) => {
  if (!isKnownNumber(totalSeconds) || totalSeconds <= 0) return null;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h${minutes.toString().padStart(2, "0")}`;
  if (minutes > 0) return `${minutes}m${seconds.toString().padStart(2, "0")}s`;
  return `${seconds}s`;
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
  const [weekData, setWeekData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    if (subLoading || isFree) return;

    let ignore = false;

    const loadWeek = async () => {
      setLoading(true);
      setHasError(false);
      try {
        const response = await axios.get(`${API}/training/v2/week`);
        if (!ignore) {
          setWeekData(response.data);
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

    loadWeek();

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
    return <Paywall returnPath="/training-v2" />;
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
  const targetBasis = weekData.weekly_target?.target_basis;
  const weeklyTargetValue = targetBasis === "distance"
    ? (isKnownNumber(weekData.weekly_target?.target_km) ? `${weekData.weekly_target.target_km} km` : t("trainingV2.notAvailable"))
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
            <DetailRow
              label={t("trainingV2.allowIntensity")}
              value={weekData.state?.allow_intensity ? t("trainingV2.allowIntensityValues.yes") : t("trainingV2.allowIntensityValues.no")}
            />
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
              metricParts.push(`${session.distance_km} km`);
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
                    )) : (
                      <span className="rounded-full border border-current/20 px-2.5 py-1">
                        {t("trainingV2.notAvailable")}
                      </span>
                    )}
                  </div>
                </div>
                {session?.reason_codes?.length > 0 && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    <Timer className="mr-1 inline h-3 w-3" />
                    {t("trainingV2.reasonCodesHidden")}
                  </p>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}

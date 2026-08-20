import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Activity,
  CalendarDays,
  Flag,
  Gauge,
  RefreshCw,
  Route,
  Target,
  Timer,
} from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";
import { API_BASE_URL } from "@/config";
import Paywall from "@/components/Paywall";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const API = API_BASE_URL;

const COPY = {
  fr: {
    title: "Training — V2 natif",
    subtitle: "Semaine courante",
    refresh: "Rafraîchir",
    loadingError: "Impossible de charger la semaine V2.",
    loadFailed: "Chargement impossible",
    retry: "Réessayer",
    goal: "Objectif",
    state: "État",
    continuityState: "État de continuité",
    weeklyTarget: "Cible hebdo",
    plannedWeek: "Planifié cette semaine",
    basisDistance: "Base distance",
    basisDuration: "Base durée",
    sessions: "séances",
    confidence: "Confiance",
    allowedIntensity: "Intensité autorisée",
    onlyEasy: "Easy / récupération uniquement",
    raceDate: "Date course",
    targetTime: "Temps cible",
    none: "Non défini",
    estimatedTss: "TSS estimé",
    reasonCodes: "Reason codes",
    minutes: "min",
  },
  es: {
    title: "Training — V2 nativo",
    subtitle: "Semana actual",
    refresh: "Actualizar",
    loadingError: "No se pudo cargar la semana V2.",
    loadFailed: "Error de carga",
    retry: "Reintentar",
    goal: "Objetivo",
    state: "Estado",
    continuityState: "Estado de continuidad",
    weeklyTarget: "Objetivo semanal",
    plannedWeek: "Planificado esta semana",
    basisDistance: "Base distancia",
    basisDuration: "Base duración",
    sessions: "sesiones",
    confidence: "Confianza",
    allowedIntensity: "Intensidad permitida",
    onlyEasy: "Solo easy / recuperación",
    raceDate: "Fecha de carrera",
    targetTime: "Tiempo objetivo",
    none: "No definido",
    estimatedTss: "TSS estimado",
    reasonCodes: "Reason codes",
    minutes: "min",
  },
  en: {
    title: "Training — Native V2",
    subtitle: "Current week",
    refresh: "Refresh",
    loadingError: "Unable to load V2 week.",
    loadFailed: "Loading failed",
    retry: "Retry",
    goal: "Goal",
    state: "State",
    continuityState: "Continuity state",
    weeklyTarget: "Weekly target",
    plannedWeek: "Planned this week",
    basisDistance: "Distance basis",
    basisDuration: "Duration basis",
    sessions: "sessions",
    confidence: "Confidence",
    allowedIntensity: "Intensity allowed",
    onlyEasy: "Easy / recovery only",
    raceDate: "Race date",
    targetTime: "Target time",
    none: "Not set",
    estimatedTss: "Estimated TSS",
    reasonCodes: "Reason codes",
    minutes: "min",
  },
};

const DAY_LABELS = {
  monday: { fr: "Lundi", es: "Lunes", en: "Monday" },
  tuesday: { fr: "Mardi", es: "Martes", en: "Tuesday" },
  wednesday: { fr: "Mercredi", es: "Miércoles", en: "Wednesday" },
  thursday: { fr: "Jeudi", es: "Jueves", en: "Thursday" },
  friday: { fr: "Vendredi", es: "Viernes", en: "Friday" },
  saturday: { fr: "Samedi", es: "Sábado", en: "Saturday" },
  sunday: { fr: "Dimanche", es: "Domingo", en: "Sunday" },
};

const SESSION_COLORS = {
  rest: "border-indigo-500/60 bg-indigo-950/30",
  recovery: "border-cyan-500/60 bg-cyan-950/30",
  easy: "border-emerald-500/60 bg-emerald-950/30",
  steady: "border-sky-500/60 bg-sky-950/30",
  quality: "border-orange-500/60 bg-orange-950/30",
  long_easy: "border-blue-500/60 bg-blue-950/30",
};

const DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const formatTargetTime = (seconds) => {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${s.toString().padStart(2, "0")}s`;
  return `${s}s`;
};

const formatReferenceDate = (dateString, locale) => {
  if (!dateString) return "";
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return dateString;
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  }).format(date);
};

export default function TrainingPlanV2() {
  const { lang } = useLanguage();
  const locale = lang === "fr" ? "fr-FR" : lang === "es" ? "es-ES" : "en-US";
  const copy = COPY[lang] || COPY.en;
  const { unitSystem } = useUnitSystem();
  const { isFree, loading: subLoading } = useSubscription();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [apiError, setApiError] = useState(null);

  const fetchWeek = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const response = await axios.get(`${API}/training/v2/week`);
      setData(response.data);
      setApiError(null);
    } catch (error) {
      if (error?.response?.status === 403 && error?.response?.data?.error === "subscription_required") {
        setApiError("subscription_required");
      } else {
        setApiError("generic");
        toast.error(copy.loadingError);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [copy.loadingError]);

  useEffect(() => {
    fetchWeek();
  }, [fetchWeek]);

  const sessions = useMemo(() => {
    const source = Array.isArray(data?.week?.sessions) ? data.week.sessions : [];
    return [...source].sort((a, b) => DAY_ORDER.indexOf(a.day) - DAY_ORDER.indexOf(b.day));
  }, [data]);

  if (loading || subLoading) {
    return (
      <div className="p-4 md:p-6 space-y-4">
        <Skeleton className="h-8 w-56" />
        <div className="grid gap-3 md:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (isFree || apiError === "subscription_required") {
    return <Paywall language={lang} returnPath="/training-v2" />;
  }

  if (apiError === "generic" && !data) {
    return (
      <div className="p-4 md:p-6">
        <Card className="border-red-500/50">
          <CardHeader>
            <CardTitle className="text-red-300">{copy.loadFailed}</CardTitle>
          </CardHeader>
          <CardContent>
            <Button onClick={() => fetchWeek()}>{copy.retry}</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const weeklyTarget = data?.weekly_target || {};
  const week = data?.week || {};
  const goal = data?.goal || {};
  const state = data?.state || {};
  const targetTime = formatTargetTime(goal.target_time_seconds);
  const referenceDate = formatReferenceDate(data?.reference_date, locale);

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{copy.title}</h1>
          <p className="text-sm text-muted-foreground">
            {copy.subtitle}{referenceDate ? ` • ${referenceDate}` : ""}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            setRefreshing(true);
            fetchWeek({ silent: true });
          }}
          disabled={refreshing}
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
          {copy.refresh}
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Flag className="w-4 h-4 text-blue-400" />
              {copy.goal}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Type</span>
              <Badge variant="secondary">{goal.goal_type || copy.none}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{copy.raceDate}</span>
              <span>{goal.race_date || copy.none}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{copy.targetTime}</span>
              <span>{targetTime || copy.none}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              {copy.state}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{copy.continuityState}</span>
              <Badge variant="outline">{state.continuity_state || copy.none}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{copy.allowedIntensity}</span>
              <Badge variant={state.allow_intensity ? "default" : "secondary"}>
                {state.allow_intensity ? "ON" : "OFF"}
              </Badge>
            </div>
            {!state.allow_intensity && (
              <p className="text-xs text-amber-300">{copy.onlyEasy}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Target className="w-4 h-4 text-emerald-400" />
              {copy.weeklyTarget}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">
                {weeklyTarget.target_basis === "duration" ? copy.basisDuration : copy.basisDistance}
              </span>
              <span>
                {weeklyTarget.target_basis === "duration"
                  ? weeklyTarget.target_duration_minutes != null
                    ? `${weeklyTarget.target_duration_minutes} ${copy.minutes}`
                    : copy.none
                  : weeklyTarget.target_km != null
                    ? formatDistance(weeklyTarget.target_km, { unitSystem })
                    : copy.none}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{copy.sessions}</span>
              <Badge variant="secondary">{weeklyTarget.session_count ?? 0}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{copy.confidence}</span>
              <Badge variant="outline">{weeklyTarget.confidence || copy.none}</Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <CalendarDays className="w-5 h-5 text-violet-400" />
            {copy.plannedWeek}
          </CardTitle>
          <div className="text-sm text-muted-foreground flex flex-wrap gap-3">
            <span className="inline-flex items-center gap-1">
              <Route className="w-4 h-4" />
              {week.planned_km != null ? formatDistance(week.planned_km, { unitSystem }) : "—"}
            </span>
            <span className="inline-flex items-center gap-1">
              <Timer className="w-4 h-4" />
              {week.planned_duration_minutes != null ? `${week.planned_duration_minutes} ${copy.minutes}` : "—"}
            </span>
            <span className="inline-flex items-center gap-1">
              <Gauge className="w-4 h-4" />
              {week.session_count ?? 0} {copy.sessions}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {sessions.map((session, index) => {
            const dayLabel = DAY_LABELS[session.day]?.[lang] || DAY_LABELS[session.day]?.en || session.day;
            const colorClass = SESSION_COLORS[session.workout_type] || "border-border bg-muted/20";
            const isRest = session.workout_type === "rest";
            const targetLabel = session.distance_km != null
              ? formatDistance(session.distance_km, { unitSystem })
              : session.duration_minutes != null
                ? `${session.duration_minutes} ${copy.minutes}`
                : "—";
            const tss = session.estimated_tss == null ? "—" : Number(session.estimated_tss).toFixed(0);

            return (
              <div
                key={[
                  session.day,
                  session.workout_type,
                  session.intensity_class,
                  session.distance_km ?? "na",
                  session.duration_minutes ?? "na",
                  session.reason_codes?.join("|") ?? "na",
                  index,
                ].join("-")}
                className={`rounded-lg border p-3 ${colorClass}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{dayLabel}</span>
                    <Badge variant="outline">{session.workout_type}</Badge>
                    <Badge variant="secondary">{session.intensity_class}</Badge>
                  </div>
                  <span className="text-sm font-medium">{targetLabel}</span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span>{copy.estimatedTss}: {isRest ? "0" : tss}</span>
                  {Array.isArray(session.reason_codes) && session.reason_codes.length > 0 && (
                    <span className="truncate max-w-full">
                      {copy.reasonCodes}: {session.reason_codes.join(", ")}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}

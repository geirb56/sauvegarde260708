import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import axios from "axios";
import {
  Activity,
  ArrowLeft,
  HeartPulse,
  Lightbulb,
  Scale,
  Sparkles,
} from "lucide-react";

import { API_BASE_URL } from "@/config";
import { useLanguage } from "@/context/LanguageContext";
import { useUnitSystem } from "@/context/UnitContext";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDistance, formatElevation, formatPace, formatSpeed } from "@/utils/units";
import { formatDuration } from "@/utils/workoutHelpers";

const API = API_BASE_URL;

const localeByLang = {
  en: "en-US",
  fr: "fr-FR",
  es: "es-ES",
};

const KNOWN_METRIC_KEYS = new Set([
  "id",
  "name",
  "date",
  "type",
  "notes",
  "user_id",
  "_id",
]);

const formatLabel = (key) => key
  .replace(/_/g, " ")
  .replace(/\b\w/g, (char) => char.toUpperCase());

const formatWorkoutTypeLabel = (type, t) => {
  const translated = t(`workoutTypes.${type}`);
  return translated === `workoutTypes.${type}` ? formatLabel(type || "") : translated;
};

const formatValue = (value) => {
  if (value == null || value === "") return "--";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return `${value}`;
  if (Array.isArray(value) || typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return value;
};

const DetailSkeleton = () => (
  <div className="space-y-4 p-4 pb-24">
    <Skeleton className="h-7 w-40" />
    <Skeleton className="h-24 w-full" />
    <Skeleton className="h-48 w-full" />
    <Skeleton className="h-56 w-full" />
  </div>
);

export default function SessionDetail() {
  const { id } = useParams();
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const [session, setSession] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadSession = async () => {
      setLoading(true);
      try {
        const [sessionRes, analysisRes] = await Promise.all([
          axios.get(`${API}/workouts/${id}`),
          axios.get(`${API}/coach/detailed-analysis/${id}?language=${lang}`).catch(() => ({ data: null })),
        ]);
        setSession(sessionRes.data);
        setAnalysis(analysisRes.data);
      } catch (error) {
        console.error("Failed to load session:", error);
        setSession(null);
        setAnalysis(null);
      } finally {
        setLoading(false);
      }
    };

    loadSession();
  }, [id, lang]);

  const locale = localeByLang[lang] || "en-US";
  const cadenceValue = session?.avg_cadence_spm || session?.average_cadence;

  const primaryMetrics = useMemo(() => {
    if (!session) return [];

    return [
      { label: t("sessions.columns.distance"), value: formatDistance(session.distance_km || 0, { unitSystem }) },
      { label: t("sessions.columns.duration"), value: formatDuration(session.duration_minutes) },
      { label: t("sessions.movingTime"), value: formatDuration(session.moving_time_minutes) },
      { label: t("sessions.columns.pace"), value: formatPace((session.avg_pace_min_km || 0) * 60, { unitSystem }) },
      { label: t("workout.avgSpeed"), value: formatSpeed(session.avg_speed_kmh || 0, { unitSystem }) },
      { label: t("workout.avgHeartRate"), value: session.avg_heart_rate ? `${session.avg_heart_rate} bpm` : "--" },
      { label: t("workout.maxHeartRate"), value: session.max_heart_rate ? `${session.max_heart_rate} bpm` : "--" },
      { label: t("sessions.avgCadence"), value: cadenceValue ? `${cadenceValue} spm` : "--" },
      { label: t("workout.elevation"), value: formatElevation(session.elevation_gain_m || 0, { unitSystem }) },
      { label: t("workout.calories"), value: session.calories ? `${session.calories}` : "--" },
      { label: t("sessions.trainingLoad"), value: session.training_load ?? "--" },
      { label: t("sessions.bestPace"), value: formatPace((session.best_pace_min_km || 0) * 60, { unitSystem }) },
      { label: t("sessions.maxSpeed"), value: formatSpeed(session.max_speed_kmh || 0, { unitSystem }) },
      { label: t("sessions.source"), value: session.data_source || "--" },
      { label: t("sessions.createdAt"), value: session.created_at ? new Date(session.created_at).toLocaleString(locale) : "--" },
    ].filter((metric) => metric.value !== "--");
  }, [cadenceValue, locale, session, t, unitSystem]);

  const extraMetrics = useMemo(() => {
    if (!session) return [];

    return Object.entries(session).filter(([key, value]) => {
      if (KNOWN_METRIC_KEYS.has(key)) return false;
      if ([
        "distance_km",
        "duration_minutes",
        "moving_time_minutes",
        "avg_pace_min_km",
        "avg_speed_kmh",
        "avg_heart_rate",
        "max_heart_rate",
        "avg_cadence_spm",
        "average_cadence",
        "elevation_gain_m",
        "calories",
        "training_load",
        "best_pace_min_km",
        "max_speed_kmh",
        "data_source",
        "created_at",
      ].includes(key)) {
        return false;
      }

      return value != null && value !== "";
    });
  }, [session]);

  if (loading) {
    return <DetailSkeleton />;
  }

  if (!session) {
    return (
      <div className="p-4 pb-24">
        <Link to="/sessions" className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <ArrowLeft className="h-4 w-4" />
          {t("sessions.back")}
        </Link>
        <p className="mt-6 text-muted-foreground">{t("workout.notFound")}</p>
      </div>
    );
  }

  const analysisSections = [
    {
      key: "summary",
      title: t("sessions.summary"),
      icon: Sparkles,
      content: analysis?.header?.context,
      tone: "border-primary/20 bg-primary/5",
    },
    {
      key: "strengths",
      title: t("sessions.strengths"),
      icon: Scale,
      content: [analysis?.execution?.intensity, analysis?.execution?.volume, analysis?.execution?.regularity].filter(Boolean).join(" • "),
      tone: "border-emerald-500/20 bg-emerald-500/5",
    },
    {
      key: "improvements",
      title: t("sessions.improvements"),
      icon: Activity,
      content: analysis?.advanced?.comparisons,
      tone: "border-amber-500/20 bg-amber-500/5",
    },
    {
      key: "physiology",
      title: t("sessions.physiology"),
      icon: HeartPulse,
      content: analysis?.meaning?.text,
      tone: "border-border bg-card/40",
    },
    {
      key: "recovery",
      title: t("sessions.recovery"),
      icon: HeartPulse,
      content: analysis?.recovery?.text,
      tone: "border-orange-500/20 bg-orange-500/5",
    },
    {
      key: "nextSession",
      title: t("sessions.nextSession"),
      icon: Lightbulb,
      content: analysis?.advice?.text,
      tone: "border-violet-500/20 bg-violet-500/5",
    },
  ].filter((section) => section.content);

  return (
    <div className="p-4 pb-24 space-y-4" data-testid="session-detail-page">
      <div className="space-y-3">
        <Link to="/sessions" className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <ArrowLeft className="h-4 w-4" />
          {t("sessions.back")}
        </Link>

        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{formatWorkoutTypeLabel(session.type, t)}</p>
            <h1 className="text-2xl font-semibold tracking-tight">{session.name}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {new Date(session.date).toLocaleString(locale, {
              year: "numeric",
              month: "long",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        </div>
      </div>

      <section className="space-y-3 rounded-2xl border border-border bg-card/30 p-4">
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {t("sessions.metrics")}
          </h2>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {primaryMetrics.map((metric) => (
            <div key={metric.label} className="rounded-xl border border-border/70 bg-background/60 p-3">
              <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{metric.label}</p>
              <p className="mt-2 text-sm font-medium">{metric.value}</p>
            </div>
          ))}
        </div>
      </section>

      {extraMetrics.length > 0 && (
        <section className="space-y-3 rounded-2xl border border-border bg-card/30 p-4">
          <h2 className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {t("sessions.otherMetrics")}
          </h2>

          <div className="grid gap-3 lg:grid-cols-2">
            {extraMetrics.map(([key, value]) => (
              <div key={key} className="rounded-xl border border-border/70 bg-background/60 p-3">
                <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{formatLabel(key)}</p>
                {typeof value === "object" ? (
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs text-foreground/90">
                    {formatValue(value)}
                  </pre>
                ) : (
                  <p className="mt-2 text-sm font-medium">{formatValue(value)}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-3 rounded-2xl border border-border bg-card/30 p-4">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {t("sessions.analysisTitle")}
          </h2>
        </div>

        {analysisSections.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("sessions.unavailable")}</p>
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {analysisSections.map((section) => {
              const Icon = section.icon;
              return (
                <div key={section.key} className={`rounded-2xl border p-4 ${section.tone}`}>
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4" />
                    <h3 className="text-sm font-medium">{section.title}</h3>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-foreground/90">{section.content}</p>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

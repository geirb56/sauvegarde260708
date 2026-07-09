import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Search, Sparkles } from "lucide-react";

import { API_BASE_URL } from "@/config";
import { useLanguage } from "@/context/LanguageContext";
import { useUnitSystem } from "@/context/UnitContext";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { formatDistance, formatElevation, formatPace } from "@/utils/units";
import { formatDuration } from "@/utils/workoutHelpers";

const API = API_BASE_URL;

const localeByLang = {
  en: "en-US",
  fr: "fr-FR",
  es: "es-ES",
};

const formatDate = (date, locale) => {
  if (!date) return "--";
  return new Date(date).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
};

const formatHeartRate = (value) => (value ? `${value} bpm` : "--");
const formatWorkoutTypeLabel = (value) => value
  ? value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase())
  : "--";

const LoadingRows = () => (
  <div className="rounded-2xl border border-border overflow-hidden bg-card/30">
    {Array.from({ length: 8 }).map((_, index) => (
      <div
        key={index}
        className="grid grid-cols-2 gap-3 border-b border-border/70 px-4 py-4 last:border-b-0 md:grid-cols-[1.2fr_1fr_1fr_1fr_1fr_1fr_1fr_72px]"
      >
        {Array.from({ length: 8 }).map((__, cellIndex) => (
          <Skeleton key={cellIndex} className="h-5 w-full" />
        ))}
      </div>
    ))}
  </div>
);

export default function Sessions() {
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sport, setSport] = useState("all");
  const [sortOrder, setSortOrder] = useState("desc");

  useEffect(() => {
    const loadSessions = async () => {
      setLoading(true);
      try {
        const res = await axios.get(`${API}/workouts`);
        setSessions(Array.isArray(res.data) ? res.data : []);
      } catch (error) {
        console.error("Failed to load sessions:", error);
        setSessions([]);
      } finally {
        setLoading(false);
      }
    };

    loadSessions();
  }, []);

  const locale = localeByLang[lang] || "en-US";

  const sportOptions = useMemo(() => {
    const values = new Set(sessions.map((session) => session.type).filter(Boolean));
    return Array.from(values).sort();
  }, [sessions]);

  const filteredSessions = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    return [...sessions]
      .filter((session) => {
        const matchesSearch = !normalizedSearch
          || session.name?.toLowerCase().includes(normalizedSearch);
        const matchesSport = sport === "all" || session.type === sport;
        return matchesSearch && matchesSport;
      })
      .sort((a, b) => {
        const aDate = new Date(a.date || 0).getTime();
        const bDate = new Date(b.date || 0).getTime();
        return sortOrder === "asc" ? aDate - bDate : bDate - aDate;
      });
  }, [search, sessions, sortOrder, sport]);

  const getSportLabel = (type) => {
    const translated = t(`workoutTypes.${type}`);
    return translated === `workoutTypes.${type}` ? formatWorkoutTypeLabel(type) : translated;
  };

  return (
    <div className="p-4 pb-24 space-y-4" data-testid="sessions-page">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t("sessions.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("sessions.subtitle")}</p>
      </div>

      <div className="grid gap-3 rounded-2xl border border-border bg-card/40 p-3 md:grid-cols-[minmax(0,1fr)_220px_220px]">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("sessions.searchPlaceholder")}
            className="pl-9"
          />
        </div>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">{t("sessions.sportFilter")}</span>
          <select
            value={sport}
            onChange={(event) => setSport(event.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="all">{t("sessions.allSports")}</option>
            {sportOptions.map((value) => (
              <option key={value} value={value}>
                {getSportLabel(value)}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">{t("sessions.sort")}</span>
          <select
            value={sortOrder}
            onChange={(event) => setSortOrder(event.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="desc">{t("sessions.sortNewest")}</option>
            <option value="asc">{t("sessions.sortOldest")}</option>
          </select>
        </label>
      </div>

      {loading ? (
        <LoadingRows />
      ) : filteredSessions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
          {t("sessions.noResults")}
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border bg-card/30">
          <div className="hidden border-b border-border/70 bg-muted/30 px-4 py-3 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground md:grid md:grid-cols-[1.2fr_1fr_1fr_1fr_1fr_1fr_1fr_72px]">
            <span>{t("sessions.columns.sport")}</span>
            <span>{t("sessions.columns.date")}</span>
            <span>{t("sessions.columns.distance")}</span>
            <span>{t("sessions.columns.duration")}</span>
            <span>{t("sessions.columns.pace")}</span>
            <span>{t("sessions.columns.heartRate")}</span>
            <span>{t("sessions.columns.elevation")}</span>
            <span className="text-center">{t("sessions.columns.analysis")}</span>
          </div>

          {filteredSessions.map((session) => (
            <Link
              key={session.id}
              to={`/sessions/${session.id}`}
              className="block border-b border-border/70 px-4 py-4 transition-colors hover:bg-muted/20 last:border-b-0"
            >
              <div className="grid gap-3 md:grid-cols-[1.2fr_1fr_1fr_1fr_1fr_1fr_1fr_72px] md:items-center">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{session.name || getSportLabel(session.type)}</p>
                  <p className="text-xs text-muted-foreground">{getSportLabel(session.type)}</p>
                </div>

                <div className="text-sm text-muted-foreground">{formatDate(session.date, locale)}</div>
                <div className="text-sm">{formatDistance(session.distance_km || 0, { unitSystem })}</div>
                <div className="text-sm">{formatDuration(session.duration_minutes)}</div>
                <div className="text-sm">{formatPace((session.avg_pace_min_km || 0) * 60, { unitSystem })}</div>
                <div className="text-sm">{formatHeartRate(session.avg_heart_rate)}</div>
                <div className="text-sm">{formatElevation(session.elevation_gain_m || 0, { unitSystem })}</div>

                <div className="flex items-center justify-start md:justify-center">
                  <Sparkles
                    className="h-4 w-4 text-primary"
                    aria-label={t("sessions.aiAvailable")}
                    title={t("sessions.aiAvailable")}
                  />
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

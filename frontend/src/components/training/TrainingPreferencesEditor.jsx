import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage } from "@/context/LanguageContext";
import { API_BASE_URL } from "@/config";

const API = API_BASE_URL;
const SESSION_VALUES = [2, 3, 4, 5, 6];
const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const EMPTY_PREFERENCES = {
  sessions_per_week: null,
  preferred_training_days: null,
  preferred_long_run_day: null,
};

const getPreferences = (data) => data?.training_prefs || EMPTY_PREFERENCES;

const normalizeDays = (days) => (
  Array.isArray(days) ? DAYS.filter((day) => days.includes(day)) : []
);

const toDraft = (preferences) => ({
  sessions_per_week: SESSION_VALUES.includes(preferences?.sessions_per_week)
    ? preferences.sessions_per_week
    : null,
  preferred_training_days: normalizeDays(preferences?.preferred_training_days),
  preferred_long_run_day: DAYS.includes(preferences?.preferred_long_run_day)
    ? preferences.preferred_long_run_day
    : null,
});

const hasPreferences = (preferences) => (
  preferences.sessions_per_week != null
  || preferences.preferred_training_days != null
  || preferences.preferred_long_run_day != null
);

const sameDays = (left, right) => {
  const normalizedLeft = normalizeDays(left);
  const normalizedRight = normalizeDays(right);
  return normalizedLeft.length === normalizedRight.length
    && normalizedLeft.every((day, index) => day === normalizedRight[index]);
};

const samePreferences = (left, right) => (
  left.sessions_per_week === right.sessions_per_week
  && sameDays(left.preferred_training_days, right.preferred_training_days)
  && left.preferred_long_run_day === right.preferred_long_run_day
);

const formatDate = (value, locale) => {
  if (typeof value !== "string") return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return null;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
};

const getErrorMessage = (error, t) => {
  const status = error?.response?.status;
  if (status === 401) return t("settingsV2.preferences.authError");
  if (status === 409) return t("settingsV2.preferences.conflictError");
  if (status === 422) {
    return t("settingsV2.preferences.validationError");
  }
  if (!error?.response) return t("settingsV2.preferences.networkError");
  return t("settingsV2.preferences.saveError");
};

export default function TrainingPreferencesEditor() {
  const { lang, t } = useLanguage();
  const [preferences, setPreferences] = useState(EMPTY_PREFERENCES);
  const [activePreferences, setActivePreferences] = useState(EMPTY_PREFERENCES);
  const [effectiveFrom, setEffectiveFrom] = useState(null);
  const [draft, setDraft] = useState(() => toDraft(EMPTY_PREFERENCES));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [savedMessage, setSavedMessage] = useState("");
  const savingRef = useRef(false);

  const acceptPreferences = useCallback((data) => {
    const nextPreferences = getPreferences(data);
    const nextDraft = toDraft(nextPreferences);
    setPreferences({
      ...EMPTY_PREFERENCES,
      ...nextPreferences,
      preferred_training_days: normalizeDays(nextPreferences.preferred_training_days),
    });
    setActivePreferences({
      ...EMPTY_PREFERENCES,
      ...(nextPreferences.active_preferences || nextPreferences),
      preferred_training_days: normalizeDays(
        (nextPreferences.active_preferences || nextPreferences).preferred_training_days
      ),
    });
    setEffectiveFrom(nextPreferences.effective_from || null);
    setDraft(nextDraft);
  }, []);

  const loadPreferences = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const response = await axios.get(`${API}/training/v2/preferences`);
      acceptPreferences(response.data);
      return true;
    } catch (error) {
      setLoadError(getErrorMessage(error, t));
      return false;
    } finally {
      setLoading(false);
    }
  }, [acceptPreferences, t]);

  useEffect(() => {
    loadPreferences();
  }, [loadPreferences]);

  const dirty = !samePreferences(draft, toDraft(preferences));
  const desired = toDraft(preferences);
  const active = toDraft(activePreferences);
  const hasPendingChanges = effectiveFrom && !samePreferences(desired, active);
  const locale = lang === "fr" ? "fr-FR" : lang === "es" ? "es-ES" : "en-US";
  const effectiveDate = formatDate(effectiveFrom, locale);
  const dayLabel = (day) => t(`trainingPlanDays.${day}`);
  const activeDaysLabel = active.preferred_training_days.length
    ? active.preferred_training_days.map(dayLabel).join(", ")
    : t("settingsV2.preferences.none");
  const visibleLongRunDays = draft.preferred_training_days.length
    ? draft.preferred_training_days
    : DAYS;

  const updateDraft = (updates) => {
    setDraft((current) => ({ ...current, ...updates }));
    setErrorMessage("");
    setSavedMessage("");
  };

  const toggleDay = (day) => {
    const selected = draft.preferred_training_days.includes(day);
    const nextDays = selected
      ? draft.preferred_training_days.filter((selectedDay) => selectedDay !== day)
      : DAYS.filter((candidate) => draft.preferred_training_days.includes(candidate) || candidate === day);
    updateDraft({
      preferred_training_days: nextDays,
      ...(selected && draft.preferred_long_run_day === day ? { preferred_long_run_day: null } : {}),
    });
  };

  const save = async () => {
    if (!dirty || savingRef.current) return;

    const payload = {};
    if (draft.sessions_per_week !== desired.sessions_per_week && draft.sessions_per_week != null) {
      payload.sessions_per_week = draft.sessions_per_week;
    }
    if (!sameDays(draft.preferred_training_days, desired.preferred_training_days)) {
      payload.preferred_training_days = draft.preferred_training_days.length
        ? draft.preferred_training_days
        : null;
    }
    if (draft.preferred_long_run_day !== desired.preferred_long_run_day) {
      payload.preferred_long_run_day = draft.preferred_long_run_day;
    }
    if (!Object.keys(payload).length) return;

    savingRef.current = true;
    setSaving(true);
    setErrorMessage("");
    setSavedMessage("");
    try {
      const response = await axios.patch(`${API}/training/v2/preferences`, payload);
      if (response.data?.training_prefs) {
        acceptPreferences(response.data);
      } else {
        const reloaded = await loadPreferences();
        if (!reloaded) return;
      }
      setSavedMessage(t("settingsV2.preferences.saved"));
    } catch (error) {
      setErrorMessage(getErrorMessage(error, t));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3" data-testid="training-preferences-loading">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="space-y-3" data-testid="training-preferences-load-error">
        <p className="text-sm text-destructive">{loadError}</p>
        <Button type="button" variant="outline" onClick={loadPreferences}>
          {t("settingsV2.preferences.retry")}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="training-preferences-editor">
      <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid="settings-sessions-current">
        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
          {t("settingsV2.plan.sessions")}
        </p>
        <p className="mt-1 text-sm font-medium text-foreground">
          {draft.sessions_per_week
            ? t("settingsV2.plan.sessionsValue").replace("{count}", String(draft.sessions_per_week))
            : t("settingsV2.common.missing")}
        </p>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          {t("settingsV2.plan.sessionsHelp")}
        </p>
      </div>
      <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid="settings-sessions-options">
        <div className="grid grid-cols-5 gap-2" data-testid="settings-sessions-grid">
          {SESSION_VALUES.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={draft.sessions_per_week === value}
              className={`rounded-xl border px-3 py-3 text-sm font-semibold transition-colors ${
                draft.sessions_per_week === value
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-card text-foreground hover:border-primary/40"
              }`}
              data-testid={`sessions-per-week-btn-${value}`}
              disabled={saving}
              onClick={() => updateDraft({ sessions_per_week: value })}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid="preferred-training-days">
        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
          {t("settingsV2.preferences.trainingDays")}
        </p>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          {t("settingsV2.preferences.trainingDaysHelp")}
        </p>
        <div className="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-7">
          {DAYS.map((day) => {
            const selected = draft.preferred_training_days.includes(day);
            return (
              <button
                key={day}
                type="button"
                aria-pressed={selected}
                className={`min-h-11 rounded-xl border px-2 py-2 text-sm font-medium transition-colors ${
                  selected
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-card text-foreground hover:border-primary/40"
                }`}
                data-testid={`preferred-day-${day}`}
                disabled={saving}
                onClick={() => toggleDay(day)}
              >
                {dayLabel(day)}
              </button>
            );
          })}
        </div>
        <label className="mt-4 block text-sm font-medium text-foreground" htmlFor="preferred-long-run-day">
          {t("settingsV2.preferences.longRunDay")}
        </label>
        <select
          id="preferred-long-run-day"
          className="mt-2 min-h-11 w-full rounded-xl border border-border bg-card px-3 text-sm text-foreground"
          data-testid="preferred-long-run-day"
          value={draft.preferred_long_run_day || ""}
          disabled={saving}
          onChange={(event) => updateDraft({ preferred_long_run_day: event.target.value || null })}
        >
          <option value="">{t("settingsV2.preferences.none")}</option>
          {visibleLongRunDays.map((day) => (
            <option key={day} value={day}>{dayLabel(day)}</option>
          ))}
        </select>
      </div>

      <div className="rounded-xl border border-border bg-muted/30 p-4" data-testid="active-training-preferences">
        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
          {t("settingsV2.preferences.activeTitle")}
        </p>
        {!hasPreferences(activePreferences) ? (
          <p className="mt-1 text-sm text-muted-foreground">{t("settingsV2.preferences.empty")}</p>
        ) : (
          <>
            {active.sessions_per_week ? (
              <p className="mt-1 text-sm text-foreground">
                {t("settingsV2.preferences.activeSessions").replace("{count}", String(active.sessions_per_week))}
              </p>
            ) : null}
            <p className="mt-1 text-sm text-foreground">
              {t("settingsV2.preferences.activeDays").replace("{days}", activeDaysLabel)}
            </p>
            {active.preferred_long_run_day ? (
              <p className="mt-1 text-sm text-muted-foreground">
                {t("settingsV2.preferences.activeLongRun").replace("{day}", dayLabel(active.preferred_long_run_day))}
              </p>
            ) : null}
          </>
        )}
      </div>

      {hasPendingChanges && effectiveDate ? (
        <p className="text-sm text-muted-foreground" data-testid="training-preferences-effective-date">
          {t("settingsV2.preferences.effectiveFrom").replace("{date}", effectiveDate)}
        </p>
      ) : null}
      {errorMessage ? <p className="text-sm text-destructive" role="alert">{errorMessage}</p> : null}
      {savedMessage ? <p className="text-sm text-emerald-400" role="status">{savedMessage}</p> : null}
      <Button
        type="button"
        onClick={save}
        disabled={!dirty || saving}
        data-testid="save-training-preferences"
      >
        {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {saving ? t("settingsV2.common.saving") : t("settingsV2.preferences.save")}
      </Button>
    </div>
  );
}

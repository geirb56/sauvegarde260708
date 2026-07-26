import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Link } from "react-router-dom";
import axios from "axios";
import { Activity, Bike, ChevronRight, Flame, Heart, Zap } from "lucide-react";

import { API_BASE_URL } from "@/config";
import { useLanguage } from "@/context/LanguageContext";
import { useUnitSystem } from "@/context/UnitContext";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDistance, formatPace as formatPaceUnits } from "@/utils/units";

const API = API_BASE_URL;

const WORKOUT_TYPES = {
  fractionne: { color: "#f97316", icon: Zap },
  endurance: { color: "#10b981", icon: Activity },
  seuil: { color: "#f97316", icon: Flame },
  recuperation: { color: "#22d3ee", icon: Heart },
  run: { color: "#10b981", icon: Activity },
  cycle: { color: "#f97316", icon: Bike },
};

const getRelativeDate = (dateStr, t, locale) => {
  const date = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return t("dashboard.today");
  if (date.toDateString() === yesterday.toDateString()) return t("dashboard.yesterday");
  return date.toLocaleDateString(locale, { day: "numeric", month: "short" });
};

const LoadingRows = () => (
  <div className="space-y-2">
    {Array.from({ length: 5 }).map((_, index) => (
      <Skeleton key={index} className="h-16 w-full rounded-2xl" />
    ))}
  </div>
);

export default function Sessions() {
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const [workouts, setWorkouts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadWorkouts = async () => {
      setLoading(true);
      try {
        const res = await axios.get(`${API}/workouts`, { headers: { "X-User-Id": undefined } });
        setWorkouts(Array.isArray(res.data) ? res.data : []);
      } catch (error) {
        console.error("Failed to load workouts:", error);
        setWorkouts([]);
      } finally {
        setLoading(false);
      }
    };

    loadWorkouts();
  }, []);

  return (
    <div className="p-4 pb-24 space-y-4" data-testid="sessions-page">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t("sessions.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("sessions.subtitle")}</p>
      </div>

      {loading ? (
        <LoadingRows />
      ) : workouts.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
          {t("sessions.noResults")}
        </div>
      ) : (
        <div className="space-y-2">
          {workouts.map((workout, index) => {
            const workoutName = workout.name?.toLowerCase() || "";
            const notes = workout.notes?.toLowerCase() || "";
            const avgHR = workout.avg_heart_rate || 0;

            let workoutType = "endurance";

            if (workoutName.includes("interval") || notes.includes("interval") || workoutName.includes("fractionn")) {
              workoutType = "fractionne";
            } else if (workoutName.includes("recup") || notes.includes("recup") || workoutName.includes("easy") || workoutName.includes("recovery")) {
              workoutType = "recuperation";
            } else if (avgHR > 165 || workoutName.includes("tempo") || workoutName.includes("seuil") || workoutName.includes("threshold")) {
              workoutType = "seuil";
            } else if (workout.type === "cycle") {
              workoutType = "cycle";
            }

            const typeConfig = WORKOUT_TYPES[workoutType] || WORKOUT_TYPES.endurance;
            const TypeIcon = typeConfig.icon;

            return (
              <Link
                key={workout.id}
                to={`/workout/${workout.id}`}
                className="workout-list-item animate-in"
                style={{ animationDelay: `${index * 50}ms` }}
              >
                <div
                  className="workout-icon"
                  style={{
                    background: `${typeConfig.color}20`,
                    color: typeConfig.color,
                  }}
                >
                  <TypeIcon className="w-5 h-5" />
                </div>

                <div className="workout-info">
                  <p className="workout-type-name">{t(`workoutTypes.${workoutType}`)}</p>
                  <div className="workout-stats">
                    <span>{formatDistance(workout.distance_km || 0, { unitSystem })}</span>
                    <span className="dot" />
                    <span>{formatPaceUnits((workout.avg_pace_min_km || 0) * 60, { unitSystem })}</span>
                    {workout.avg_heart_rate && (
                      <>
                        <span className="dot" />
                        <span>{t("dashboard.hrLabel")} {workout.avg_heart_rate}</span>
                      </>
                    )}
                  </div>
                </div>

                <span className="workout-date">
                  {getRelativeDate(workout.date, t, lang === "fr" ? "fr-FR" : "en-US")}
                </span>

                <ChevronRight className="workout-arrow w-4 h-4" />
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

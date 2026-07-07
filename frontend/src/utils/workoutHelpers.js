import { Bike, Footprints } from "lucide-react";

export const getWorkoutIcon = (type) => {
  const iconMap = {
    cycle: Bike,
    run: Footprints,
  };
  return iconMap[type] || Footprints;
};

export const formatDuration = (minutes) => {
  if (!minutes) return "--";
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) return `${hrs}h ${mins}m`;
  return `${mins}m`;
};

export const formatDate = (dateStr, locale, options = {}) => {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  const defaultOptions = { month: "short", day: "numeric", ...options };
  return date.toLocaleDateString(locale, defaultOptions);
};

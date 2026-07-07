// Centralized unit system utilities for distances, pace, speed and elevation.
// All internal data is expected in metric:
// - distance: kilometers
// - speed: km/h
// - elevation: meters
// Conversions are done only for display.

export const UNIT_SYSTEM_KEY = "cardiocoach_unit_system";

// Detect device region and return a default unit system ("metric" | "imperial")
export const detectDeviceUnitSystem = () => {
  if (typeof window === "undefined") {
    return "metric";
  }

  try {
    const locale =
      (window.navigator.language ||
        window.navigator.userLanguage ||
        "").toLowerCase();

    // US or UK -> imperial
    if (locale.startsWith("en-us") || locale.startsWith("en-gb") || locale.endsWith("-us") || locale.endsWith("-gb")) {
      return "imperial";
    }
  } catch {
    // Ignore detection errors and fallback to metric
  }

  // Default
  return "metric";
};

// Get the effective unit system following the priority:
// 1) explicit choice in localStorage
// 2) device region
// 3) metric (default)
export const getUnitSystem = () => {
  if (typeof window === "undefined") {
    return "metric";
  }

  try {
    const stored = window.localStorage.getItem(UNIT_SYSTEM_KEY);
    if (stored === "metric" || stored === "imperial") {
      return stored;
    }
  } catch {
    // Ignore storage errors
  }

  return detectDeviceUnitSystem();
};

export const setUnitSystem = (system) => {
  if (typeof window === "undefined") return;
  if (system !== "metric" && system !== "imperial") return;

  try {
    window.localStorage.setItem(UNIT_SYSTEM_KEY, system);
  } catch {
    // Ignore storage errors
  }
};

// --- Conversion helpers (inputs always metric) ---

export const convertDistance = (km, unitSystem) => {
  if (km == null || Number.isNaN(km)) return 0;
  if (unitSystem === "imperial") {
    return km * 0.621371;
  }
  return km;
};

// secondsPerKm: number of seconds to cover 1 km
export const convertPace = (secondsPerKm, unitSystem) => {
  if (secondsPerKm == null || Number.isNaN(secondsPerKm) || secondsPerKm <= 0) {
    return null;
  }

  if (unitSystem === "imperial") {
    // 1 mile = 1.60934 km
    const secondsPerMile = secondsPerKm * 1.60934;
    return secondsPerMile;
  }

  return secondsPerKm;
};

export const convertSpeed = (kmh, unitSystem) => {
  if (kmh == null || Number.isNaN(kmh)) return 0;
  if (unitSystem === "imperial") {
    return kmh * 0.621371;
  }
  return kmh;
};

export const convertElevation = (meters, unitSystem) => {
  if (meters == null || Number.isNaN(meters)) return 0;
  if (unitSystem === "imperial") {
    return meters * 3.28084;
  }
  return meters;
};

// --- Formatting helpers: automatically read current unit system ---

const pad2 = (value) => value.toString().padStart(2, "0");

export const formatDistance = (km, options = {}) => {
  const unitSystem = options.unitSystem || getUnitSystem();
  const value = convertDistance(km, unitSystem);
  const rounded =
    value >= 10 ? value.toFixed(1) : value.toFixed(2); // more precision on small distances
  const unit = unitSystem === "imperial" ? "mi" : "km";
  return `${rounded} ${unit}`;
};

// secondsPerKm: internal metric pace expressed in seconds per km
export const formatPace = (secondsPerKm, options = {}) => {
  const unitSystem = options.unitSystem || getUnitSystem();
  const convertedSeconds = convertPace(secondsPerKm, unitSystem);
  if (!convertedSeconds) return "--";

  const mins = Math.floor(convertedSeconds / 60);
  const secs = Math.round(convertedSeconds - mins * 60);
  const unit = unitSystem === "imperial" ? "/mi" : "/km";
  return `${mins}:${pad2(secs)} ${unit}`;
};

// kmh: internal metric speed in km/h
export const formatSpeed = (kmh, options = {}) => {
  const unitSystem = options.unitSystem || getUnitSystem();
  const value = convertSpeed(kmh, unitSystem);
  const rounded = value.toFixed(1);
  const unit = unitSystem === "imperial" ? "mph" : "km/h";
  return `${rounded} ${unit}`;
};

// meters: internal elevation in meters
export const formatElevation = (meters, options = {}) => {
  const unitSystem = options.unitSystem || getUnitSystem();
  const value = convertElevation(meters, unitSystem);
  const rounded = Math.round(value);
  const unit = unitSystem === "imperial" ? "ft" : "m";
  return `${rounded} ${unit}`;
};


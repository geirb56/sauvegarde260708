import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import StructuredWorkoutView, {
  formatStructuredDistance,
  formatStructuredDuration,
  formatStructuredPace,
  getPrimaryStructuredPace,
  getStructuredSummary,
} from "@/components/training/StructuredWorkoutView";

const labels = {
  "trainingV2.structured.steps.warmup": "Warm-up",
  "trainingV2.structured.steps.work": "Work",
  "trainingV2.structured.steps.recovery": "Recovery",
  "trainingV2.structured.steps.cooldown": "Cool-down",
  "trainingV2.structured.steps.continuous": "Session",
  "trainingV2.structured.recovery": "Recovery",
  "trainingV2.structured.recoveryShort": "Rec.",
};
const t = (key) => labels[key] || key;

const structured = {
  workout_type: "quality",
  quality_kind: "threshold_intervals",
  target_basis: "distance",
  total_distance_km: 9,
  total_duration_minutes: null,
  steps: [
    {
      step_type: "warmup", repetitions: 1, distance_m: 2000, duration_seconds: null,
      recovery: null, pace_zone: "E", pace_min_per_km: null,
      pace_min_per_km_min: 6.1667, pace_min_per_km_max: 6.5833,
    },
    {
      step_type: "work", repetitions: 3, distance_m: 2000, duration_seconds: null,
      recovery: { kind: "jog", duration_seconds: 120, distance_m: null, count: 2 },
      pace_zone: "T", pace_min_per_km: 5.1333,
      pace_min_per_km_min: null, pace_min_per_km_max: null,
    },
    {
      step_type: "cooldown", repetitions: 1, distance_m: 1000, duration_seconds: null,
      recovery: null, pace_zone: "E", pace_min_per_km: null,
      pace_min_per_km_min: 6.1667, pace_min_per_km_max: 6.5833,
    },
  ],
};

describe("StructuredWorkoutView", () => {
  test("renders warmup, work, recovery, and cooldown from the backend contract", () => {
    render(<StructuredWorkoutView structured={structured} unitSystem="metric" t={t} />);
    expect(screen.getByTestId("structured-step-warmup")).toHaveTextContent("Warm-up");
    expect(screen.getByTestId("structured-step-work")).toHaveTextContent("Work");
    expect(screen.getByTestId("structured-recovery")).toHaveTextContent("Recovery");
    expect(screen.getByTestId("structured-step-cooldown")).toHaveTextContent("Cool-down");
  });

  test("renders repetitions once instead of duplicating work blocks", () => {
    render(<StructuredWorkoutView structured={structured} unitSystem="metric" t={t} />);
    expect(screen.getByTestId("structured-step-work")).toHaveTextContent("3 × 2.00 km");
    expect(screen.getAllByTestId("structured-step-work")).toHaveLength(1);
  });

  test("respects recovery count and time", () => {
    render(<StructuredWorkoutView structured={structured} unitSystem="metric" t={t} />);
    expect(screen.getByTestId("structured-recovery")).toHaveTextContent("2 × Recovery · 2 min");
  });

  test("renders distance recovery when supplied", () => {
    const value = JSON.parse(JSON.stringify(structured));
    value.steps[1].recovery = { kind: "jog", duration_seconds: null, distance_m: 400, count: 2 };
    render(<StructuredWorkoutView structured={value} unitSystem="metric" t={t} />);
    expect(screen.getByTestId("structured-recovery")).toHaveTextContent("400 m");
  });

  test("does not render a recovery with a backend count of zero", () => {
    const value = JSON.parse(JSON.stringify(structured));
    value.steps[1].recovery.count = 0;
    render(<StructuredWorkoutView structured={value} unitSystem="metric" t={t} />);
    expect(screen.queryByTestId("structured-recovery")).not.toBeInTheDocument();
  });

  test("formats single pace", () => {
    expect(formatStructuredPace(structured.steps[1], "metric")).toBe("5:08 /km");
  });

  test("formats pace range", () => {
    expect(formatStructuredPace(structured.steps[0], "metric")).toBe("6:10–6:35 /km");
  });

  test("does not invent missing pace", () => {
    expect(formatStructuredPace({ pace_zone: "T" }, "metric")).toBeNull();
  });

  test("formats metric distances using metres and kilometres", () => {
    expect(formatStructuredDistance(400, "metric")).toBe("400 m");
    expect(formatStructuredDistance(2000, "metric")).toBe("2.00 km");
  });

  test("formats imperial distances and paces", () => {
    expect(formatStructuredDistance(400, "imperial")).toBe("437 yd");
    expect(formatStructuredDistance(2000, "imperial")).toBe("1.24 mi");
    expect(formatStructuredPace(structured.steps[1], "imperial")).toMatch(/\/mi$/);
  });

  test("formats seconds, minutes, and hours", () => {
    expect(formatStructuredDuration(45)).toBe("45 s");
    expect(formatStructuredDuration(60)).toBe("1 min");
    expect(formatStructuredDuration(90)).toBe("1:30");
    expect(formatStructuredDuration(120)).toBe("2 min");
    expect(formatStructuredDuration(150)).toBe("2:30");
    expect(formatStructuredDuration(3600)).toBe("1 h");
    expect(formatStructuredDuration(3601)).toBe("1 h 00:01");
    expect(formatStructuredDuration(3900)).toBe("1 h 05");
  });

  test("renders the exact PR234 threshold recovery calibration without rounding", () => {
    const value = JSON.parse(JSON.stringify(structured));
    value.steps[1].recovery.duration_seconds = 90;
    render(<StructuredWorkoutView structured={value} unitSystem="metric" t={t} />);

    expect(screen.getByTestId("structured-recovery")).toHaveTextContent("1:30");
    expect(screen.getByTestId("structured-recovery")).not.toHaveTextContent("2 min");
  });

  test("uses the work step as the primary pace", () => {
    expect(getPrimaryStructuredPace(structured, "metric")).toBe("5:08 /km");
  });

  test("compact summary is sourced only from structured work and recovery", () => {
    expect(getStructuredSummary(structured, "metric", t)).toBe("3 × 2.00 km · 2 × Rec. 2 min");
  });

  test("renders nothing when no structured contract is supplied", () => {
    const { container } = render(<StructuredWorkoutView structured={null} unitSystem="metric" t={t} />);
    expect(container).toBeEmptyDOMElement();
  });
});

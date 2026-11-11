import { describeMarker, projectSynthesisMarker } from "@/lib/workoutMarkers";
import { translations } from "@/lib/i18n";

const pace = (difference, extra = {}) => ({
  code: "coach.history.pace", text: "validated text",
  evidence: {
    pace_sample_count: 5, pace_difference_sec_per_km: difference,
    current_pace_min_km: 6.9333, baseline_pace_min_km: 7.1667, ...extra,
  },
});
const hr = (difference) => ({
  code: "coach.history.hr", text: "validated text",
  evidence: {
    hr_sample_count: 4, heart_rate_difference_bpm: difference,
    current_heart_rate_bpm: 135, baseline_heart_rate_bpm: 138,
  },
});
const describe_ = (item, lang = "en") => {
  const text = (key) => translations[lang].workoutNarrative[key];
  return describeMarker(projectSynthesisMarker(item), lang, text);
};

describe("C419 marker projection", () => {
  test("faster pace keeps the fractional engine differential (fr)", () => {
    const view = describe_(pace(-14.2), "fr");
    expect(view.label).toBe("5 sorties de distance comparable");
    expect(view.headline).toBe("14,2 s/km plus rapide que tes références");
    expect(view.detail).toBe("Séance : 6:56/km · Références : 7:10/km");
  });

  test("slower and identical pace follow the sign", () => {
    expect(describe_(pace(8.5)).headline).toBe("8.5 s/km slower than your references");
    expect(describe_(pace(0)).headline).toBe("Same pace as your references");
    expect(describe_(pace(-3), "es").headline).toBe("3 s/km más rápido que tus referencias");
  });

  test("the differential is not recomputed from the rounded paces", () => {
    expect(projectSynthesisMarker(pace(-14.2)).difference).toBe(-14.2);
  });

  test("heart rate is not presented as a pace", () => {
    const view = describe_(hr(-3));
    expect(view.headline).toBe("Average heart rate 3 bpm lower than your references");
    expect(view.detail).toBe("This session: 135 bpm · References: 138 bpm");
    expect(view.headline).not.toMatch(/s\/km/);
  });

  test("incomplete evidence stays textual", () => {
    expect(projectSynthesisMarker(pace(-14.2, { baseline_pace_min_km: undefined })).kind).toBe("text");
    expect(projectSynthesisMarker(pace(undefined)).kind).toBe("text");
    expect(projectSynthesisMarker(pace(-1, { pace_sample_count: 0 })).kind).toBe("text");
    expect(projectSynthesisMarker({ code: "fact.pace_change", text: "x", evidence: { a: 1 } }).kind).toBe("text");
    expect(projectSynthesisMarker(null).kind).toBe("text");
  });
});

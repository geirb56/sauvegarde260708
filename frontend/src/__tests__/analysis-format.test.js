import { formatAnalysisNumber, formatAnalysisDelta } from "@/lib/analysisFormat";
import { getWorkoutNarrative } from "@/components/workout/NarrativeWorkoutAnalysis";

describe("workout analysis display formatting", () => {
  test.each([["fr", "6,6"], ["en", "6.6"], ["es", "6,6"]])(
    "formats finite evidence for %s without changing the metric", (lang, expected) => {
      expect(formatAnalysisNumber(6.5621, lang)).toBe(expected);
      expect(formatAnalysisNumber(6.5621, lang, 2)).toBe(lang === "en" ? "6.56" : "6,56");
      expect(formatAnalysisDelta(6.5621, lang, "s/km")).toBe(`+${expected} s/km`);
    },
  );
  test.each([null, undefined, NaN, Infinity, -Infinity, "6.6"])("does not invent a value for %s", (value) => {
    expect(formatAnalysisNumber(value, "fr")).toBe("--");
    expect(formatAnalysisDelta(value, "fr", "bpm")).toBe("--");
  });
  test("zero is data, and rounding does not produce negative zero", () => {
    expect(formatAnalysisNumber(0, "fr")).toBe("0");
    expect(formatAnalysisNumber(-0.001, "fr")).toBe("0");
    expect(formatAnalysisDelta(-0.001, "fr", "s/km")).toBe("0 s/km");
    expect(formatAnalysisDelta(0.001, "fr", "s/km")).toBe("0 s/km");
  });
  test("can preserve existing unit display precision while localizing", () => {
    expect(formatAnalysisNumber(10, "en", 1, 1)).toBe("10.0");
    expect(formatAnalysisNumber(10, "fr", 1, 1)).toBe("10,0");
    expect(formatAnalysisNumber(6, "es", 2, 2)).toBe("6,00");
  });
});

describe("narrative contract selection", () => {
  const narrative = {
    headline: "Séance",
    analysis: "La valeur brute 16.5621 s/km reste dans la phrase.",
    interpretation: "Votre historique reste limité.",
    recommendation: null,
    language: "fr",
    generation_mode: "deterministic_fallback",
  };
  test("keeps backend sentences and tone intact", () => {
    expect(getWorkoutNarrative({ narrative_coach_v3: narrative }, "fr")).toBe(narrative);
  });
  test.each([
    null, {}, { ...narrative, generation_mode: "none" }, { ...narrative, language: "en" },
    { ...narrative, headline: "" }, { ...narrative, analysis: " " }, { ...narrative, interpretation: 42 },
  ])("falls back on absent, wrong-language or incomplete data", (candidate) => {
    expect(getWorkoutNarrative({ narrative_coach_v3: candidate }, "fr")).toBeNull();
  });
});

describe("C400 coach comment selection", () => {
  const { getCoachComment } = require("@/components/workout/NarrativeWorkoutAnalysis");
  const ok = { status: "generated", language: "fr", source: "coach_c396", text: " Bonne sortie. " };
  test("only a generated, same-language C396 comment is shown", () => {
    expect(getCoachComment({ coach_comment: ok }, "fr")).toBe("Bonne sortie.");
    expect(getCoachComment({ coach_comment: ok }, "en")).toBeNull();
    expect(getCoachComment({ coach_comment: { ...ok, status: "fallback" } }, "fr")).toBeNull();
    expect(getCoachComment({ coach_comment: { ...ok, source: "other" } }, "fr")).toBeNull();
    expect(getCoachComment({ coach_comment: { ...ok, text: " " } }, "fr")).toBeNull();
    expect(getCoachComment({}, "fr")).toBeNull();
  });
});

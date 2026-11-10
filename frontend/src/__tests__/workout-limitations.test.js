import { mergeWorkoutLimitations, splitWorkoutLimitations } from "@/lib/workoutLimitations";
import { translations } from "@/lib/i18n";

const v2History = {
  en: "This difference describes these sessions; it cannot alone establish a change in fitness or judge execution.",
  fr: "Cet écart décrit ces séances ; il ne suffit pas à conclure à un changement de forme ni à juger l’exécution.",
  es: "Esta diferencia describe esas sesiones; por sí sola no permite establecer un cambio de forma ni juzgar la ejecución.",
};
const v3History = {
  en: "Historical comparisons are observational, not proof of a physiological change.",
  fr: "Les comparaisons historiques sont des observations, pas la preuve d'un changement physiologique.",
  es: "Las comparaciones históricas son observaciones, no pruebas de un cambio fisiológico.",
};

test("merges identical limitations with multiple spaces", () => {
  const merged = mergeWorkoutLimitations({
    synthesis: [{ code: "x", text: "Same   limit here." }],
    narrative: ["Same limit here."],
  });
  expect(merged).toHaveLength(1);
});

test("merges identical limitations with different line breaks, in both directions", () => {
  expect(mergeWorkoutLimitations({
    synthesis: [{ code: "x", text: "Same limit\nhere." }], narrative: ["Same limit here."],
  })).toHaveLength(1);
  expect(mergeWorkoutLimitations({
    synthesis: [{ code: "x", text: "Same limit here." }], narrative: ["Same \n limit\r\n  here."],
  })).toHaveLength(1);
  expect(mergeWorkoutLimitations({ narrative: ["A  b", "A\nb"] })).toHaveLength(1);
});

test("keeps V2 and V3 provenance and the original text for display", () => {
  const [item] = mergeWorkoutLimitations({
    synthesis: [{ code: "x", text: "Same  limit." }], narrative: ["Same limit.", "Same limit."],
  });
  expect(item.sources).toEqual(["v2", "v3"]);
  expect(item.text).toBe("Same  limit.");
});

test("does not merge distinct limitations and keeps V2 then V3 order", () => {
  const merged = mergeWorkoutLimitations({
    synthesis: [{ code: "a", text: "First limit." }], narrative: ["Second limit.", "Third limit."],
  });
  expect(merged.map((item) => item.text)).toEqual(["First limit.", "Second limit.", "Third limit."]);
  expect(merged.map((item) => item.sources)).toEqual([["v2"], ["v3"], ["v3"]]);
  const { essential, rest } = splitWorkoutLimitations(merged);
  expect(essential.text).toBe("First limit.");
  expect(rest.map((item) => item.text)).toEqual(["Second limit.", "Third limit."]);
});

test.each(["fr", "en", "es"])("preserves the explicit equivalent category in %s", (language) => {
  const merged = mergeWorkoutLimitations({
    synthesis: [{ code: "synthesis.history_descriptive", text: v2History[language] }],
    narrative: [v3History[language]],
  });
  expect(merged).toHaveLength(1);
  expect(merged[0].sources).toEqual(["v2", "v3"]);
  expect(merged[0].text).toBe(v2History[language]);
  // Also matched by text alone when the V2 code is absent, with extra whitespace.
  expect(mergeWorkoutLimitations({
    synthesis: [{ code: "other", text: v2History[language].replace(" ", "  ") }], narrative: [v3History[language]],
  })).toHaveLength(1);
});

test("does not merge unrelated limitations across categories", () => {
  expect(mergeWorkoutLimitations({
    synthesis: [{ code: "synthesis.hr_observation", text: "HR limit." }], narrative: [v3History.en],
  })).toHaveLength(2);
});

test("language packs still define the labels used for limitations", () => {
  ["fr", "en", "es"].forEach((language) => {
    expect(translations[language].workoutNarrative.methodLimits).toBeTruthy();
  });
});

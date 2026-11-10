// C417: one presentation of the limitations coming from V2 session_synthesis and V3 narrative.
// Nothing is recalculated. Two limitations are merged only when they are strictly identical or
// when both appear in the explicit table of backend sentences below (provable categories).
const norm = (text) => text.trim().replace(/\s+/g, " ");

// Backend `trend.caution` (narrative_coach_v3) and `synthesis.history_descriptive`
// (coach_session_synthesis) state the same scientific restriction.
const HISTORY_DESCRIPTIVE = "history_descriptive";
const CATEGORY_BY_CODE = { "synthesis.history_descriptive": HISTORY_DESCRIPTIVE };
const CATEGORY_BY_TEXT = new Map([
  "Historical comparisons are observational, not proof of a physiological change.",
  "Les comparaisons historiques sont des observations, pas la preuve d'un changement physiologique.",
  "Las comparaciones históricas son observaciones, no pruebas de un cambio fisiológico.",
  "This difference describes these sessions; it cannot alone establish a change in fitness or judge execution.",
  "Cet écart décrit ces séances ; il ne suffit pas à conclure à un changement de forme ni à juger l’exécution.",
  "Esta diferencia describe esas sesiones; por sí sola no permite establecer un cambio de forma ni juzgar la ejecución.",
].map((text) => [norm(text), HISTORY_DESCRIPTIVE]));

const hasText = (value) => typeof value === "string" && value.trim().length > 0;

// Returns [{ key, text, category, sources: ["v2" | "v3"] }] ordered V2 first, then V3.
export const mergeWorkoutLimitations = ({ synthesis = [], narrative = [] } = {}) => {
  const merged = [];
  const add = (text, category, source) => {
    if (!hasText(text)) return;
    const clean = norm(text);
    const cat = category || CATEGORY_BY_TEXT.get(clean) || null;
    const existing = merged.find((item) => item.text === clean || (cat && item.category === cat));
    if (existing) {
      if (!existing.sources.includes(source)) existing.sources.push(source);
      return;
    }
    merged.push({ key: `${source}:${merged.length}`, text: hasText(text) ? text.trim() : clean, category: cat, sources: [source] });
  };
  (Array.isArray(synthesis) ? synthesis : []).forEach((item) =>
    add(item?.text, CATEGORY_BY_CODE[item?.code?.trim?.()], "v2"));
  (Array.isArray(narrative) ? narrative : []).forEach((text) => add(text, null, "v3"));
  return merged;
};

// At most one limitation stays in the main flow; every other one goes to the details.
export const splitWorkoutLimitations = (limitations) => ({
  essential: limitations[0] || null,
  rest: limitations.slice(1),
});

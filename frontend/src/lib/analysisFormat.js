const locales = { fr: "fr-FR", en: "en-US", es: "es-ES" };

export const formatAnalysisNumber = (value, lang = "en", precision = 1, minimumFractionDigits = 0) => {
  if (!Number.isFinite(value)) return "--";
  const rounded = Number(value.toFixed(precision));
  return new Intl.NumberFormat(locales[lang] || locales.en, {
    maximumFractionDigits: precision,
    minimumFractionDigits,
    useGrouping: false,
  }).format(Object.is(rounded, -0) ? 0 : rounded);
};

export const formatAnalysisDelta = (value, lang, unit, precision = 1) =>
  Number.isFinite(value)
    ? `${value > 0 && Number(value.toFixed(precision)) !== 0 ? "+" : ""}${formatAnalysisNumber(value, lang, precision)} ${unit}`
    : "--";

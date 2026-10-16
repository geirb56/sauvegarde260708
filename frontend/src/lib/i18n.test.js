import { getAppLanguage, getTranslation, translations, LANGUAGE_STORAGE_KEY } from "./i18n";

describe("i18n auth coverage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  test.each(["fr", "en", "es"])("%s removes only pace/prediction confidence translations", (lang) => {
    const labels = translations[lang];
    expect(labels.trainingV2).not.toHaveProperty("confidence");
    expect(labels.trainingV2).not.toHaveProperty("pacesConfidence");
    ["confidenceLabel", "confidenceHigh", "confidenceMedium", "confidenceLow", "confidenceInsufficient"].forEach((key) => {
      expect(labels.progressExtended).not.toHaveProperty(key);
    });
    ["trainingV2", "progressExtended"].forEach((section) => {
      expect(Object.keys(labels[section]).sort()).toEqual(Object.keys(translations.en[section]).sort());
      Object.entries(labels[section]).forEach(([key, value]) => {
        if (typeof value === "string") {
          expect(value.trim()).not.toBe("");
          expect(getTranslation(lang, `${section}.${key}`)).toBe(value);
        }
      });
    });
    expect(labels.progress.confidence).toEqual(expect.any(String));
    expect(labels.progress.confidenceLevels).toEqual(expect.objectContaining({
      high: expect.any(String), medium: expect.any(String), low: expect.any(String),
    }));
    expect(labels.trainingV2.confidenceValues).toEqual(expect.objectContaining({
      high: expect.any(String), medium: expect.any(String), low: expect.any(String),
    }));
  });

  test("WorkoutDetail keys and interpolation placeholders match in FR/EN/ES", () => {
    const reference = translations.en.workoutDetailExtended;
    ["fr", "en", "es"].forEach((language) => {
      const labels = translations[language].workoutDetailExtended;
      expect(Object.keys(labels).sort()).toEqual(Object.keys(reference).sort());
      Object.entries(reference).forEach(([key, value]) => {
        expect(labels[key]).toEqual(expect.any(String));
        expect(labels[key].trim()).not.toBe("");
        expect((labels[key].match(/\{[^}]+\}/g) || []).sort()).toEqual((value.match(/\{[^}]+\}/g) || []).sort());
        expect(getTranslation(language, `workoutDetailExtended.${key}`)).toBe(labels[key]);
      });
    });
  });

  test("auth keys exist in all supported languages", () => {
    const requiredKeys = [
      "auth.signIn",
      "auth.createAccount",
      "auth.forgotPassword",
      "auth.resetPassword",
      "auth.continueWithGoogle",
      "auth.googleNotConfigured",
      "auth.logout",
    ];

    Object.keys(translations).forEach((lang) => {
      requiredKeys.forEach((key) => {
        expect(getTranslation(lang, key)).not.toBe(key);
      });
    });
  });

  test("prefers persisted language and falls back to browser locale", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    expect(getAppLanguage()).toBe("fr");

    window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    Object.defineProperty(window.navigator, "language", {
      configurable: true,
      value: "es-ES",
    });
    Object.defineProperty(window.navigator, "languages", {
      configurable: true,
      value: ["es-ES", "en-US"],
    });
    expect(getAppLanguage()).toBe("es");
  });
});

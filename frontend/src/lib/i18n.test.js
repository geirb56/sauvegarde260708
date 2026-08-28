import { getAppLanguage, getTranslation, translations, LANGUAGE_STORAGE_KEY } from "./i18n";

describe("i18n auth coverage", () => {
  beforeEach(() => {
    window.localStorage.clear();
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

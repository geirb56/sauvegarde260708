import { createContext, useContext, useState, useEffect } from "react";
import { translations, LANGUAGE_STORAGE_KEY, getAppLanguage } from "@/lib/i18n";

const LanguageContext = createContext();

export const LanguageProvider = ({ children }) => {
  const [lang, setLang] = useState(() => getAppLanguage());

  useEffect(() => {
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
      } catch {
        // Ignore storage/write errors
      }
    }
  }, [lang]);

  const t = (path) => {
    const keys = path.split(".");
    let result = translations[lang];
    for (const key of keys) {
      if (result && result[key] !== undefined) {
        result = result[key];
      } else {
        // Fallback to English
        result = translations.en;
        for (const k of keys) {
          if (result && result[k] !== undefined) {
            result = result[k];
          } else {
            return path;
          }
        }
        break;
      }
    }
    return result;
  };

  const toggleLanguage = () => {
    setLang((prev) => {
      if (prev === "en") return "fr";
      if (prev === "fr") return "es";
      return "en";
    });
  };

  return (
    <LanguageContext.Provider value={{ lang, setLang, t, toggleLanguage }}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within LanguageProvider");
  }
  return context;
};

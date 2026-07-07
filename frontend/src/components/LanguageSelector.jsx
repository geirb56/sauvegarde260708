import { Card, CardContent } from "@/components/ui/card";
import { Globe } from "lucide-react";

export const LanguageSelector = ({ lang, onLangChange, t }) => {
  return (
    <Card className="bg-card border-border">
      <CardContent className="p-6">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0 rounded-sm">
            <Globe className="w-5 h-5 text-primary" />
          </div>
          <div className="flex-1">
            <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
              {t("settings.language")}
            </h2>
            <p className="font-mono text-xs text-muted-foreground mb-4">
              {t("settings.languageDesc")}
            </p>

            <div className="flex gap-3">
              <button
                onClick={() => onLangChange("en")}
                className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors rounded-sm ${
                  lang === "en"
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                }`}
              >
                <span className="block text-lg mb-1">EN</span>
                <span className="block text-xs">{t("settings.english")}</span>
              </button>

              <button
                onClick={() => onLangChange("fr")}
                className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors rounded-sm ${
                  lang === "fr"
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                }`}
              >
                <span className="block text-lg mb-1">FR</span>
                <span className="block text-xs">{t("settings.french")}</span>
              </button>

              <button
                onClick={() => onLangChange("es")}
                className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors rounded-sm ${
                  lang === "es"
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                }`}
              >
                <span className="block text-lg mb-1">ES</span>
                <span className="block text-xs">{t("settings.spanish")}</span>
              </button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

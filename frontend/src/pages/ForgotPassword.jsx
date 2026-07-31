import { useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, CheckCircle } from "lucide-react";
import { API_BASE_URL } from "@/config";

export default function ForgotPassword() {
  const { t } = useLanguage();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/auth/forgot-password`, { email: email.trim().toLowerCase() });
      setSubmitted(true);
    } catch {
      setError(t("auth.somethingWentWrong"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-bold">{t("auth.title")}</CardTitle>
          <p className="text-muted-foreground text-sm mt-1">{t("auth.resetPassword")}</p>
        </CardHeader>
        <CardContent>
          {submitted ? (
            <div className="text-center space-y-3">
              <CheckCircle className="w-10 h-10 text-green-500 mx-auto" />
              <p className="text-sm text-muted-foreground">
                {t("auth.emailSentMessage")}
              </p>
              <Link to="/login" className="text-primary hover:underline text-sm block">
                {t("auth.backToSignIn")}
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="email" className="text-sm font-medium block mb-1">
                  {t("auth.emailLabel")}
                </label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={t("auth.emailPlaceholder")}
                  required
                  disabled={loading}
                />
              </div>

              {error && (
                <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{error}</p>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    {t("auth.sending")}
                  </>
                ) : (
                  t("auth.sendResetLink")
                )}
              </Button>

              <p className="text-center text-sm text-muted-foreground">
                <Link to="/login" className="text-primary hover:underline">
                  {t("auth.backToSignIn")}
                </Link>
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useLanguage } from "@/context/LanguageContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import OAuthButtons from "@/components/OAuthButtons";
import { mapAuthErrorDetail } from "@/lib/authErrors";

const HAS_OAUTH_CONFIG = Boolean(
  process.env.REACT_APP_GOOGLE_CLIENT_ID || process.env.REACT_APP_APPLE_CLIENT_ID
);

export default function Login() {
  const { login } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const result = await login(email.trim().toLowerCase(), password);
    setLoading(false);

    if (result.ok) {
      toast.success(t("auth.welcomeBack"));
      navigate("/", { replace: true });
    } else {
      setError(mapAuthErrorDetail(t, result.errorDetail, "auth.invalidEmailOrPassword"));
    }
  };

  const handleOAuthSuccess = () => {
    toast.success(t("auth.welcomeBack"));
    navigate("/", { replace: true });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-bold">{t("auth.title")}</CardTitle>
          <p className="text-muted-foreground text-sm mt-1">{t("auth.signIn")}</p>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <OAuthButtons
              onSuccess={handleOAuthSuccess}
              onError={(msg) => setError(msg)}
            />

            {HAS_OAUTH_CONFIG && (
              <div className="relative flex items-center">
                <div className="flex-1 border-t border-border" />
                <span className="mx-3 text-xs text-muted-foreground">{t("auth.orDivider")}</span>
                <div className="flex-1 border-t border-border" />
              </div>
            )}

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

              <div>
                <label htmlFor="password" className="text-sm font-medium block mb-1">
                  {t("auth.passwordLabel")}
                </label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t("auth.passwordPlaceholder")}
                    required
                    disabled={loading}
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? t("auth.hidePassword") : t("auth.showPassword")}
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{error}</p>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    {t("auth.signingIn")}
                  </>
                ) : (
                  t("auth.signInButton")
                )}
              </Button>

              <div className="text-center text-sm text-muted-foreground space-y-2">
                <div>
                  <Link
                    to="/forgot-password"
                    className="text-primary hover:underline"
                  >
                    {t("auth.forgotPassword")}
                  </Link>
                </div>
                <div>
                  {t("auth.noAccount")}{" "}
                  <Link to="/register" className="text-primary hover:underline">
                    {t("auth.signUp")}
                  </Link>
                </div>
              </div>
            </form>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

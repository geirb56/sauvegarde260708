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

export default function Register() {
  const { register } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError(t("auth.passwordsDoNotMatch"));
      return;
    }

    if (password.length < 8) {
      setError(t("auth.passwordTooShort"));
      return;
    }

    setLoading(true);
    const result = await register(email.trim().toLowerCase(), password);
    setLoading(false);

    if (result.ok) {
      toast.success(t("auth.accountCreated"));
      navigate("/", { replace: true });
    } else {
      setError(result.error);
    }
  };

  const handleOAuthSuccess = () => {
    toast.success(t("auth.accountCreated"));
    navigate("/", { replace: true });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-bold">{t("auth.title")}</CardTitle>
          <p className="text-muted-foreground text-sm mt-1">{t("auth.createAccount")}</p>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <OAuthButtons
              onSuccess={handleOAuthSuccess}
              onError={(msg) => setError(msg)}
            />

            <div className="relative flex items-center">
              <div className="flex-1 border-t border-border" />
              <span className="mx-3 text-xs text-muted-foreground">{t("auth.orDivider")}</span>
              <div className="flex-1 border-t border-border" />
            </div>

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
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t("auth.passwordPlaceholder")}
                    required
                    minLength={8}
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
                <p className="text-xs text-muted-foreground mt-1">
                  {t("auth.passwordHint")}
                </p>
              </div>

              <div>
                <label htmlFor="confirmPassword" className="text-sm font-medium block mb-1">
                  {t("auth.confirmPasswordLabel")}
                </label>
                <Input
                  id="confirmPassword"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder={t("auth.passwordPlaceholder")}
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
                    {t("auth.creatingAccount")}
                  </>
                ) : (
                  t("auth.createAccountButton")
                )}
              </Button>

              <p className="text-center text-sm text-muted-foreground">
                {t("auth.alreadyHaveAccount")}{" "}
                <Link to="/login" className="text-primary hover:underline">
                  {t("auth.signInButton")}
                </Link>
              </p>
            </form>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}


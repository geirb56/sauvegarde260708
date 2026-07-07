import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Activity, Loader2, Check, X, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import axios from "axios";
import { API_BASE } from "@/utils/constants";

// Default user identifier — matches the convention used across CardioCoach.
const USER_ID = "default";

/**
 * TerraConnection — UI card for managing the Terra wearable integration.
 *
 * Terra wearable connection card.  Uses token-based auth: the user
 * pastes their Terra user token and it is stored on the backend via
 * POST /terra/connect.
 *
 * Props:
 *   lang           — current locale ("fr" | "en")
 *   t              — i18n translation function
 *   onStatusChange — optional callback called with the latest status object
 */
export const TerraConnection = ({ lang, t, onStatusChange }) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [token, setToken] = useState("");

  useEffect(() => {
    loadStatus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadStatus = async () => {
    try {
      const res = await axios.get(`${API_BASE}/terra/status?user_id=${USER_ID}`);
      setStatus(res.data);
      if (onStatusChange) onStatusChange(res.data);
    } catch (error) {
      console.error("Failed to load Terra status:", error);
      setStatus({ connected: false });
    } finally {
      setLoading(false);
    }
  };

  const handleConnect = async () => {
    if (!token.trim()) {
      toast.error(t("terra.tokenRequired"));
      return;
    }
    setConnecting(true);
    try {
      await axios.post(`${API_BASE}/terra/connect?user_id=${USER_ID}`, { token: token.trim() });
      toast.success(t("terra.connected"));
      setToken("");
      loadStatus();
    } catch (error) {
      console.error("Failed to connect Terra:", error);
      toast.error(error.response?.data?.detail || t("terra.connectionFailed"));
    } finally {
      setConnecting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await axios.post(`${API_BASE}/terra/sync?user_id=${USER_ID}`);
      if (res.data.success) {
        toast.success(
          t("terra.syncImported").replace(
            "{count}",
            res.data.synced_count
          )
        );
      }
      loadStatus();
    } catch (error) {
      console.error("Terra sync failed:", error);
      toast.error(t("terra.syncFailed"));
    } finally {
      setSyncing(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await axios.delete(`${API_BASE}/terra/disconnect?user_id=${USER_ID}`);
      setStatus({ connected: false });
      toast.success(t("terra.disconnected"));
    } catch (error) {
      toast.error(t("common.error") || "Error");
    }
  };

  const formatLastSync = (isoString) => {
    if (!isoString) return t("common.never");
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    const locale = lang === "fr" ? "fr-FR" : lang === "es" ? "es-ES" : "en-US";
    if (diffMins < 1) return t("common.justNow");
    if (diffMins < 60)
      return t("common.timeAgoMins").replace("{n}", diffMins);
    if (diffHours < 24)
      return t("common.timeAgoHours").replace("{n}", diffHours);
    if (diffDays < 7)
      return t("common.timeAgoDays").replace("{n}", diffDays);
    return date.toLocaleDateString(locale, { day: "numeric", month: "short" });
  };

  if (loading) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="p-6">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="font-mono text-xs">{t("common.loading")}</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card border-border">
      <CardContent className="p-6">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0 rounded-sm">
            <Activity className="w-5 h-5 text-primary" />
          </div>
          <div className="flex-1">
            <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
              {t("terra.title")}
            </h2>
            <p className="font-mono text-xs text-muted-foreground mb-4">
              {t("terra.description")}
            </p>

            {status?.connected ? (
              <div className="space-y-4">
                <div className="flex items-center gap-2 text-chart-2">
                  <Check className="w-4 h-4 flex-shrink-0" />
                  <span className="font-mono text-xs uppercase tracking-wider">
                    {t("settings.connected")}
                  </span>
                </div>

                <div className="p-3 bg-muted/50 border border-border rounded-sm">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                        {t("settings.lastSync")}
                      </p>
                      <p className="font-mono text-sm">
                        {formatLastSync(status.last_sync)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                        {t("settings.workouts")}
                      </p>
                      <p className="font-mono text-sm">{status.workout_count}</p>
                    </div>
                  </div>
                </div>

                <div className="flex gap-3">
                  <Button
                    onClick={handleSync}
                    disabled={syncing}
                    data-testid="sync-terra"
                    className="flex-1 bg-primary text-white hover:bg-primary/90 rounded-sm uppercase font-bold tracking-wider text-xs h-9"
                  >
                    {syncing ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <RefreshCw className="w-4 h-4" />
                    )}
                    {t("settings.sync")}
                  </Button>
                  <Button
                    onClick={handleDisconnect}
                    variant="ghost"
                    data-testid="disconnect-terra"
                    className="flex-1 text-muted-foreground hover:text-destructive rounded-sm uppercase font-mono text-xs h-9"
                  >
                    {t("settings.disconnect")}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <X className="w-4 h-4 flex-shrink-0" />
                  <span className="font-mono text-xs uppercase tracking-wider">
                    {t("settings.notConnected")}
                  </span>
                </div>
                <Input
                  type="text"
                  placeholder={t("terra.tokenPlaceholder")}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  className="font-mono text-xs h-9 rounded-sm"
                  data-testid="terra-token-input"
                />
                <Button
                  onClick={handleConnect}
                  disabled={connecting || !token.trim()}
                  data-testid="connect-terra"
                  className="w-full bg-primary text-white hover:bg-primary/90 rounded-sm uppercase font-bold tracking-wider text-xs h-9"
                >
                  {connecting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Activity className="w-4 h-4" />
                  )}
                  {t("terra.connect")}
                </Button>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

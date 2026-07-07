import { useState, useEffect } from "react";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/context/LanguageContext";
import { 
  RefreshCw, 
  Loader2,
  CheckCircle,
  Settings2,
  Pause,
  Footprints,
  Bike,
  Heart
} from "lucide-react";
import { toast } from "sonner";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default";

const statusConfig = {
  maintain: {
    icon: CheckCircle,
    color: "text-chart-2",
    bgColor: "bg-chart-2/10",
    borderColor: "border-chart-2/30",
  },
  adjust: {
    icon: Settings2,
    color: "text-chart-3",
    bgColor: "bg-chart-3/10",
    borderColor: "border-chart-3/30",
  },
  hold_steady: {
    icon: Pause,
    color: "text-chart-1",
    bgColor: "bg-chart-1/10",
    borderColor: "border-chart-1/30",
  },
};

const getSessionIcon = (type) => {
  if (!type) return Footprints;
  const t = type.toLowerCase();
  if (t.includes("cycle") || t.includes("bike") || t.includes("velo")) return Bike;
  if (t.includes("recovery") || t.includes("recuperation")) return Heart;
  return Footprints;
};

export default function Guidance() {
  const [guidance, setGuidance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const { t, lang } = useLanguage();

  useEffect(() => {
    loadLatestGuidance();
  }, []);

  const loadLatestGuidance = async () => {
    try {
      const res = await axios.get(`${API}/coach/guidance/latest?user_id=${USER_ID}`);
      setGuidance(res.data);
    } catch (error) {
      console.error("Failed to load guidance:", error);
    } finally {
      setLoading(false);
    }
  };

  const generateGuidance = async () => {
    setGenerating(true);
    try {
      const res = await axios.post(`${API}/coach/guidance`, {
        language: lang,
        user_id: USER_ID
      });
      setGuidance(res.data);
      toast.success(t("guidanceExtended.generated"));
    } catch (error) {
      console.error("Failed to generate guidance:", error);
      toast.error(t("guidanceExtended.generationFailed"));
    } finally {
      setGenerating(false);
    }
  };

  const formatTimeAgo = (isoString) => {
    if (!isoString) return "";
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffMins < 60) return t("common.timeAgoMins").replace("{n}", diffMins);
    if (diffHours < 24) return t("common.timeAgoHours").replace("{n}", diffHours);
    return t("common.timeAgoDays").replace("{n}", diffDays);
  };

  if (loading) {
    return (
      <div className="p-6 md:p-8" data-testid="guidance-page">
        <div className="h-8 w-48 bg-muted rounded animate-pulse mb-8" />
        <div className="h-64 bg-muted rounded animate-pulse" />
      </div>
    );
  }

  const statusInfo = guidance?.status ? statusConfig[guidance.status] : statusConfig.maintain;
  const StatusIcon = statusInfo.icon;

  return (
    <div className="p-6 md:p-8 pb-24 md:pb-8" data-testid="guidance-page">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="font-heading text-2xl md:text-3xl uppercase tracking-tight font-bold mb-1">
            {t("guidance.title")}
          </h1>
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            {t("guidance.subtitle")}
          </p>
        </div>
        <Button
          onClick={generateGuidance}
          disabled={generating}
          data-testid="generate-guidance"
          className="bg-primary text-white hover:bg-primary/90 rounded-none uppercase font-bold tracking-wider text-xs h-10 px-4 flex items-center gap-2"
        >
          {generating ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          {t("guidanceExtended.refresh")}
        </Button>
      </div>

      {!guidance ? (
        <Card className="bg-card border-border">
          <CardContent className="p-8 text-center">
            <p className="font-mono text-sm text-muted-foreground mb-4">
              {t("guidanceExtended.noGuidance")}
            </p>
            <Button
              onClick={generateGuidance}
              disabled={generating}
              className="bg-primary text-white hover:bg-primary/90 rounded-none uppercase font-bold tracking-wider text-xs h-10 px-6"
            >
              {generating ? (
                <Loader2 className="w-4 h-4 animate-spin mr-2" />
              ) : null}
              {t("guidanceExtended.generate")}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {/* Status Card */}
          <Card className={`bg-card border ${statusInfo.borderColor}`}>
            <CardContent className="p-6">
              <div className="flex items-center gap-4">
                <div className={`w-12 h-12 flex items-center justify-center ${statusInfo.bgColor} border ${statusInfo.borderColor}`}>
                  <StatusIcon className={`w-6 h-6 ${statusInfo.color}`} />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="font-heading text-lg uppercase tracking-tight font-semibold">
                      {t(`guidance.status.${guidance.status}`)}
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {formatTimeAgo(guidance.generated_at)}
                    </span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Guidance Content */}
          <Card className="bg-card border-border">
            <CardContent className="p-6">
              <p className="font-mono text-[10px] uppercase tracking-widest text-primary mb-4">
                {t("guidance.suggestedSessions")}
              </p>
              <div className="prose prose-sm prose-invert max-w-none">
                <p className="text-sm whitespace-pre-wrap leading-relaxed text-foreground/90">
                  {guidance.guidance}
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Disclaimer */}
          <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground text-center">
            {t("guidance.disclaimer")}
          </p>
        </div>
      )}
    </div>
  );
}

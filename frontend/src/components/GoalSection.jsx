import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Target, Calendar, Clock, Route, Trash2, Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import axios from "axios";
import { API_BASE } from "@/utils/constants";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance } from "@/utils/units";

const DISTANCE_OPTIONS = ["5k", "10k", "semi", "marathon", "ultra"];
const DISTANCE_KM = { "5k": 5, "10k": 10, "semi": 21.1, "marathon": 42.195, "ultra": 50 };

export const GoalSection = ({ goal, lang, t, onUpdate }) => {
  const { unitSystem } = useUnitSystem();
  const [isEditing, setIsEditing] = useState(!goal);
  const [eventName, setEventName] = useState(goal?.event_name || "");
  const [eventDate, setEventDate] = useState(goal?.event_date || "");
  const [distanceType, setDistanceType] = useState(goal?.distance_type || "marathon");
  const [targetHours, setTargetHours] = useState(goal?.target_time_minutes ? Math.floor(goal.target_time_minutes / 60) : "");
  const [targetMinutes, setTargetMinutes] = useState(goal?.target_time_minutes ? (goal.target_time_minutes % 60).toString().padStart(2, "0") : "");
  const [saving, setSaving] = useState(false);

  const calculateDaysUntil = (dateStr) => {
    if (!dateStr) return null;
    const eventDate = new Date(dateStr);
    const today = new Date();
    const diffDays = Math.ceil((eventDate - today) / (1000 * 60 * 60 * 24));
    return diffDays > 0 ? diffDays : null;
  };

  const formatTargetTime = (minutes) => {
    if (!minutes) return null;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h${mins.toString().padStart(2, "0")}`;
  };

  const handleSave = async () => {
    if (!eventName.trim() || !eventDate || !distanceType) {
      toast.error(t("settingsExtended.fillRequiredFields"));
      return;
    }

    let targetTimeMinutes = null;
    if (targetHours || targetMinutes) {
      const hours = parseInt(targetHours) || 0;
      const mins = parseInt(targetMinutes) || 0;
      if (hours > 0 || mins > 0) targetTimeMinutes = hours * 60 + mins;
    }

    setSaving(true);
    try {
      const res = await axios.post(`${API_BASE}/user/goal?user_id=default`, {
        event_name: eventName.trim(),
        event_date: eventDate,
        distance_type: distanceType,
        target_time_minutes: targetTimeMinutes
      });
      onUpdate(res.data.goal);
      setIsEditing(false);
      toast.success(t("settings.goalSaved"));
    } catch (error) {
      toast.error(t("common.error"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await axios.delete(`${API_BASE}/user/goal?user_id=default`);
      onUpdate(null);
      toast.success(t("settings.goalDeleted"));
    } catch (error) {
      toast.error(t("common.error"));
    }
  };

  const daysUntil = calculateDaysUntil(goal?.event_date);

  return (
    <Card className="bg-card border-border">
      <CardContent className="p-6">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0 rounded-sm">
            <Target className="w-5 h-5 text-primary" />
          </div>
          <div className="flex-1">
            <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
              {t("settings.goal")}
            </h2>
            <p className="font-mono text-xs text-muted-foreground mb-4">
              {t("settings.goalDesc")}
            </p>

            {!isEditing && goal && daysUntil ? (
              <div className="space-y-4">
                <div className="p-4 bg-primary/5 border border-primary/20 rounded-sm">
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-mono text-sm font-semibold text-primary">
                      {goal.event_name}
                    </span>
                    <Button
                      onClick={handleDelete}
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>

                  <div className="grid grid-cols-2 gap-3 mb-3">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Route className="w-4 h-4 flex-shrink-0" />
                      <span className="font-mono text-xs">
                        {t(`settings.distances.${goal.distance_type}`)} (
                          {formatDistance(goal.distance_km, { unitSystem })}
                        )
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Calendar className="w-4 h-4 flex-shrink-0" />
                      <span className="font-mono text-xs">
                        {new Date(goal.event_date).toLocaleDateString(
                          lang === "fr" ? "fr-FR" : "en-US",
                          { day: "numeric", month: "short", year: "numeric" }
                        )}
                      </span>
                    </div>
                    {goal.target_time_minutes && (
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Clock className="w-4 h-4 flex-shrink-0" />
                        <span className="font-mono text-xs">
                          {t("settings.targetTime")}: {formatTargetTime(goal.target_time_minutes)}
                        </span>
                      </div>
                    )}
                      {goal.target_pace && (
                      <div className="flex items-center gap-2 text-primary">
                        <Target className="w-4 h-4 flex-shrink-0" />
                          <span className="font-mono text-xs font-semibold">
                          {t("settings.targetPace")}: {goal.target_pace}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="pt-3 border-t border-primary/20">
                    <p className="font-mono text-2xl font-bold text-primary">
                      {daysUntil} <span className="text-sm font-normal">{t("settings.daysUntil")}</span>
                    </p>
                  </div>
                </div>

                <Button
                  onClick={() => setIsEditing(true)}
                  variant="outline"
                  size="sm"
                  className="w-full"
                >
                  {t("settings.editGoal")}
                </Button>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                    {t("settings.eventName")} *
                  </label>
                  <Input
                    value={eventName}
                    onChange={(e) => setEventName(e.target.value)}
                    placeholder={t("settingsExtended.placeholderGoalExample")}
                    className="bg-muted border-border font-mono text-sm"
                  />
                </div>

                <div>
                  <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                    {t("settings.distance")} *
                  </label>
                  <Select value={distanceType} onValueChange={setDistanceType}>
                    <SelectTrigger className="bg-muted border-border font-mono text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DISTANCE_OPTIONS.map((dist) => (
                        <SelectItem key={dist} value={dist} className="font-mono text-sm">
                          {t(`settings.distances.${dist}`)} ({DISTANCE_KM[dist]}km)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                    {t("settings.eventDate")} *
                  </label>
                  <Input
                    type="date"
                    value={eventDate}
                    onChange={(e) => setEventDate(e.target.value)}
                    min={new Date().toISOString().split('T')[0]}
                    className="bg-muted border-border font-mono text-sm"
                  />
                </div>

                <div>
                  <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                    {t("settings.targetTime")}
                  </label>
                  <p className="font-mono text-[9px] text-muted-foreground mb-2">
                    {t("settings.targetTimeDesc")}
                  </p>
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      min="0"
                      max="24"
                      value={targetHours}
                      onChange={(e) => setTargetHours(e.target.value)}
                      placeholder="0"
                      className="bg-muted border-border font-mono text-sm w-20 text-center"
                    />
                    <span className="font-mono text-sm text-muted-foreground">h</span>
                    <Input
                      type="number"
                      min="0"
                      max="59"
                      value={targetMinutes}
                      onChange={(e) => setTargetMinutes(e.target.value)}
                      placeholder="00"
                      className="bg-muted border-border font-mono text-sm w-20 text-center"
                    />
                    <span className="font-mono text-sm text-muted-foreground">min</span>
                  </div>
                </div>

                <div className="flex gap-2">
                  <Button
                    onClick={handleSave}
                    disabled={saving || !eventName.trim() || !eventDate}
                    className="flex-1 bg-primary text-white hover:bg-primary/90 rounded-sm uppercase font-bold tracking-wider text-xs h-9"
                  >
                    {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                    {t("settings.saveGoal")}
                  </Button>
                  {goal && (
                    <Button
                      onClick={() => setIsEditing(false)}
                      variant="outline"
                      className="flex-1"
                    >
                      {t("common.cancel")}
                    </Button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

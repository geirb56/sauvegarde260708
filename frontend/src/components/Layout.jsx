import { useState, useEffect, useMemo } from "react";
import { Outlet, NavLink, useLocation } from "react-router-dom";
import { Activity, Home, CalendarDays, MessageCircle, RefreshCw, Settings, TrendingUp, LogOut, Shield } from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";
import { useAutoSync } from "@/hooks/useAutoSync";
import { useAuth } from "@/context/AuthContext";
import ChatCoach from "@/components/ChatCoach";
import axios from "axios";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

export const Layout = () => {
  const location = useLocation();
  const { t } = useLanguage();
  const { user, logout } = useAuth();
  const userId = user?.id;
  const [chatOpen, setChatOpen] = useState(false);
  const [lastSyncMinutes, setLastSyncMinutes] = useState(null);
  
  // Auto-sync Terra data on startup
  useAutoSync();

  // Get last sync time
  useEffect(() => {
    const checkSync = async () => {
      if (!userId) return;
      try {
        const res = await axios.get(`${API}/terra/status`);
        if (res.data.last_sync) {
          const syncDate = new Date(res.data.last_sync);
          const now = new Date();
          const diffMins = Math.round((now - syncDate) / 60000);
          setLastSyncMinutes(diffMins);
        }
      } catch (err) {
        // Ignore
      }
    };
    checkSync();
  }, [userId]);

  const lastSyncLabel = useMemo(() => {
    if (lastSyncMinutes == null) return null;
    if (lastSyncMinutes < 60) {
      return t("common.timeAgoMins").replace("{n}", lastSyncMinutes);
    }
    return t("common.timeAgoHours").replace("{n}", Math.round(lastSyncMinutes / 60));
  }, [lastSyncMinutes, t]);

  const navItems = [
    { path: "/", icon: Home, labelKey: "nav.dashboard" },
    { path: "/sessions", icon: Activity, labelKey: "nav.sessions" },
    { path: "/training", icon: CalendarDays, labelKey: "nav.training" },
    { path: "/coach", icon: MessageCircle, labelKey: "nav.coach" },
    { path: "/progress", icon: TrendingUp, labelKey: "nav.progress" },
    { path: "/settings", icon: Settings, labelKey: "nav.settings" },
  ];
  if (user?.is_admin) {
    navItems.push({ path: "/admin", icon: Shield, label: "Admin" });
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
      
      {/* Mobile Header */}
      <header className="header-modern">
        <div className="header-logo">
          <img
            src="/runindex-logo.png"
            alt="RunIndex"
            className="header-logo-img"
            data-testid="app-logo"
          />
          {lastSyncLabel && (
            <div className="sync-status">
              <span className="sync-dot" />
              <span>{lastSyncLabel}</span>
            </div>
          )}
        </div>
        
        <div className="header-actions">
          <button 
            className="p-2 rounded-lg transition-colors hover:bg-white/5"
            style={{ color: "var(--text-tertiary)" }}
          >
            <RefreshCw className="w-5 h-5" />
          </button>
          <button
            onClick={logout}
            className="p-2 rounded-lg transition-colors hover:bg-white/5"
            style={{ color: "var(--text-tertiary)" }}
            title={t("auth.logout")}
          >
            <LogOut className="w-5 h-5" />
          </button>
          <div className="header-avatar">
            {user?.email ? user.email[0].toUpperCase() : "?"}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-auto pb-20">
        <Outlet />
      </main>

      {/* Bottom Navigation */}
      <nav className="bottom-nav-modern fixed bottom-0 left-0 right-0 flex items-center justify-between px-2 py-2 safe-area-pb">
        {navItems.map((item) => {
          const isActive = item.path === "/"
            ? location.pathname === item.path
            : location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={`nav-item-modern flex-1 ${isActive ? "active" : ""}`}
            >
              <div className="relative">
                <item.icon className="nav-icon w-5 h-5" />
                {item.hasNotification && (
                  <span 
                    className="absolute -top-1 -right-1 w-2 h-2 rounded-full"
                    style={{ background: "var(--status-success)" }}
                  />
                )}
              </div>
              <span className="nav-label text-[9px]">{item.label ?? t(item.labelKey)}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Chat Coach Overlay */}
      <ChatCoach 
        isOpen={chatOpen} 
        onClose={() => setChatOpen(false)} 
        userId={userId}
      />
    </div>
  );
};

export default Layout;

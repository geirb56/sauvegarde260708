import { useState, useEffect } from "react";
import { Outlet, NavLink, useLocation } from "react-router-dom";
import { Home, CalendarDays, MessageCircle, Zap, RefreshCw, Settings, TrendingUp } from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";
import { useAutoSync } from "@/hooks/useAutoSync";
import ChatCoach from "@/components/ChatCoach";
import axios from "axios";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

export const Layout = () => {
  const location = useLocation();
  const { t, lang } = useLanguage();
  const [chatOpen, setChatOpen] = useState(false);
  const [lastSync, setLastSync] = useState(null);
  
  // Auto-sync Terra data on startup
  useAutoSync();

  // Get last sync time
  useEffect(() => {
    const checkSync = async () => {
      try {
        const res = await axios.get(`${API}/terra/status?user_id=default`);
        if (res.data.last_sync) {
          const syncDate = new Date(res.data.last_sync);
          const now = new Date();
          const diffMins = Math.round((now - syncDate) / 60000);
          if (diffMins < 60) {
            setLastSync(t("common.timeAgoMins").replace("{n}", diffMins));
          } else {
            setLastSync(t("common.timeAgoHours").replace("{n}", Math.round(diffMins / 60)));
          }
        }
      } catch (err) {
        // Ignore
      }
    };
    checkSync();
  }, []);

  const navItems = [
    { path: "/", icon: Home, labelKey: "nav.dashboard" },
    { path: "/training", icon: CalendarDays, labelKey: "nav.training" },
    { path: "/coach", icon: MessageCircle, labelKey: "nav.coach" },
    { path: "/progress", icon: TrendingUp, labelKey: "nav.progress" },
    { path: "/settings", icon: Settings, labelKey: "nav.settings" },
  ];

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
      
      {/* Mobile Header */}
      <header className="header-modern">
        <div className="header-logo">
          <div className="header-logo-icon">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="header-logo-text">
              Cardio<span>Coach</span>
            </h1>
            {lastSync && (
              <div className="sync-status">
                <span className="sync-dot" />
                <span>{lastSync}</span>
              </div>
            )}
          </div>
        </div>
        
        <div className="header-actions">
          <button 
            className="p-2 rounded-lg transition-colors hover:bg-white/5"
            style={{ color: "var(--text-tertiary)" }}
          >
            <RefreshCw className="w-5 h-5" />
          </button>
          <div className="header-avatar">
            AR
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
          const isActive = location.pathname === item.path;
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
              <span className="nav-label text-[9px]">{t(item.labelKey)}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Chat Coach Overlay */}
      <ChatCoach 
        isOpen={chatOpen} 
        onClose={() => setChatOpen(false)} 
        userId="default"
      />
    </div>
  );
};

export default Layout;

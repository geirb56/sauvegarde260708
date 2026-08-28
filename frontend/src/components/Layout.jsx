import { useState } from "react";
import { Outlet, NavLink, useLocation } from "react-router-dom";
import { Activity, Home, CalendarDays, MessageCircle, RefreshCw, Settings, TrendingUp, LogOut, Shield } from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";
import ChatCoach from "@/components/ChatCoach";

export const Layout = () => {
  const location = useLocation();
  const { t } = useLanguage();
  const { user, logout } = useAuth();
  const userId = user?.id;
  const [chatOpen, setChatOpen] = useState(false);

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
        </div>
        
        <div className="header-actions">
          <button
            type="button"
            aria-label="Refresh"
            className="p-2 rounded-lg transition-colors hover:bg-white/5 min-w-[44px] min-h-[44px] flex items-center justify-center"
            style={{ color: "var(--text-tertiary)" }}
          >
            <RefreshCw className="w-5 h-5" />
          </button>
          <button
            type="button"
            onClick={logout}
            className="p-2 rounded-lg transition-colors hover:bg-white/5 min-w-[44px] min-h-[44px] flex items-center justify-center"
            style={{ color: "var(--text-tertiary)" }}
            title={t("auth.logout")}
            aria-label={t("auth.logout")}
          >
            <LogOut className="w-5 h-5" />
          </button>
          <div className="header-avatar">
            {user?.email ? user.email[0].toUpperCase() : "?"}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-x-hidden overflow-y-auto pb-[calc(5rem+env(safe-area-inset-bottom))]">
        <Outlet />
      </main>

      {/* Bottom Navigation */}
      <nav className="bottom-nav-modern fixed bottom-0 left-0 right-0 flex items-stretch justify-between gap-0.5 px-2 py-2 safe-area-pb overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
        {navItems.map((item) => {
          const isActive = item.path === "/"
            ? location.pathname === item.path
            : location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={`nav-item-modern flex-1 min-w-[48px] min-h-[44px] ${isActive ? "active" : ""}`}
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
              <span className="nav-label text-[10px] leading-tight truncate max-w-full">{item.label ?? t(item.labelKey)}</span>
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

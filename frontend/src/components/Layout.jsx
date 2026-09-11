import { Outlet, NavLink, Link, useLocation } from "react-router-dom";
import { Activity, Home, CalendarDays, MessageCircle, Settings, TrendingUp, LogOut, Shield } from "lucide-react";
import { useLanguage } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";

export const Layout = () => {
  const location = useLocation();
  const { t } = useLanguage();
  const { user, logout } = useAuth();
  const authenticatedBrandSrc = "/runindex-symbol.png";

  const navItems = [
    { path: "/", icon: Home, labelKey: "nav.home", testId: "mobile-nav-dashboard" },
    { path: "/training", icon: CalendarDays, labelKey: "nav.training", testId: "mobile-nav-training" },
    { path: "/sessions", icon: Activity, labelKey: "nav.sessions", testId: "mobile-nav-sessions" },
    { path: "/coach", icon: MessageCircle, labelKey: "nav.coach", testId: "mobile-nav-coach" },
    { path: "/progress", icon: TrendingUp, labelKey: "nav.progress", testId: "mobile-nav-progress" },
  ];

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-primary)" }}>
      {/* Mobile Header */}
      <header className="header-modern">
        <div className="header-logo">
          <img
            src={authenticatedBrandSrc}
            alt="RunIndex"
            className="header-logo-img"
            data-testid="app-logo"
          />
        </div>
        
        <div className="header-actions">
          <Link
            to="/settings"
            aria-label={t("nav.settings")}
            title={t("nav.settings")}
            data-testid="header-settings-link"
            className="p-2 rounded-lg transition-colors hover:bg-white/5 min-w-[44px] min-h-[44px] flex items-center justify-center"
            style={{ color: "var(--text-tertiary)" }}
          >
            <Settings className="w-5 h-5" />
          </Link>
          {user?.is_admin && (
            <Link
              to="/admin"
              aria-label={t("nav.admin")}
              title={t("nav.admin")}
              data-testid="header-admin-link"
              className="p-2 rounded-lg transition-colors hover:bg-white/5 min-w-[44px] min-h-[44px] flex items-center justify-center"
              style={{ color: "var(--text-tertiary)" }}
            >
              <Shield className="w-5 h-5" />
            </Link>
          )}
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
      <main className="flex-1 overflow-x-hidden overflow-y-auto pb-[calc(4.75rem+env(safe-area-inset-bottom))]">
        <Outlet />
      </main>

      {/* Bottom Navigation */}
      <nav className="bottom-nav-modern fixed bottom-0 left-0 right-0 z-40 border-t border-border/80 px-3 py-2 safe-area-pb backdrop-blur" data-testid="mobile-nav">
        <div className="mx-auto grid w-full max-w-screen-sm grid-cols-5 gap-1">
        {navItems.map((item) => {
          const isActive = item.path === "/"
            ? location.pathname === item.path
            : location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
          return (
            <NavLink
              key={item.path}
              to={item.path}
              data-testid={item.testId}
              className={`nav-item-modern flex min-h-[56px] items-center justify-center rounded-2xl px-1.5 py-2 ${isActive ? "active" : ""}`}
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
              <span className="nav-label text-center text-[11px] font-medium leading-4 whitespace-nowrap">{t(item.labelKey)}</span>
            </NavLink>
          );
        })}
        </div>
      </nav>
    </div>
  );
};

export default Layout;

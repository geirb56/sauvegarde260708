import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { Loader2 } from "lucide-react";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { LanguageProvider } from "@/context/LanguageContext";
import { SubscriptionProvider } from "@/context/SubscriptionContext";
import { UnitProvider } from "@/context/UnitContext";
import Dashboard from "@/pages/Dashboard";
import WorkoutDetail from "@/pages/WorkoutDetail";
import DetailedAnalysis from "@/pages/DetailedAnalysis";
import Sessions from "@/pages/Sessions";
import SessionDetail from "@/pages/SessionDetail";
import Progress from "@/pages/Progress";
import Guidance from "@/pages/Guidance";
import Digest from "@/pages/Digest";
import Settings from "@/pages/Settings";
import Subscription from "@/pages/Subscription";
import TrainingPlanV2 from "@/pages/TrainingPlanV2";
import Coach from "@/pages/Coach";
import Onboarding from "@/pages/Onboarding";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import Admin from "@/pages/Admin";
import Layout from "@/components/Layout";
import IOSPWAHint from "@/components/IOSPWAHint";

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AdminRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!user.is_admin) return <Navigate to="/" replace />;
  return children;
}

function App() {
  return (
    <LanguageProvider>
      <AuthProvider>
        <SubscriptionProvider>
          <UnitProvider>
            <div className="App min-h-screen bg-background text-foreground">
              <div className="noise-overlay" aria-hidden="true" />
              <BrowserRouter>
                <Routes>
                  <Route path="/login" element={<Login />} />
                  <Route path="/register" element={<Register />} />
                  <Route path="/forgot-password" element={<ForgotPassword />} />
                  <Route path="/reset-password" element={<ResetPassword />} />
                  <Route
                    path="/"
                    element={
                      <ProtectedRoute>
                        <Layout />
                      </ProtectedRoute>
                    }
                  >
                    <Route index element={<Dashboard />} />
                    <Route path="sessions" element={<Sessions />} />
                    <Route path="sessions/:id" element={<SessionDetail />} />
                    <Route path="workout/:id" element={<WorkoutDetail />} />
                    <Route path="workout/:id/analysis" element={<DetailedAnalysis />} />
                    <Route path="progress" element={<Progress />} />
                    <Route path="coach" element={<Coach />} />
                    <Route path="guidance" element={<Guidance />} />
                    <Route path="digest" element={<Digest />} />
                    <Route path="training" element={<TrainingPlanV2 />} />
                    <Route path="training-v2" element={<Navigate to="/training" replace />} />
                    <Route path="onboarding" element={<Onboarding />} />
                    <Route path="settings" element={<Settings />} />
                    <Route path="subscription" element={<Subscription />} />
                    <Route
                      path="admin"
                      element={(
                        <AdminRoute>
                          <Admin />
                        </AdminRoute>
                      )}
                    />
                  </Route>
                </Routes>
              </BrowserRouter>
              <Toaster position="bottom-right" />
              {/* PWA iOS hint - discret, one-time, non-bloquant */}
              <IOSPWAHint />
            </div>
          </UnitProvider>
        </SubscriptionProvider>
      </AuthProvider>
    </LanguageProvider>
  );
}

export default App;

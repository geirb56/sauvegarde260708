import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
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
import TrainingPlan from "@/pages/TrainingPlan";
import Coach from "@/pages/Coach";
import Onboarding from "@/pages/Onboarding";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import Layout from "@/components/Layout";
import IOSPWAHint from "@/components/IOSPWAHint";
import { useState, useEffect } from "react";
import axios from "axios";
import { API_BASE_URL } from "@/config";


function AuthGate({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  const [onboardingDone, setOnboardingDone] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (!user || loading) {
      setChecking(false);
      return;
    }

    axios.get(`${API_BASE_URL}/user/profile`)
      .then((res) => setOnboardingDone(res.data?.onboarding_completed === true))
      .catch(() => setOnboardingDone(false))
      .finally(() => setChecking(false));
  }, [user, loading]);

  if (loading || checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (onboardingDone === false && location.pathname !== "/onboarding") {
    return <Navigate to="/onboarding" replace />;
  }

  return children;
}

function App() {
  return (
    <AuthProvider>
      <LanguageProvider>
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
                      <AuthGate>
                        <Layout />
                      </AuthGate>
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
                    <Route path="training" element={<TrainingPlan />} />
                    <Route path="onboarding" element={<Onboarding />} />
                    <Route path="settings" element={<Settings />} />
                    <Route path="subscription" element={<Subscription />} />
                  </Route>
                </Routes>
              </BrowserRouter>
              <Toaster position="bottom-right" />
              {/* PWA iOS hint - discret, one-time, non-bloquant */}
              <IOSPWAHint />
            </div>
          </UnitProvider>
        </SubscriptionProvider>
      </LanguageProvider>
    </AuthProvider>
  );
}

export default App;

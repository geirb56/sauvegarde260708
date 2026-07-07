import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { LanguageProvider } from "@/context/LanguageContext";
import { SubscriptionProvider } from "@/context/SubscriptionContext";
import { UnitProvider } from "@/context/UnitContext";
import Dashboard from "@/pages/Dashboard";
import WorkoutDetail from "@/pages/WorkoutDetail";
import DetailedAnalysis from "@/pages/DetailedAnalysis";
import Progress from "@/pages/Progress";
import Guidance from "@/pages/Guidance";
import Digest from "@/pages/Digest";
import Settings from "@/pages/Settings";
import Subscription from "@/pages/Subscription";
import TrainingPlan from "@/pages/TrainingPlan";
import Coach from "@/pages/Coach";
import Onboarding from "@/pages/Onboarding";
import Layout from "@/components/Layout";
import IOSPWAHint from "@/components/IOSPWAHint";

function App() {
  return (
    <LanguageProvider>
      <SubscriptionProvider>
        <UnitProvider>
          <div className="App min-h-screen bg-background text-foreground">
            <div className="noise-overlay" aria-hidden="true" />
            <BrowserRouter>
              <Routes>
                <Route path="/" element={<Layout />}>
                  <Route index element={<Dashboard />} />
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
  );
}

export default App;

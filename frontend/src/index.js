import React from "react";
import ReactDOM from "react-dom/client";
import axios from "axios";
import "@/index.css";
import "@/styles/theme-modern.css";
import App from "@/App";
import { API_BASE_URL } from "@/config";
import { supabase } from "@/lib/supabase";

// Global axios interceptor: attach the Supabase JWT token as Authorization header.
// The backend validates this token server-side to identify the user.
// X-User-Id headers and ?user_id= query params are no longer used.
axios.interceptors.request.use(async (config) => {
  const url = config.url || "";
  if (url.startsWith(API_BASE_URL) || url.includes("/api/")) {
    config.headers = config.headers || {};
    if (!config.headers["Authorization"]) {
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.access_token) {
        config.headers["Authorization"] = `******;
      }
    }
  }
  return config;
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

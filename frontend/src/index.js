import React from "react";
import ReactDOM from "react-dom/client";
import axios from "axios";
import "@/index.css";
import "@/styles/theme-modern.css";
import App from "@/App";
import { USER_ID } from "@/utils/constants";
import { API_BASE_URL } from "@/config";

// Global axios interceptor: attach X-User-Id to every API request so the
// backend subscription middleware attributes calls to the right user.
axios.interceptors.request.use((config) => {
  const url = config.url || "";
  if (url.startsWith(API_BASE_URL) || url.includes("/api/")) {
    config.headers = config.headers || {};
    if (!config.headers["X-User-Id"]) {
      config.headers["X-User-Id"] = USER_ID;
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

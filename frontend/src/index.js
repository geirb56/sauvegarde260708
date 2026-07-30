import React from "react";
import ReactDOM from "react-dom/client";
import axios from "axios";
import "@/index.css";
import "@/styles/theme-modern.css";
import App from "@/App";
import { API_BASE_URL } from "@/config";

// Global axios interceptor: attach JWT ****** to every API request so
// the backend can authenticate the current user on all endpoints.
axios.interceptors.request.use((config) => {
  const url = config.url || "";
  if (url.startsWith(API_BASE_URL) || url.includes("/api/")) {
    config.headers = config.headers || {};
    if (!config.headers["Authorization"]) {
      const token = localStorage.getItem("access_token");
      if (token) {
        config.headers["Authorization"] = "Bearer " + token;
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

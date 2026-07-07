import { useEffect, useRef } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Hook to automatically sync Terra wearable data on app startup
 * Only syncs if:
 * - User is connected to Terra
 * - Last sync was more than 1 hour ago OR no sync has been done
 */
export function useAutoSync() {
  const hasTriedSync = useRef(false);

  useEffect(() => {
    if (hasTriedSync.current) return;
    hasTriedSync.current = true;

    const autoSync = async () => {
      try {
        const statusRes = await axios.get(`${API}/terra/status`);
        const { connected, last_sync } = statusRes.data;

        if (!connected) {
          return;
        }

        const ONE_HOUR_MS = 60 * 60 * 1000;
        const now = Date.now();
        const lastSyncTime = last_sync ? new Date(last_sync).getTime() : 0;
        const timeSinceLastSync = now - lastSyncTime;

        if (timeSinceLastSync < ONE_HOUR_MS) {
          return;
        }

        await axios.post(`${API}/terra/sync`);
      } catch (error) {
        // Silent fail - don't disrupt user experience
      }
    };

    const timeoutId = setTimeout(autoSync, 2000);

    return () => clearTimeout(timeoutId);
  }, []);
}

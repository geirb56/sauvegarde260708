import { useEffect, useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "@/config";

export default function useWorkoutIntelligence(id, lang, allowed) {
  const [state, setState] = useState(null);
  const key = JSON.stringify([id, lang]);

  useEffect(() => {
    if (!allowed || !id) {
      setState(null);
      return undefined;
    }
    const controller = new AbortController();
    const { signal } = controller;
    setState({ key, loading: true, error: false, data: null });
    axios.get(`${API_BASE_URL}/coach/workout-intelligence/${encodeURIComponent(id)}?language=${lang}`, { signal })
      .then(({ data }) => {
        if (!signal.aborted) setState({ key, data, loading: false, error: false });
      })
      .catch((error) => {
        if (!signal.aborted && !axios.isCancel(error)) {
          setState({ key, data: null, loading: false, error: true });
        }
      });
    return () => controller.abort();
  }, [id, lang, allowed, key]);

  return allowed && id && state?.key === key
    ? state
    : { data: null, error: false, loading: Boolean(allowed && id) };
}

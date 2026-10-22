import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "@/config";

export default function useWorkoutIntelligence(id, lang, allowed) {
  const [state, setState] = useState(null);
  // A new scope also invalidates results after entitlement is revoked and restored.
  const scope = useMemo(() => ({ id, lang, allowed }), [id, lang, allowed]);

  useEffect(() => {
    if (!allowed || !id) {
      setState(null);
      return undefined;
    }
    const controller = new AbortController();
    const { signal } = controller;
    setState({ scope, loading: true, error: false, data: null });
    axios.get(`${API_BASE_URL}/coach/workout-intelligence/${encodeURIComponent(id)}?language=${lang}`, { signal, timeout: 15000 })
      .then(({ data }) => {
        if (!signal.aborted) setState({ scope, data, loading: false, error: false });
      })
      .catch((error) => {
        if (!signal.aborted && !axios.isCancel(error)) {
          setState({ scope, data: null, loading: false, error: true });
        }
      });
    return () => controller.abort();
  }, [id, lang, allowed, scope]);

  return allowed && id && state?.scope === scope
    ? state
    : { scope, data: null, error: false, loading: Boolean(allowed && id) };
}

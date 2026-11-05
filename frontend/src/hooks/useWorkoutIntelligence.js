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
    const base = `${API_BASE_URL}/coach/workout-intelligence/${encodeURIComponent(id)}?language=${lang}`;
    // C400: the C396 comment is optional and slower; it never blocks or replaces the C388 facts.
    const commentUrl = `${API_BASE_URL}/coach/workout-comment/${encodeURIComponent(id)}?language=${lang}`;
    axios.get(base, { signal, timeout: 15000 })
      .then(({ data }) => {
        if (signal.aborted) return;
        setState({ scope, data, loading: false, error: false });
        axios.get(commentUrl, { signal, timeout: 30000 }).then(({ data: comment }) => {
          if (signal.aborted || !comment) return;
          setState((prev) => (prev?.scope === scope && prev.data
            ? { ...prev, data: { ...prev.data, coach_comment: comment } } : prev));
        }).catch(() => {});
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

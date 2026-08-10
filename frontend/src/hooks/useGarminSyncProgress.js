/**
 * useGarminSyncProgress
 *
 * Streams Garmin sync-progress events from the backend SSE endpoint using
 * the Fetch API (NOT the native EventSource, which cannot set Authorization
 * headers — RunIndex uses JWT in localStorage + ******
 *
 * Behaviour:
 *  - Opens GET /api/garmin/sync/stream with Authorization: ******
 *  - Parses `event: sync_progress` frames; ignores heartbeat comments.
 *  - On disconnect / error: exponential back-off then retries.
 *  - Falls back to GET /api/garmin/status on reconnect failure or when
 *    the stream is closed by the server (e.g. sync complete).
 *  - Exposes { progress, isStreaming, error }.
 *
 * Usage:
 *   const { progress, isStreaming } = useGarminSyncProgress({ enabled: true });
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../config";

const STREAM_URL = `${API_BASE_URL}/garmin/sync/stream`;
const STATUS_URL = `${API_BASE_URL}/garmin/status`;

const INITIAL_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;
const MAX_RETRIES = 8;

function getToken() {
  return localStorage.getItem("token") || localStorage.getItem("access_token") || null;
}

function parseSSEFrames(chunk, buffer) {
  const lines = (buffer + chunk).split("\n");
  const events = [];
  let currentEvent = null;
  let currentData = null;
  let newBuffer = "";

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Incomplete last line — keep it in the buffer.
    if (i === lines.length - 1 && !chunk.endsWith("\n")) {
      newBuffer = line;
      break;
    }

    if (line.startsWith(":")) {
      // Comment / heartbeat — skip.
      continue;
    }

    if (line.startsWith("event:")) {
      currentEvent = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      currentData = line.slice(5).trim();
    } else if (line === "") {
      // End of frame.
      if (currentEvent === "sync_progress" && currentData) {
        try {
          events.push(JSON.parse(currentData));
        } catch (_) {
          // Malformed JSON — ignore.
        }
      }
      currentEvent = null;
      currentData = null;
    }
  }

  return { events, buffer: newBuffer };
}

export function useGarminSyncProgress({ enabled = true } = {}) {
  const [progress, setProgress] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState(null);

  const abortRef = useRef(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef(null);
  const lastIdRef = useRef("$");
  const bufferRef = useRef("");
  const isMountedRef = useRef(true);

  // --- Fallback: fetch current status via REST ---------------------
  const fetchStatusFallback = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await fetch(STATUS_URL, {
        headers: { Authorization: "Bearer " + token },
      });
      if (!res.ok) return;
      const data = await res.json();
      if (isMountedRef.current) setProgress(data);
    } catch (_) {
      // Silent — fallback is best-effort.
    }
  }, []);

  // --- Stream opener -----------------------------------------------
  const openStream = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setError("unauthenticated");
      return;
    }

    const url =
      lastIdRef.current && lastIdRef.current !== "$"
        ? `${STREAM_URL}?last_id=${encodeURIComponent(lastIdRef.current)}`
        : STREAM_URL;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      setIsStreaming(true);
      setError(null);

      const res = await fetch(url, {
        headers: {
          Authorization: "Bearer " + token,
          Accept: "text/event-stream",
        },
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`SSE HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      bufferRef.current = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const { events, buffer } = parseSSEFrames(chunk, bufferRef.current);
        bufferRef.current = buffer;

        for (const ev of events) {
          if (isMountedRef.current) {
            setProgress(ev);
            // Track Last-Event-ID for reconnect (skip synthetic "snapshot" id).
            if (ev._id && ev._id !== "snapshot") {
              lastIdRef.current = ev._id;
            }
          }
        }
      }

      // Stream closed cleanly by server.
      retryCountRef.current = 0;
      if (isMountedRef.current) setIsStreaming(false);
    } catch (err) {
      if (err.name === "AbortError" || !isMountedRef.current) return;

      if (isMountedRef.current) setIsStreaming(false);

      const count = retryCountRef.current;
      if (count >= MAX_RETRIES) {
        setError("max_retries");
        await fetchStatusFallback();
        return;
      }

      const delay = Math.min(INITIAL_RETRY_MS * 2 ** count, MAX_RETRY_MS);
      retryCountRef.current = count + 1;

      retryTimerRef.current = setTimeout(() => {
        if (isMountedRef.current) openStream();
      }, delay);
    }
  }, [fetchStatusFallback]);

  // --- Lifecycle ---------------------------------------------------
  useEffect(() => {
    isMountedRef.current = true;

    if (!enabled) return;

    openStream();

    return () => {
      isMountedRef.current = false;
      abortRef.current?.abort();
      clearTimeout(retryTimerRef.current);
    };
  }, [enabled, openStream]);

  return { progress, isStreaming, error };
}

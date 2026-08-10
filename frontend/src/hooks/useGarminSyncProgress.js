/**
 * useGarminSyncProgress
 *
 * Streams Garmin sync-progress events from the backend SSE endpoint using
 * the Fetch API (NOT the native EventSource, which cannot set Authorization
 * headers — RunIndex uses JWT in localStorage).
 *
 * Behaviour:
 *  - Opens GET /api/garmin/sync/stream with Authorization: ******
 *  - Parses `event: sync_progress` frames; supports `id:`, `event:`, `data:`
 *    fields and CRLF / LF line endings, across fragmented chunks.
 *  - Terminal statuses (complete, partial_success, failed) received via SSE
 *    or from the /garmin/status fallback stop streaming immediately.
 *  - The synthetic snapshot id ("snapshot") is NEVER stored as a Last-Event-ID
 *    cursor; only real Redis Stream IDs are stored.
 *  - On network error / clean stream close (done=true) without terminal status:
 *    fetch /garmin/status first.
 *      • Terminal status → update progress, do NOT reconnect.
 *      • Active status  → exponential back-off, then reconnect.
 *  - Voluntary abort (unmount / enabled=false) → no fallback, no reconnect.
 *  - 401 / 403 → set error, do NOT retry.
 *  - status=failed via SSE → sets safe error (error_code or "sync_failed").
 *  - Exposes { progress, isStreaming, error }.
 *
 * Back-off schedule (ms): 1 000 → 2 000 → 4 000 → 8 000 → … → 30 000 cap.
 * Back-off counter is reset after a successful SSE connection.
 *
 * Cleanup: AbortController + clearTimeout on unmount or enabled=false.
 * A voluntary abort is never treated as a network error.
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

/** Statuses that mean the sync has finished — no reconnect needed. */
const TERMINAL_STATUSES = new Set(["complete", "partial_success", "failed"]);

function getToken() {
  return localStorage.getItem("token") || localStorage.getItem("access_token") || null;
}

/**
 * parseSSEFrames
 *
 * Parses raw SSE text (possibly fragmented across network chunks) into
 * complete events.  Supports:
 *   - `id:`, `event:`, `data:` fields
 *   - CRLF (\r\n) and LF (\n) line endings
 *   - Multiple `data:` lines per frame (concatenated with \n per spec)
 *   - Heartbeat / comment lines (`:`)
 *
 * Returns { events, buffer } where `buffer` is the incomplete tail to prepend
 * to the next chunk.  Each event object is { id, event, data } where `data`
 * is the parsed JSON object and `id` is the parsed id field (or null).
 *
 * Frames are detected by splitting on "\n\n" (the SSE frame separator after
 * CRLF normalisation).  This correctly handles frames that span multiple
 * network chunks because incomplete frames stay in the buffer until "\n\n"
 * arrives.
 */
export function parseSSEFrames(rawChunk, prevBuffer) {
  // Normalise CRLF → LF so we can split on \n uniformly.
  const text = prevBuffer + rawChunk.replace(/\r\n/g, "\n");

  // Split into complete frames (terminated by \n\n) and keep the remainder.
  const events = [];
  let pos = 0;

  while (true) {
    const sep = text.indexOf("\n\n", pos);
    if (sep === -1) break; // No complete frame yet — keep the rest in buffer.

    const frame = text.slice(pos, sep);
    pos = sep + 2;

    let currentId = null;
    let currentEvent = null;
    const currentDataLines = [];

    for (const line of frame.split("\n")) {
      if (line === "" || line.startsWith(":")) continue; // blank / comment

      const colonIdx = line.indexOf(":");
      if (colonIdx === -1) continue; // bare field name — skip per spec

      const field = line.slice(0, colonIdx);
      // Per SSE spec: strip exactly one leading space after the colon.
      const value = colonIdx + 1 < line.length
        ? (line[colonIdx + 1] === " " ? line.slice(colonIdx + 2) : line.slice(colonIdx + 1))
        : "";

      if (field === "id") {
        currentId = value;
      } else if (field === "event") {
        currentEvent = value;
      } else if (field === "data") {
        currentDataLines.push(value);
      }
    }

    if (currentEvent === "sync_progress" && currentDataLines.length > 0) {
      const dataStr = currentDataLines.join("\n");
      try {
        const parsed = JSON.parse(dataStr);
        events.push({ id: currentId, event: currentEvent, data: parsed });
      } catch (_) {
        // Malformed JSON — ignore frame.
      }
    }
  }

  return { events, buffer: text.slice(pos) };
}

export function useGarminSyncProgress({ enabled = true } = {}) {
  const [progress, setProgress] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState(null);

  const abortRef = useRef(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef(null);
  const lastIdRef = useRef(null);
  const bufferRef = useRef("");
  const isMountedRef = useRef(true);
  // Set to true when the stream is voluntarily stopped (unmount / enabled=false / abort).
  // Prevents recovery or reconnect on voluntary close.
  const voluntaryAbortRef = useRef(false);

  // ------------------------------------------------------------------
  // Fallback: fetch current status via REST.
  // Returns true if a terminal status was found (no reconnect needed).
  // ------------------------------------------------------------------
  const fetchStatusFallback = useCallback(async () => {
    const token = getToken();
    if (!token) return false;
    try {
      const res = await fetch(STATUS_URL, {
        headers: { Authorization: "Bearer " + token },
      });
      if (!res.ok) return false;
      const data = await res.json();
      // The endpoint returns { sync_status: {...} }
      const snapshot = data.sync_status ?? null;
      if (isMountedRef.current) setProgress(snapshot);
      return TERMINAL_STATUSES.has(snapshot?.status);
    } catch (_) {
      return false;
    }
  }, []);

  // ------------------------------------------------------------------
  // Schedule a reconnect with exponential back-off.
  // ------------------------------------------------------------------
  const scheduleReconnect = useCallback((openStreamFn) => {
    const count = retryCountRef.current;
    const delay = Math.min(INITIAL_RETRY_MS * 2 ** count, MAX_RETRY_MS);
    retryCountRef.current = count + 1;
    retryTimerRef.current = setTimeout(() => {
      if (isMountedRef.current) openStreamFn();
    }, delay);
  }, []);

  // ------------------------------------------------------------------
  // Stream opener
  // ------------------------------------------------------------------
  const openStream = useCallback(async () => {
    // Reset voluntary-abort flag at the start of every new connection attempt.
    voluntaryAbortRef.current = false;

    const token = getToken();
    if (!token) {
      setError("unauthenticated");
      setIsStreaming(false);
      return;
    }

    const url =
      lastIdRef.current
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

      // 401 / 403 → auth error, no retry.
      if (res.status === 401) {
        if (isMountedRef.current) {
          setError("unauthenticated");
          setIsStreaming(false);
        }
        return;
      }
      if (res.status === 403) {
        if (isMountedRef.current) {
          setError("forbidden");
          setIsStreaming(false);
        }
        return;
      }

      if (!res.ok) {
        // 5xx or other — treat as network error below.
        throw new Error(`SSE HTTP ${res.status}`);
      }

      // Successful connection — reset back-off counter.
      retryCountRef.current = 0;

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
          if (!isMountedRef.current) break;

          setProgress(ev.data);

          // Update Last-Event-ID cursor — but never store the synthetic
          // "snapshot" id emitted by the backend for the initial snapshot;
          // that is not a valid Redis Stream cursor.
          if (ev.id !== null && ev.id !== undefined && ev.id !== "snapshot") {
            lastIdRef.current = ev.id;
          }

          // Terminal status via SSE → stop streaming, no reconnect.
          if (TERMINAL_STATUSES.has(ev.data?.status)) {
            // For failed status, expose a safe error code — never raw payloads.
            if (ev.data.status === "failed") {
              const safeError = ev.data?.error_code || "sync_failed";
              if (isMountedRef.current) setError(safeError);
            }
            setIsStreaming(false);
            reader.cancel();
            return;
          }
        }
      }

      // Stream closed cleanly by server (done=true) with no terminal status seen.
      // This can happen due to a network proxy closing the connection.
      // Apply the same recovery as a network error: check /garmin/status.
      // Exception: voluntary abort (enabled=false clean-close) — skip recovery.
      if (isMountedRef.current && !voluntaryAbortRef.current) {
        setIsStreaming(false);
        const isTerminal = await fetchStatusFallback();
        if (!isMountedRef.current) return;
        if (!isTerminal) {
          scheduleReconnect(openStream);
        }
      } else if (isMountedRef.current) {
        // Voluntary abort path where the stream happened to close cleanly
        // (e.g. enabled=false fired just as the server closed the connection).
        setIsStreaming(false);
      }
    } catch (err) {
      // Voluntary abort (unmount or enabled=false) — never treat as error.
      if (err.name === "AbortError" || !isMountedRef.current) return;

      if (isMountedRef.current) setIsStreaming(false);

      // Recovery: check /garmin/status BEFORE deciding to reconnect.
      const isTerminal = await fetchStatusFallback();
      if (!isMountedRef.current) return;

      if (isTerminal) {
        // Sync finished — do not reconnect.
        return;
      }

      // Still active — schedule reconnect with back-off.
      scheduleReconnect(openStream);
    }
  }, [fetchStatusFallback, scheduleReconnect]);

  // --- Lifecycle ---------------------------------------------------
  useEffect(() => {
    isMountedRef.current = true;

    if (!enabled) return;

    openStream();

    return () => {
      isMountedRef.current = false;
      voluntaryAbortRef.current = true;
      abortRef.current?.abort();
      clearTimeout(retryTimerRef.current);
    };
  }, [enabled, openStream]);

  return { progress, isStreaming, error };
}

/**
 * Tests for useGarminSyncProgress hook (PR07B)
 *
 * Covers F1–F21 as specified in the problem statement.
 * Uses the Fetch API mock — no native EventSource involved.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { useGarminSyncProgress, parseSSEFrames } from "../hooks/useGarminSyncProgress";

// Mock config before hook import — jest.mock is hoisted so this is safe.
jest.mock("../config", () => ({
  API_BASE_URL: "http://localhost:8000/api",
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const encoder = new TextEncoder();

/**
 * makeSSEBody — returns a fake response body with getReader()
 * that emits the given text chunks as Uint8Array values, then signals done.
 * Does NOT require ReadableStream (not available in jsdom).
 */
function makeSSEBody(chunks) {
  let idx = 0;
  return {
    getReader() {
      return {
        read() {
          if (idx < chunks.length) {
            return Promise.resolve({ done: false, value: encoder.encode(chunks[idx++]) });
          }
          return Promise.resolve({ done: true, value: undefined });
        },
        cancel: jest.fn(),
      };
    },
  };
}

/** Build a fetch spy that returns a streaming SSE response. */
function mockSSEFetch(chunks, status = 200) {
  return jest.spyOn(global, "fetch").mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    body: makeSSEBody(chunks),
  });
}

// ---------------------------------------------------------------------------
// Lifecycle hooks
// ---------------------------------------------------------------------------

beforeEach(() => {
  jest.useFakeTimers();
  localStorage.setItem("token", "test-jwt-token");
});

afterEach(() => {
  jest.runAllTimers();
  jest.useRealTimers();
  localStorage.clear();
  jest.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// F1 — Authorization ******
// ---------------------------------------------------------------------------
test("F1: sends Authorization ****** on connect", async () => {
  const fetchSpy = mockSSEFetch([": connected\n\n"]);
  renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => { await Promise.resolve(); });

  expect(fetchSpy).toHaveBeenCalledWith(
    expect.stringContaining("/garmin/sync/stream"),
    expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: expect.stringContaining("Bearer "),
      }),
    })
  );
});

// ---------------------------------------------------------------------------
// F2 — JWT absent from URL
// ---------------------------------------------------------------------------
test("F2: JWT token is NOT placed in the URL", async () => {
  const fetchSpy = mockSSEFetch([": connected\n\n"]);
  renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => { await Promise.resolve(); });

  const calledUrl = fetchSpy.mock.calls[0][0];
  expect(calledUrl).not.toContain("test-jwt-token");
  expect(calledUrl).not.toContain("token=");
});

// ---------------------------------------------------------------------------
// F3 — No EventSource in hook source
// ---------------------------------------------------------------------------
test("F3: hook does not use native EventSource", () => {
  const src = useGarminSyncProgress.toString();
  expect(src).not.toContain("EventSource");
});

// ---------------------------------------------------------------------------
// F4 — Simple parsing: single sync_progress frame
// ---------------------------------------------------------------------------
test("F4: parses a simple sync_progress frame", async () => {
  const payload = { status: "in_progress", phase: "activities_fetching" };
  mockSSEFetch([`event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`]);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.progress).not.toBeNull(), { timeout: 2000 });
  expect(result.current.progress.status).toBe("in_progress");
  expect(result.current.progress.phase).toBe("activities_fetching");
});

// ---------------------------------------------------------------------------
// F5 — Fragmented frame across multiple chunks
// ---------------------------------------------------------------------------
test("F5: handles frame fragmented across multiple chunks", async () => {
  const chunks = [
    "id: 12\nevent: sync_pro",
    "gress\ndata: {\"run_index_",
    "status\":\"ready\",\"status\":\"in_progress\"}\n\n",
  ];
  mockSSEFetch(chunks);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.progress).not.toBeNull(), { timeout: 2000 });
  expect(result.current.progress.run_index_status).toBe("ready");
});

// ---------------------------------------------------------------------------
// F6 — CRLF line endings
// ---------------------------------------------------------------------------
test("F6: handles CRLF line endings", () => {
  const frame = "event: sync_progress\r\ndata: {\"status\":\"queued\"}\r\n\r\n";
  const { events } = parseSSEFrames(frame, "");
  expect(events).toHaveLength(1);
  expect(events[0].data.status).toBe("queued");
});

// ---------------------------------------------------------------------------
// F7 — Heartbeat comments are ignored
// ---------------------------------------------------------------------------
test("F7: heartbeat comment lines are ignored", async () => {
  const payload = { status: "in_progress" };
  mockSSEFetch([
    ": heartbeat\n\n",
    ": ping\n\n",
    `event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`,
  ]);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.progress).not.toBeNull(), { timeout: 2000 });
  expect(result.current.progress.status).toBe("in_progress");
});

// ---------------------------------------------------------------------------
// F8 — Multiple data: lines concatenated per SSE spec
// ---------------------------------------------------------------------------
test("F8: multiple data: lines are each returned and final frame is parsed", () => {
  // A single frame with two data: lines (the second is empty — valid JSON still parseable)
  const frame = 'event: sync_progress\ndata: {"status":"in_progress"}\ndata: \n\n';
  const { events } = parseSSEFrames(frame, "");
  // data lines joined: '{"status":"in_progress"}' + '\n' + ''
  // JSON.parse of that string still succeeds (trailing \n is ignored by the parser)
  expect(events[0].data.status).toBe("in_progress");

  // Second scenario: verify two data: lines ARE concatenated
  const frame2 = 'event: sync_progress\ndata: {"k":\ndata: "v"}\n\n';
  const { events: evs2 } = parseSSEFrames(frame2, "");
  // The two lines joined: '{"k":' + '\n' + '"v"}' — valid JSON
  expect(evs2[0].data.k).toBe("v");
});

// ---------------------------------------------------------------------------
// F9 — id: field is parsed and returned in event object
// ---------------------------------------------------------------------------
test("F9: id: field is parsed and present in event object", () => {
  const frame = "id: 123-0\nevent: sync_progress\ndata: {\"status\":\"in_progress\"}\n\n";
  const { events } = parseSSEFrames(frame, "");
  expect(events).toHaveLength(1);
  expect(events[0].id).toBe("123-0");
  expect(events[0].data.status).toBe("in_progress");
});

// ---------------------------------------------------------------------------
// F10 — complete via SSE stops reconnection
// ---------------------------------------------------------------------------
test("F10: SSE status=complete stops streaming and does not reconnect", async () => {
  const payload = { status: "complete" };
  const fetchSpy = mockSSEFetch([`event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`]);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.progress?.status).toBe("complete"), { timeout: 2000 });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  // Only one stream fetch — no reconnect
  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F11 — partial_success via SSE stops reconnection without error
// ---------------------------------------------------------------------------
test("F11: SSE status=partial_success stops streaming without error", async () => {
  const payload = { status: "partial_success" };
  const fetchSpy = mockSSEFetch([`event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`]);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.progress?.status).toBe("partial_success"), { timeout: 2000 });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.error).toBeNull();
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F12 — failed via SSE stops reconnection; progress set
// ---------------------------------------------------------------------------
test("F12: SSE status=failed stops streaming with progress set but no reconnect", async () => {
  const payload = { status: "failed", reason: "timeout" };
  const fetchSpy = mockSSEFetch([`event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`]);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.progress?.status).toBe("failed"), { timeout: 2000 });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F13 — network cut → GET /garmin/status called before any reconnect
// ---------------------------------------------------------------------------
test("F13: on network error, calls /garmin/status before reconnecting", async () => {
  const fetchCallUrls = [];
  jest.spyOn(global, "fetch").mockImplementation((url) => {
    fetchCallUrls.push(url);
    if (url.includes("/garmin/sync/stream")) {
      return Promise.reject(new Error("Network error"));
    }
    // Status fallback — return terminal to stop reconnect loop
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "complete" } }),
    });
  });

  renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(fetchCallUrls.some((u) => u.includes("/garmin/status"))).toBe(true);
  // Status is called AFTER stream failure (index must be higher)
  const streamIdx = fetchCallUrls.findIndex((u) => u.includes("/garmin/sync/stream"));
  const statusIdx = fetchCallUrls.findIndex((u) => u.includes("/garmin/status"));
  expect(statusIdx).toBeGreaterThan(streamIdx);
});

// ---------------------------------------------------------------------------
// F14 — fallback sync_status=complete → no reconnect
// ---------------------------------------------------------------------------
test("F14: fallback sync_status=complete does not reconnect", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      return Promise.reject(new Error("Network error"));
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "complete" } }),
    });
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.progress?.status).toBe("complete");
});

// ---------------------------------------------------------------------------
// F15 — fallback sync_status=partial_success → no reconnect
// ---------------------------------------------------------------------------
test("F15: fallback sync_status=partial_success does not reconnect", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      return Promise.reject(new Error("Network error"));
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "partial_success" } }),
    });
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.progress?.status).toBe("partial_success");
});

// ---------------------------------------------------------------------------
// F16 — fallback sync_status=failed → no reconnect
// ---------------------------------------------------------------------------
test("F16: fallback sync_status=failed does not reconnect", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      return Promise.reject(new Error("Network error"));
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "failed" } }),
    });
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.progress?.status).toBe("failed");
});

// ---------------------------------------------------------------------------
// F17 — fallback sync_status=in_progress → reconnect with back-off
// ---------------------------------------------------------------------------
test("F17: fallback sync_status=in_progress triggers reconnect with back-off", async () => {
  let streamCallCount = 0;
  jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      streamCallCount++;
      return Promise.reject(new Error("Network error"));
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "in_progress" } }),
    });
  });

  renderHook(() => useGarminSyncProgress({ enabled: true }));

  // First failure + fallback
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(streamCallCount).toBe(1);

  // Advance back-off timer to trigger reconnect
  await act(async () => {
    jest.runAllTimers();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(streamCallCount).toBeGreaterThan(1);
});

// ---------------------------------------------------------------------------
// F18 — 401 → no retry, error=unauthenticated
// ---------------------------------------------------------------------------
test("F18: 401 response sets error=unauthenticated and does not retry", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue({
    ok: false,
    status: 401,
    body: makeSSEBody([]),
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.error).toBe("unauthenticated"), { timeout: 2000 });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F19 — 403 → no retry, error=forbidden
// ---------------------------------------------------------------------------
test("F19: 403 response sets error=forbidden and does not retry", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue({
    ok: false,
    status: 403,
    body: makeSSEBody([]),
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.error).toBe("forbidden"), { timeout: 2000 });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F20 — abort during stream → no reconnect, no fallback
// ---------------------------------------------------------------------------
test("F20: unmounting during stream does not trigger reconnect or fallback", async () => {
  // Infinite stream — read() never resolves
  const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          read: () => new Promise(() => {}),
          cancel: jest.fn(),
        };
      },
    },
  });

  const { unmount } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => { await Promise.resolve(); });
  unmount();
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  // Only one SSE fetch — no reconnect, no status fallback
  expect(fetchSpy).toHaveBeenCalledTimes(1);
});

// ---------------------------------------------------------------------------
// F21 — abort during back-off timer → no reconnect
// ---------------------------------------------------------------------------
test("F21: unmounting during back-off timer cancels reconnect", async () => {
  const fetchCallUrls = [];
  jest.spyOn(global, "fetch").mockImplementation((url) => {
    fetchCallUrls.push(url);
    if (url.includes("/garmin/sync/stream")) {
      return Promise.reject(new Error("Network error"));
    }
    // in_progress → back-off timer is set
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "in_progress" } }),
    });
  });

  const { unmount } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  // First failure + fallback complete
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

  // Back-off timer is pending — unmount before it fires
  unmount();
  const callCountBeforeTimer = fetchCallUrls.length;

  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const newStreamCalls = fetchCallUrls
    .slice(callCountBeforeTimer)
    .filter((u) => u.includes("/garmin/sync/stream"));
  expect(newStreamCalls).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// F22 — synthetic "snapshot" id is never stored as last_id cursor
// ---------------------------------------------------------------------------
test("F22: synthetic 'snapshot' id is not used as last_id in reconnect URL", async () => {
  const fetchCallUrls = [];
  let callCount = 0;
  jest.spyOn(global, "fetch").mockImplementation((url) => {
    fetchCallUrls.push(url);
    callCount++;
    if (url.includes("/garmin/sync/stream")) {
      if (callCount === 1) {
        // First call: emit snapshot event then close cleanly.
        return Promise.resolve({
          ok: true,
          status: 200,
          body: makeSSEBody([
            "id: snapshot\nevent: sync_progress\ndata: {\"status\":\"in_progress\"}\n\n",
          ]),
        });
      }
      // Second call (reconnect): just hang.
      return Promise.resolve({
        ok: true,
        status: 200,
        body: { getReader() { return { read: () => new Promise(() => {}), cancel: jest.fn() }; } },
      });
    }
    // Status fallback for clean-close recovery: return in_progress to trigger reconnect.
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "in_progress" } }),
    });
  });

  renderHook(() => useGarminSyncProgress({ enabled: true }));

  // Let first stream complete + fallback run.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

  // Advance back-off timer to trigger reconnect.
  await act(async () => {
    jest.runAllTimers();
    await Promise.resolve();
    await Promise.resolve();
  });

  // The reconnect URL must NOT contain last_id=snapshot.
  const reconnectCalls = fetchCallUrls.filter((u) => u.includes("/garmin/sync/stream"));
  expect(reconnectCalls.length).toBeGreaterThanOrEqual(2);
  for (const u of reconnectCalls) {
    expect(u).not.toContain("last_id=snapshot");
  }
});

// ---------------------------------------------------------------------------
// F23 — clean stream close + active fallback → backoff → reconnect
// ---------------------------------------------------------------------------
test("F23: clean stream close without terminal + in_progress fallback → reconnect", async () => {
  let streamCallCount = 0;
  jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      streamCallCount++;
      if (streamCallCount === 1) {
        // Clean close (done=true) with no terminal event.
        return Promise.resolve({
          ok: true,
          status: 200,
          body: makeSSEBody([": heartbeat\n\n"]),
        });
      }
      // Subsequent reconnects: hang.
      return Promise.resolve({
        ok: true,
        status: 200,
        body: { getReader() { return { read: () => new Promise(() => {}), cancel: jest.fn() }; } },
      });
    }
    // /garmin/status fallback: in_progress → reconnect.
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "in_progress" } }),
    });
  });

  renderHook(() => useGarminSyncProgress({ enabled: true }));

  // Let clean close + fallback run.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(streamCallCount).toBe(1);

  // Trigger back-off → reconnect.
  await act(async () => {
    jest.runAllTimers();
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(streamCallCount).toBeGreaterThan(1);
});

// ---------------------------------------------------------------------------
// F24 — clean stream close + complete fallback → no reconnect
// ---------------------------------------------------------------------------
test("F24: clean stream close without terminal + complete fallback → no reconnect", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        body: makeSSEBody([": heartbeat\n\n"]),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "complete" } }),
    });
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F25 — clean stream close + partial_success fallback → no reconnect
// ---------------------------------------------------------------------------
test("F25: clean stream close without terminal + partial_success fallback → no reconnect", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        body: makeSSEBody([": heartbeat\n\n"]),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "partial_success" } }),
    });
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F26 — clean stream close + failed fallback → no reconnect
// ---------------------------------------------------------------------------
test("F26: clean stream close without terminal + failed fallback → no reconnect", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        body: makeSSEBody([": heartbeat\n\n"]),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "failed" } }),
    });
  });

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => { jest.runAllTimers(); await Promise.resolve(); });

  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F27 — status=failed via SSE sets safe error (error_code or "sync_failed")
// ---------------------------------------------------------------------------
test("F27: SSE status=failed with error_code sets safe error code", async () => {
  const payload = { status: "failed", error_code: "metrics_failed" };
  mockSSEFetch([`event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`]);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.error).not.toBeNull(), { timeout: 2000 });

  expect(result.current.error).toBe("metrics_failed");
  expect(result.current.isStreaming).toBe(false);
  // Must not contain stacktrace or raw exception text.
  expect(typeof result.current.error).toBe("string");
  expect(result.current.error).not.toMatch(/Error|stack|exception/i);
});

test("F27b: SSE status=failed without error_code sets generic safe error", async () => {
  const payload = { status: "failed" };
  mockSSEFetch([`event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`]);

  const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  await waitFor(() => expect(result.current.error).not.toBeNull(), { timeout: 2000 });

  expect(result.current.error).toBe("sync_failed");
  expect(result.current.isStreaming).toBe(false);
});

// ---------------------------------------------------------------------------
// F28 — voluntary abort/unmount does NOT trigger fallback or reconnect
// ---------------------------------------------------------------------------
test("F28: unmount during clean stream does not trigger fallback or reconnect", async () => {
  // Use a half-open stream: first read delivers heartbeat (no terminal), second hangs.
  // This ensures unmount happens while the read loop is waiting, so voluntaryAbortRef
  // is set before the clean-close recovery path can run.
  const fetchSpy = jest.spyOn(global, "fetch").mockImplementation((url) => {
    if (url.includes("/garmin/sync/stream")) {
      let idx = 0;
      return Promise.resolve({
        ok: true,
        status: 200,
        body: {
          getReader() {
            return {
              read() {
                if (idx === 0) {
                  idx++;
                  return Promise.resolve({ done: false, value: encoder.encode(": heartbeat\n\n") });
                }
                // Second read hangs forever — simulates a half-open connection.
                return new Promise(() => {});
              },
              cancel: jest.fn(),
            };
          },
        },
      });
    }
    // Should NOT be called — /garmin/status must not be reached.
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ sync_status: { status: "complete" } }),
    });
  });

  const { unmount } = renderHook(() => useGarminSyncProgress({ enabled: true }));

  // Let the first read (heartbeat) be consumed; second read now hangs.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

  // Unmount while the hook is blocked on the second read.
  unmount();

  await act(async () => {
    jest.runAllTimers();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

  // /garmin/status must NOT have been called.
  const statusCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/status"));
  expect(statusCalls).toHaveLength(0);

  // No additional stream reconnect beyond the original one.
  const streamCalls = fetchSpy.mock.calls.filter(([u]) => u.includes("/garmin/sync/stream"));
  expect(streamCalls).toHaveLength(1);
});

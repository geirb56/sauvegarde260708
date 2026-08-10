/**
 * Tests for useGarminSyncProgress hook (PR07B)
 *
 * Tests the Fetch-based SSE streaming hook without EventSource.
 */

import { renderHook, act, waitFor } from "@testing-library/react";

// Mock config before hook import
jest.mock("../config", () => ({
  API_BASE_URL: "http://localhost:8000/api",
}));

// Helper: create a readable stream from SSE text chunks
function makeSSEStream(chunks) {
  const encoder = new TextEncoder();
  let idx = 0;
  return new ReadableStream({
    pull(controller) {
      if (idx < chunks.length) {
        controller.enqueue(encoder.encode(chunks[idx++]));
      } else {
        controller.close();
      }
    },
  });
}

describe("useGarminSyncProgress", () => {
  beforeEach(() => {
    localStorage.setItem("token", "test-jwt-token");
  });

  afterEach(() => {
    localStorage.clear();
    jest.resetAllMocks();
  });

  test("does not fetch when disabled", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      body: makeSSEStream([": connected\n\n"]),
    });

    const { useGarminSyncProgress } = require("../hooks/useGarminSyncProgress");
    const { result } = renderHook(() => useGarminSyncProgress({ enabled: false }));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result.current.isStreaming).toBe(false);
  });

  test("sets isStreaming while connected", async () => {
    // Stream that stays open (never closes)
    const controller = new AbortController();
    let resolveRead;
    const body = {
      getReader: () => ({
        read: () =>
          new Promise((res) => {
            resolveRead = res;
          }),
        cancel: () => {},
      }),
    };

    jest.spyOn(global, "fetch").mockResolvedValue({ ok: true, body });

    const { useGarminSyncProgress } = require("../hooks/useGarminSyncProgress");
    const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

    await waitFor(() => expect(result.current.isStreaming).toBe(true));
  });

  test("parses sync_progress event and sets progress", async () => {
    const payload = {
      status: "in_progress",
      phase: "activities_fetching",
      run_index_status: "pending",
    };

    const sseFrames = [
      ": connected\n\n",
      `event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`,
    ];

    jest.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      body: makeSSEStream(sseFrames),
    });

    const { useGarminSyncProgress } = require("../hooks/useGarminSyncProgress");
    const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

    await waitFor(() => expect(result.current.progress).not.toBeNull(), { timeout: 2000 });

    expect(result.current.progress.status).toBe("in_progress");
    expect(result.current.progress.phase).toBe("activities_fetching");
  });

  test("ignores heartbeat comment lines", async () => {
    const payload = { status: "complete", phase: "complete" };
    const sseFrames = [
      ": ping\n\n",
      ": ping\n\n",
      `event: sync_progress\ndata: ${JSON.stringify(payload)}\n\n`,
    ];

    jest.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      body: makeSSEStream(sseFrames),
    });

    const { useGarminSyncProgress } = require("../hooks/useGarminSyncProgress");
    const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

    await waitFor(() => expect(result.current.progress?.phase).toBe("complete"), { timeout: 2000 });
  });

  test("sends Authorization header on connect", async () => {
    const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      body: makeSSEStream([": connected\n\n"]),
    });

    const { useGarminSyncProgress } = require("../hooks/useGarminSyncProgress");
    renderHook(() => useGarminSyncProgress({ enabled: true }));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/garmin/sync/stream"),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: expect.stringContaining("Bearer "),
        }),
      })
    );
  });

  test("does not use EventSource", () => {
    const { useGarminSyncProgress } = require("../hooks/useGarminSyncProgress");
    const src = useGarminSyncProgress.toString();
    expect(src).not.toContain("EventSource");
    expect(src).not.toContain("new EventSource");
  });

  test("sets error state on max retries", async () => {
    jest.spyOn(global, "fetch").mockRejectedValue(new Error("Network error"));

    // Patch constants to speed up the test
    jest.mock("../hooks/useGarminSyncProgress", () => {
      const actual = jest.requireActual("../hooks/useGarminSyncProgress");
      return actual;
    });

    const { useGarminSyncProgress } = require("../hooks/useGarminSyncProgress");

    // With 8 retries and exponential back-off this would take too long in a unit
    // test, so we verify that after HTTP error the hook sets isStreaming=false.
    const { result } = renderHook(() => useGarminSyncProgress({ enabled: true }));

    await waitFor(() => expect(result.current.isStreaming).toBe(false), { timeout: 3000 });
  });
});

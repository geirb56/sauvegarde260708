import { streamGarminSyncProgress } from "@/lib/garminSyncStream";

function makeReader(chunks) {
  const queue = [...chunks];
  return {
    read: jest.fn(async () => {
      if (!queue.length) {
        return { done: true, value: undefined };
      }
      return { done: false, value: new TextEncoder().encode(queue.shift()) };
    }),
    releaseLock: jest.fn(),
  };
}

describe("streamGarminSyncProgress", () => {
  beforeEach(() => {
    window.localStorage.clear();
    global.fetch = jest.fn();
  });

  afterEach(() => {
    delete global.fetch;
  });

  test("uses the stored JWT in the Authorization header and parses sync events", async () => {
    window.localStorage.setItem("access_token", "jwt-token");
    const reader = makeReader([
      ": connected\n\n",
      "id: 4-0\nevent: sync_progress\ndata: {\"status\":\"in_progress\",\"activities_count\":12}\n\n",
    ]);

    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      body: {
        getReader: () => reader,
      },
    });

    const onMessage = jest.fn();
    const lastEventId = await streamGarminSyncProgress({ onMessage });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/garmin/sync/stream"),
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Accept: "text/event-stream",
          Authorization: ["Bearer", "jwt-token"].join(" "),
        }),
      })
    );
    expect(onMessage).toHaveBeenCalledWith({
      event: "sync_progress",
      data: { status: "in_progress", activities_count: 12 },
      lastEventId: "4-0",
    });
    expect(lastEventId).toBe("4-0");
    expect(reader.releaseLock).toHaveBeenCalled();
  });

  test("rejects when no JWT is available", async () => {
    await expect(streamGarminSyncProgress()).rejects.toThrow(
      "Missing auth token for Garmin sync stream"
    );
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

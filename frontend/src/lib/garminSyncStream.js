import { API_BASE_URL } from "@/config";

const TOKEN_KEY = "access_token";
const STREAM_PATH = `${API_BASE_URL}/garmin/sync/stream`;

function loadToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

function emitEvent({ eventName, dataLines, lastEventId, onMessage }) {
  if (!dataLines.length) {
    return;
  }

  const raw = dataLines.join("\n");
  let data = raw;

  if (eventName === "sync_progress") {
    data = JSON.parse(raw);
  }

  onMessage?.({
    event: eventName,
    data,
    lastEventId,
  });
}

export async function streamGarminSyncProgress({
  signal,
  lastEventId = null,
  onMessage,
} = {}) {
  const token = loadToken();
  if (!token) {
    throw new Error("Missing auth token for Garmin sync stream");
  }

  const headers = {
    Accept: "text/event-stream",
    Authorization: `******
  };

  if (lastEventId) {
    headers["Last-Event-ID"] = lastEventId;
  }

  const response = await fetch(STREAM_PATH, {
    method: "GET",
    headers,
    signal,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Garmin sync stream failed (${response.status})`);
  }

  if (!response.body) {
    throw new Error("Garmin sync stream body is unavailable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEventName = "message";
  let currentDataLines = [];
  let currentLastEventId = lastEventId;

  const flushEvent = () => {
    emitEvent({
      eventName: currentEventName,
      dataLines: currentDataLines,
      lastEventId: currentLastEventId,
      onMessage,
    });
    currentEventName = "message";
    currentDataLines = [];
  };

  const processBuffer = () => {
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      let line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);

      if (line.endsWith("\r")) {
        line = line.slice(0, -1);
      }

      if (!line) {
        flushEvent();
        newlineIndex = buffer.indexOf("\n");
        continue;
      }

      if (line.startsWith(":")) {
        newlineIndex = buffer.indexOf("\n");
        continue;
      }

      const separator = line.indexOf(":");
      const field = separator === -1 ? line : line.slice(0, separator);
      const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");

      if (field === "event") {
        currentEventName = value || "message";
      } else if (field === "data") {
        currentDataLines.push(value);
      } else if (field === "id") {
        currentLastEventId = value || currentLastEventId;
      }

      newlineIndex = buffer.indexOf("\n");
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        if (buffer) {
          buffer += "\n";
          processBuffer();
        }
        flushEvent();
        return currentLastEventId;
      }

      buffer += decoder.decode(value, { stream: true });
      processBuffer();
    }
  } finally {
    reader.releaseLock?.();
  }
}

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { setItem } from "@/lib/storage";

import { OFFLINE_CACHE_MAX_AGE_MS } from "./offlineCache";
import {
  clearOfflineSession,
  isNoAnswerError,
  isSessionRejected,
  readOfflineCommunities,
  readOfflineSession,
  saveOfflineCommunities,
  saveOfflineSession,
} from "./offlineSession";

const SERVER = "https://initiative.example";

beforeEach(() => {
  clearOfflineSession();
});

afterEach(() => {
  vi.useRealTimers();
  clearOfflineSession();
});

describe("the session snapshot", () => {
  it("hands back the user it was saved with, until it is cleared", () => {
    expect(readOfflineSession(SERVER)).toBeNull();
    const user = buildUser();
    saveOfflineSession(user, SERVER);
    expect(readOfflineSession(SERVER)?.id).toBe(user.id);
    clearOfflineSession();
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("is refused for a different server, and taken away with it", () => {
    saveOfflineSession(buildUser(), SERVER);
    expect(readOfflineSession("https://other.example")).toBeNull();
    // Cleared, so switching back does not resurrect it.
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("expires on the same clock as the cache it accompanies", () => {
    vi.useFakeTimers();
    saveOfflineSession(buildUser(), SERVER);
    vi.advanceTimersByTime(OFFLINE_CACHE_MAX_AGE_MS - 1000);
    expect(readOfflineSession(SERVER)).not.toBeNull();
    vi.advanceTimersByTime(2000);
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("discards a snapshot it cannot make sense of", () => {
    setItem("initiative-offline-session", "{not json");
    expect(readOfflineSession(SERVER)).toBeNull();
    setItem("initiative-offline-session", JSON.stringify({ savedAt: Date.now() }));
    expect(readOfflineSession(SERVER)).toBeNull();
  });
});

describe("the remembered community list", () => {
  it("hands back what was saved, for its own server, until the session goes", () => {
    saveOfflineCommunities([{ id: 3, name: "Beyonders" }], SERVER);
    expect(readOfflineCommunities<{ id: number }>(SERVER)).toEqual([{ id: 3, name: "Beyonders" }]);
    expect(readOfflineCommunities("https://other.example")).toBeNull();
    clearOfflineSession();
    expect(readOfflineCommunities(SERVER)).toBeNull();
  });

  it("expires on the same clock as everything else", () => {
    vi.useFakeTimers();
    saveOfflineCommunities([{ id: 3 }], SERVER);
    vi.advanceTimersByTime(OFFLINE_CACHE_MAX_AGE_MS + 1000);
    expect(readOfflineCommunities(SERVER)).toBeNull();
  });

  it("discards a list it cannot make sense of", () => {
    setItem("initiative-offline-guilds", "{not json");
    expect(readOfflineCommunities(SERVER)).toBeNull();
  });
});

describe("isSessionRejected", () => {
  // Only the server declining the credentials, or the account itself being
  // over (both come back from the current-user dependency as codes, not prose).
  // A bare 400 or 404 is too broad to read as the account being over.
  it.each([
    [{ response: { status: 401 } }, true],
    [{ response: { status: 400, data: { detail: "INACTIVE_USER" } } }, true],
    [{ response: { status: 404, data: { detail: "USER_NOT_FOUND" } } }, true],
    [{ response: { status: 500 } }, false],
    [{ response: { status: 502 } }, false],
    [{ response: { status: 503 } }, false],
    [{ response: { status: 403 } }, false],
    [{ response: { status: 404 } }, false],
    [{ response: { status: 400 } }, false],
    [{ response: { status: 400, data: { detail: "SOMETHING_ELSE" } } }, false],
    [{ request: {} }, false],
    [null, false],
  ])("reads %j as %s", (error, expected) => {
    expect(isSessionRejected(error)).toBe(expected);
  });
});

describe("isNoAnswerError", () => {
  // A request sent with nothing back, or a timeout; never a server that
  // answered (a 401 is the server speaking) or anything that is not a request.
  it.each([
    [{ request: {}, message: "Network Error" }, true],
    [{ code: "ECONNABORTED", message: "timeout" }, true],
    [{ request: {}, response: { status: 401 } }, false],
    [{ request: {}, response: { status: 403 } }, false],
    [{ request: {}, response: { status: 500 } }, false],
    [new Error("boom"), false],
    [null, false],
    ["nope", false],
  ])("reads %j as %s", (error, expected) => {
    expect(isNoAnswerError(error)).toBe(expected);
  });
});

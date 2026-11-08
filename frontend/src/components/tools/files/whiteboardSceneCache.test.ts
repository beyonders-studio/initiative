import { afterEach, describe, expect, it } from "vitest";

import { getItem, removeItem, setItem } from "@/lib/storage";

import type { WhiteboardScene } from "./WhiteboardFileEditor";
import {
  clearAllWhiteboardSceneCaches,
  clearWhiteboardSceneCache,
  loadWhiteboardScene,
  stampWhiteboardSceneCache,
} from "./whiteboardSceneCache";

const DOC_ID = 42;
const KEY = `wb-scene-${DOC_ID}`;

const scene = (label: string): WhiteboardScene =>
  ({
    elements: [{ id: label }],
    appState: {},
    files: {},
  }) as unknown as WhiteboardScene;

const writeCache = (label: string, savedAt: string) =>
  setItem(KEY, JSON.stringify({ scene: scene(label), savedAt }));

afterEach(() => removeItem(KEY));

describe("loadWhiteboardScene", () => {
  it("prefers the cached scene when it is newer than the server copy", () => {
    writeCache("cached", "2026-08-27T12:00:10Z");
    const result = loadWhiteboardScene(DOC_ID, "2026-08-27T12:00:00Z", scene("rest"));
    expect(result.fromCache).toBe(true);
    expect(result.scene.elements).toEqual([{ id: "cached" }]);
    // A winning cache entry is kept (it still represents unsaved work).
    expect(getItem(KEY)).not.toBeNull();
  });

  it("discards a cache entry that is older than the server copy", () => {
    // The rejoin case: another user kept editing after we left, so the
    // server's updated_at moved past our stamp — the cache must lose and
    // be removed so it can't shadow newer state later.
    writeCache("stale", "2026-08-27T12:00:00Z");
    const result = loadWhiteboardScene(DOC_ID, "2026-08-27T12:05:00Z", scene("rest"));
    expect(result.fromCache).toBe(false);
    expect(result.scene.elements).toEqual([{ id: "rest" }]);
    expect(getItem(KEY)).toBeNull();
  });

  it("removes an unparseable cache entry and falls back to REST content", () => {
    setItem(KEY, "{not json");
    const result = loadWhiteboardScene(DOC_ID, "2026-08-27T12:00:00Z", scene("rest"));
    expect(result.fromCache).toBe(false);
    expect(result.scene.elements).toEqual([{ id: "rest" }]);
    expect(getItem(KEY)).toBeNull();
  });

  it("normalizes missing REST content to an empty scene", () => {
    const result = loadWhiteboardScene(DOC_ID, "2026-08-27T12:00:00Z", null);
    expect(result.fromCache).toBe(false);
    expect(result.scene).toEqual({ elements: [], appState: {}, files: {} });
  });
});

describe("stampWhiteboardSceneCache / clearWhiteboardSceneCache", () => {
  it("stamps a scene that a subsequent load resolves as newer than an older server copy", () => {
    stampWhiteboardSceneCache(DOC_ID, scene("local"));
    const result = loadWhiteboardScene(DOC_ID, "2000-01-01T00:00:00Z", scene("rest"));
    expect(result.fromCache).toBe(true);
    expect(result.scene.elements).toEqual([{ id: "local" }]);
  });

  it("clear removes the entry", () => {
    stampWhiteboardSceneCache(DOC_ID, scene("local"));
    clearWhiteboardSceneCache(DOC_ID);
    expect(getItem(KEY)).toBeNull();
  });
});

describe("clearAllWhiteboardSceneCaches", () => {
  it("takes every whiteboard's scene off the device", () => {
    stampWhiteboardSceneCache(DOC_ID, scene("one"));
    stampWhiteboardSceneCache(DOC_ID + 1, scene("two"));

    clearAllWhiteboardSceneCaches();

    expect(getItem(KEY)).toBeNull();
    expect(getItem(`wb-scene-${DOC_ID + 1}`)).toBeNull();
  });

  it("leaves everything that is not a scene alone", () => {
    setItem("initiative-language", "en");
    stampWhiteboardSceneCache(DOC_ID, scene("one"));

    clearAllWhiteboardSceneCaches();

    expect(getItem("initiative-language")).toBe("en");
  });
});

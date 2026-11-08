/**
 * The whiteboard write-ahead cache: on every local edit the scene is written
 * to storage synchronously, so if the user leaves before the keepalive PATCH
 * lands the latest scene survives a refresh. Reading it back compares
 * timestamps against the server's `updated_at` — the cache only wins while
 * it is strictly newer than what the server has, and it must only ever be
 * stamped for *local* edits (a remote-applied update is not unsaved work,
 * and stamping it would make a watching session's cache shadow the live
 * room's newer state on a later revisit).
 */

import { getItem, listKeys, removeItem, setItem } from "@/lib/storage";

import type { WhiteboardScene } from "./WhiteboardFileEditor";

const CACHE_PREFIX = "wb-scene-";

const cacheKey = (fileId: number) => `${CACHE_PREFIX}${fileId}`;

export interface WhiteboardSceneLoad {
  scene: WhiteboardScene;
  /** True when the returned scene came from the write-ahead cache (i.e.
   *  there are local edits newer than the server's copy). */
  fromCache: boolean;
}

/** Write the scene to the write-ahead cache, stamped with the current time.
 *  Best-effort: storage being full or unavailable is not an error. */
export const stampWhiteboardSceneCache = (fileId: number, scene: WhiteboardScene): void => {
  try {
    setItem(cacheKey(fileId), JSON.stringify({ scene, savedAt: new Date().toISOString() }));
  } catch {
    // Storage full or unavailable — best-effort
  }
};

/** Drop the write-ahead cache (the server copy is now authoritative). */
export const clearWhiteboardSceneCache = (fileId: number): void => {
  removeItem(cacheKey(fileId));
};

/**
 * Drop every whiteboard's write-ahead cache. For signing out: these entries are
 * file content, and they outlived the session that was allowed to read
 * them — keyed by file id alone, with nothing to say whose they were.
 *
 * The cost is that unsaved edits do not survive a sign-out. That is the right
 * trade: signing out is deliberate, the keepalive PATCH has already run on the
 * way out of the file, and the alternative is leaving somebody's scene on
 * a device they have just signed off.
 */
export const clearAllWhiteboardSceneCaches = (): void => {
  for (const key of listKeys()) {
    if (key.startsWith(CACHE_PREFIX)) {
      removeItem(key);
    }
  }
};

/**
 * Resolve the scene to load for a whiteboard: the write-ahead cache when it
 * is strictly newer than the server's `updated_at`, otherwise the
 * REST-fetched `content`. A cache entry that loses the comparison (or fails
 * to parse) is removed. `updatedAt` must come from a fresh fetch — comparing
 * against a stale client-cached file makes the local cache look newer
 * than it is.
 */
export const loadWhiteboardScene = (
  fileId: number,
  updatedAt: string,
  content: Partial<WhiteboardScene> | null | undefined
): WhiteboardSceneLoad => {
  const key = cacheKey(fileId);
  try {
    const cached = getItem(key);
    if (cached) {
      const parsed = JSON.parse(cached) as {
        scene: WhiteboardScene;
        savedAt: string;
      };
      const cachedTs = new Date(parsed.savedAt).getTime();
      const serverTs = new Date(updatedAt).getTime();
      if (cachedTs > serverTs && parsed.scene?.elements) {
        return { scene: parsed.scene, fromCache: true };
      }
      removeItem(key);
    }
  } catch {
    removeItem(key);
  }

  return { scene: loadWhiteboardSceneFromContent(content), fromCache: false };
};

/** The scene a whiteboard's stored `content` holds, with nothing missing. */
export const loadWhiteboardSceneFromContent = (content: unknown): WhiteboardScene => {
  const raw = (content ?? {}) as Partial<WhiteboardScene>;
  return {
    elements: raw.elements ?? [],
    appState: raw.appState ?? {},
    files: raw.files ?? {},
  };
};

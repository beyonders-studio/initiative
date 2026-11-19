/**
 * A whiteboard's scene as its collaboration room holds it.
 *
 * Each element is its own entry, keyed by id, so an edit sends the elements it
 * changed rather than the whole drawing. Who holds the newer copy of an element
 * is settled by its version, as Excalidraw's own collaboration settles it: the
 * higher version wins, and a tie goes to the lower version nonce. A deleted
 * element stays as a tombstone (`isDeleted`) so its deletion is ordered against
 * edits made to it elsewhere.
 *
 * The server reads and writes the same layout (`body_states.py`).
 */

import type {
  ExcalidrawElement,
  OrderedExcalidrawElement,
} from "@excalidraw/excalidraw/element/types";
import type { AppState, BinaryFileData, BinaryFiles } from "@excalidraw/excalidraw/types";
import type * as Y from "yjs";

/** Root map names; root maps merge by name, so two clients can never each
 *  make their own. */
export const ROOM_ELEMENTS = "excalidraw.elements";
export const ROOM_FILES = "excalidraw.files";
export const ROOM_APP_STATE = "excalidraw.appState";

/** How long a deleted element's tombstone is kept: long enough for anybody
 *  still holding the element to hear it was deleted. */
export const TOMBSTONE_TTL_MS = 24 * 60 * 60 * 1000;

type RoomElement = ExcalidrawElement;

export interface RoomMaps {
  elements: Y.Map<RoomElement>;
  files: Y.Map<BinaryFileData>;
  appState: Y.Map<unknown>;
}

export function roomMaps(doc: Y.Doc): RoomMaps {
  return {
    elements: doc.getMap<RoomElement>(ROOM_ELEMENTS),
    files: doc.getMap<BinaryFileData>(ROOM_FILES),
    appState: doc.getMap<unknown>(ROOM_APP_STATE),
  };
}

/** The keys of `map` that `transaction` changed, if it changed any. */
export function changedKeys<T>(transaction: Y.Transaction, map: Y.Map<T>): Set<string> | undefined {
  const keys = (transaction.changed as Map<unknown, Set<string | null>>).get(map);
  if (!keys) return undefined;
  return new Set([...keys].filter((key): key is string => key !== null));
}

/** Whether the room holds a scene at all. */
export function roomHoldsScene(maps: RoomMaps): boolean {
  return maps.elements.size > 0 || maps.appState.size > 0;
}

/** A copy that shares nothing with the original. Yjs hands back the object it
 *  stores, and Excalidraw mutates the elements it is given, so neither side may
 *  hold the other's. */
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/** An element as the room stores it: as Excalidraw's database serializer
 *  writes it, without the point a line or arrow is still being drawn to. */
function toRoomElement(element: ExcalidrawElement): RoomElement {
  const stored = copy(element);
  if (stored.type === "arrow" || stored.type === "line") {
    return { ...stored, lastCommittedPoint: null };
  }
  return stored;
}

/** Whether `local` is a newer copy of an element than `room`'s. */
export function isNewer(local: ExcalidrawElement, room: ExcalidrawElement): boolean {
  return (
    local.version > room.version ||
    (local.version === room.version && local.versionNonce < room.versionNonce)
  );
}

/** Fractional-index order, ties by id, as Excalidraw orders a scene. */
function byIndex(a: ExcalidrawElement, b: ExcalidrawElement): number {
  const ai = a.index ?? "";
  const bi = b.index ?? "";
  if (ai !== bi) return ai < bi ? -1 : 1;
  return a.id < b.id ? -1 : 1;
}

/** The room's copies of `ids` (all of them when omitted), in scene order. */
export function readRoomElements(maps: RoomMaps, ids?: Iterable<string>): ExcalidrawElement[] {
  const out: ExcalidrawElement[] = [];
  if (ids) {
    for (const id of ids) {
      const element = maps.elements.get(id);
      if (element) out.push(copy(element));
    }
  } else {
    maps.elements.forEach((element) => {
      out.push(copy(element));
    });
  }
  return out.sort(byIndex);
}

/** The room's copies of `ids` (all of them when omitted). */
export function readRoomFiles(maps: RoomMaps, ids?: Iterable<string>): BinaryFileData[] {
  const out: BinaryFileData[] = [];
  const keys = ids ? [...ids] : [...maps.files.keys()];
  for (const id of keys) {
    const file = maps.files.get(id);
    if (file) out.push({ ...file });
  }
  return out;
}

export function readRoomAppState(maps: RoomMaps): Partial<AppState> {
  return copy(Object.fromEntries(maps.appState.entries())) as Partial<AppState>;
}

const randomNonce = () => Math.floor(Math.random() * 2 ** 31);

/**
 * `local`, with every element the room holds a newer or equal copy of moved
 * past it, so that writing them makes the room hold this scene. For a scene
 * that must win over the room's, such as unsaved work kept on the device.
 */
export function newestOver(
  local: readonly OrderedExcalidrawElement[],
  maps: RoomMaps
): OrderedExcalidrawElement[] {
  return local.map((element) => {
    const room = maps.elements.get(element.id);
    if (!room || isNewer(element, room)) return element;
    return { ...element, version: room.version + 1, versionNonce: randomNonce() };
  });
}

export interface WriteOptions {
  /** Delete what the room holds and `elements` does not. */
  replace?: boolean;
  /** For the tombstones `replace` writes. */
  now?: number;
}

/**
 * Write what changed in the local scene into the room, in one transaction:
 * the elements newer than the room's copy, the files they use that the room
 * lacks, and the persisted app state that differs. Returns whether anything
 * was written.
 */
export function writeToRoom(
  doc: Y.Doc,
  maps: RoomMaps,
  elements: readonly ExcalidrawElement[],
  persistedAppState: Partial<AppState>,
  files: BinaryFiles,
  { replace = false, now = Date.now() }: WriteOptions = {}
): boolean {
  let wrote = false;
  doc.transact(() => {
    const usedFiles = new Set<string>();
    for (const element of elements) {
      const room = maps.elements.get(element.id);
      // An element deleted before the room ever had it is nobody else's
      // business, and one whose tombstone has expired stays gone.
      const write = room ? isNewer(element, room) : !element.isDeleted;
      if (write) {
        maps.elements.set(element.id, toRoomElement(element));
        wrote = true;
      }
      const fileId = (element as { fileId?: string | null }).fileId;
      if (fileId && !element.isDeleted) usedFiles.add(fileId);
    }

    if (replace) {
      const present = new Set(elements.map((element) => element.id));
      maps.elements.forEach((room, id) => {
        if (present.has(id) || room.isDeleted) return;
        maps.elements.set(id, {
          ...copy(room),
          isDeleted: true,
          version: room.version + 1,
          versionNonce: randomNonce(),
          updated: now,
        });
        wrote = true;
      });
    }

    for (const id of usedFiles) {
      const file = files[id];
      if (file && !maps.files.has(id)) {
        maps.files.set(id, { ...file });
        wrote = true;
      }
    }

    for (const [key, value] of Object.entries(persistedAppState)) {
      if (JSON.stringify(maps.appState.get(key)) !== JSON.stringify(value)) {
        maps.appState.set(key, copy(value));
        wrote = true;
      }
    }
  });
  return wrote;
}

/** Drop the tombstones older than {@link TOMBSTONE_TTL_MS}. */
export function pruneTombstones(doc: Y.Doc, maps: RoomMaps, now = Date.now()): void {
  const expired: string[] = [];
  maps.elements.forEach((element, id) => {
    if (element.isDeleted && now - (element.updated ?? 0) > TOMBSTONE_TTL_MS) {
      expired.push(id);
    }
  });
  if (expired.length === 0) return;
  doc.transact(() => {
    for (const id of expired) maps.elements.delete(id);
  });
}

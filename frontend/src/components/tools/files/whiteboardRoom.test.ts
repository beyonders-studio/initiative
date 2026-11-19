import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type { BinaryFileData, BinaryFiles } from "@excalidraw/excalidraw/types";
import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import {
  changedKeys,
  newestOver,
  pruneTombstones,
  readRoomElements,
  roomHoldsScene,
  roomMaps,
  TOMBSTONE_TTL_MS,
  writeToRoom,
} from "./whiteboardRoom";

const element = (id: string, overrides: Record<string, unknown> = {}) =>
  ({
    id,
    type: "rectangle",
    index: `a${id}`,
    version: 1,
    versionNonce: 100,
    isDeleted: false,
    updated: 0,
    width: 10,
    ...overrides,
  }) as unknown as ExcalidrawElement;

const room = () => {
  const doc = new Y.Doc();
  return { doc, maps: roomMaps(doc) };
};

const write = (
  r: ReturnType<typeof room>,
  elements: ExcalidrawElement[],
  options: { files?: BinaryFiles; appState?: object; replace?: boolean; now?: number } = {}
) =>
  writeToRoom(r.doc, r.maps, elements, options.appState ?? {}, options.files ?? {}, {
    replace: options.replace,
    now: options.now,
  });

/** The updates `doc` sends while `fn` runs. */
const sent = (doc: Y.Doc, fn: () => void) => {
  const updates: Uint8Array[] = [];
  const onUpdate = (update: Uint8Array) => updates.push(update);
  doc.on("update", onUpdate);
  fn();
  doc.off("update", onUpdate);
  return updates;
};

describe("writeToRoom", () => {
  it("sends only the element that changed", () => {
    const r = room();
    const scene = Array.from({ length: 50 }, (_, i) => element(`e${i}`, { width: 100 + i }));
    write(r, scene);

    const moved = scene.map((el) => (el.id === "e7" ? { ...el, version: 2, width: 999 } : el));
    const updates = sent(r.doc, () => write(r, moved));

    expect(updates).toHaveLength(1);
    const peer = new Y.Doc();
    const peerMaps = roomMaps(peer);
    Y.applyUpdate(peer, Y.encodeStateAsUpdate(r.doc));
    expect(peerMaps.elements.get("e7")?.width).toBe(999);
    const text = new TextDecoder().decode(updates[0]);
    expect(text).toContain("e7");
    expect(text).not.toContain("e8");
  });

  it("writes nothing when the room already holds the scene", () => {
    const r = room();
    const scene = [element("a"), element("b")];
    write(r, scene);
    expect(write(r, scene)).toBe(false);
    expect(sent(r.doc, () => write(r, scene))).toHaveLength(0);
  });

  it("leaves a newer copy the room holds", () => {
    const r = room();
    write(r, [element("a", { version: 5, width: 50 })]);
    expect(write(r, [element("a", { version: 3, width: 1 })])).toBe(false);
    expect(r.maps.elements.get("a")?.width).toBe(50);
  });

  it("settles a tie on the lower nonce", () => {
    const r = room();
    write(r, [element("a", { version: 3, versionNonce: 200 })]);
    expect(write(r, [element("a", { version: 3, versionNonce: 100 })])).toBe(true);
    expect(write(r, [element("a", { version: 3, versionNonce: 300 })])).toBe(false);
  });

  it("sends a deletion as a tombstone", () => {
    const r = room();
    write(r, [element("a")]);
    write(r, [element("a", { version: 2, isDeleted: true })]);
    expect(r.maps.elements.get("a")?.isDeleted).toBe(true);
  });

  it("keeps an element deleted before the room had it to itself", () => {
    const r = room();
    expect(write(r, [element("a", { isDeleted: true })])).toBe(false);
    expect(r.maps.elements.has("a")).toBe(false);
  });

  it("stores a copy, not the scene's own object", () => {
    const r = room();
    const local = element("a") as { width: number } & ExcalidrawElement;
    write(r, [local]);
    local.width = 500;
    expect(r.maps.elements.get("a")?.width).toBe(10);
  });

  it("clears the point a line is still being drawn to", () => {
    const r = room();
    write(r, [element("a", { type: "arrow", lastCommittedPoint: [1, 2] })]);
    expect(
      (r.maps.elements.get("a") as unknown as { lastCommittedPoint: unknown }).lastCommittedPoint
    ).toBeNull();
  });

  it("sends a file once, and only one a live element uses", () => {
    const r = room();
    const file = {
      id: "f1",
      dataURL: "data:x",
      mimeType: "image/png",
    } as unknown as BinaryFileData;
    const unused = { ...file, id: "f2" } as BinaryFileData;
    const files = { f1: file, f2: unused } as BinaryFiles;
    write(r, [element("a", { type: "image", fileId: "f1" })], { files });
    expect([...r.maps.files.keys()]).toEqual(["f1"]);
    expect(
      sent(r.doc, () => write(r, [element("a", { type: "image", fileId: "f1" })], { files }))
    ).toHaveLength(0);
  });

  it("sends the app state that changed", () => {
    const r = room();
    write(r, [], { appState: { viewBackgroundColor: "#fff", gridSize: 20 } });
    write(r, [], { appState: { viewBackgroundColor: "#000", gridSize: 20 } });
    expect(r.maps.appState.get("viewBackgroundColor")).toBe("#000");
  });

  it("deletes what the room holds and the scene lacks, when replacing", () => {
    const r = room();
    write(r, [element("a", { version: 4 }), element("b")]);
    write(r, [element("b")], { replace: true, now: 1234 });
    const held = r.maps.elements.get("a");
    expect(held?.isDeleted).toBe(true);
    expect(held?.version).toBe(5);
    expect(held?.updated).toBe(1234);
  });
});

describe("newestOver", () => {
  it("moves an element past the room's copy", () => {
    const r = room();
    write(r, [element("a", { version: 9 })]);
    const [bumped] = newestOver([element("a", { version: 2 }) as never], r.maps);
    expect(bumped.version).toBe(10);
  });

  it("leaves an element already newer, or one the room lacks", () => {
    const r = room();
    write(r, [element("a", { version: 2 })]);
    const newer = element("a", { version: 3 });
    const fresh = element("b");
    expect(newestOver([newer, fresh] as never[], r.maps)).toEqual([newer, fresh]);
  });
});

describe("reading the room", () => {
  it("lists elements in scene order, as copies", () => {
    const r = room();
    write(r, [element("b", { index: "a2" }), element("a", { index: "a1" })]);
    const read = readRoomElements(r.maps);
    expect(read.map((el) => el.id)).toEqual(["a", "b"]);
    (read[0] as { width: number }).width = 77;
    expect(r.maps.elements.get("a")?.width).toBe(10);
  });

  it("names the keys a remote transaction changed", () => {
    const a = room();
    const b = room();
    write(a, [element("x"), element("y")]);
    Y.applyUpdate(b.doc, Y.encodeStateAsUpdate(a.doc));

    let changed: Set<string> | undefined;
    b.doc.on("afterTransaction", (tr: Y.Transaction) => {
      changed = changedKeys(tr, b.maps.elements);
    });
    const before = Y.encodeStateVector(a.doc);
    write(a, [element("x"), element("y", { version: 2 })]);
    Y.applyUpdate(b.doc, Y.encodeStateAsUpdate(a.doc, before));
    expect(changed).toEqual(new Set(["y"]));
  });

  it("holds a scene once anything is written", () => {
    const r = room();
    expect(roomHoldsScene(r.maps)).toBe(false);
    write(r, [element("a")]);
    expect(roomHoldsScene(r.maps)).toBe(true);
  });
});

describe("pruneTombstones", () => {
  it("drops tombstones past their time, and keeps the rest", () => {
    const r = room();
    const now = 10 * TOMBSTONE_TTL_MS;
    write(r, [
      element("old", { isDeleted: false }),
      element("recent", { isDeleted: false }),
      element("live"),
    ]);
    write(r, [
      element("old", { version: 2, isDeleted: true, updated: now - TOMBSTONE_TTL_MS - 1 }),
      element("recent", { version: 2, isDeleted: true, updated: now - 1 }),
    ]);
    pruneTombstones(r.doc, r.maps, now);
    expect([...r.maps.elements.keys()].sort()).toEqual(["live", "recent"]);
  });
});

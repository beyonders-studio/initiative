import { act, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { createYjsUndoManager, matchHistoryShortcut, useYjsHistory } from "./useYjsHistory";

const TRACKED = ["spreadsheet-edit"];
const scope = (d: Y.Doc) => [d.getMap("cells"), d.getMap("meta")];

describe("createYjsUndoManager", () => {
  it("returns null when there is no doc or empty scope", () => {
    expect(createYjsUndoManager(null, { getScope: scope, trackedOrigins: TRACKED })).toBeNull();
    expect(
      createYjsUndoManager(new Y.Doc(), { getScope: () => [], trackedOrigins: TRACKED })
    ).toBeNull();
  });
});

describe("useYjsHistory (React lifecycle)", () => {
  it("still tracks edits after a StrictMode mount/remount cycle", () => {
    const doc = new Y.Doc();
    const cells = doc.getMap("cells");
    const { result } = renderHook(
      () => useYjsHistory({ doc, getScope: scope, trackedOrigins: TRACKED }),
      { wrapper: StrictMode }
    );

    expect(result.current.canUndo).toBe(false);

    // A tracked edit after the (double-invoked) effects have settled must
    // still flip canUndo — i.e. the UndoManager survived StrictMode's
    // simulated unmount and is still observing the doc.
    act(() => {
      doc.transact(() => cells.set("0:0", "a"), "spreadsheet-edit");
    });
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(cells.has("0:0")).toBe(false);
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.redo());
    expect(cells.get("0:0")).toBe("a");
  });
});

describe("matchHistoryShortcut", () => {
  const ev = (over: Partial<Parameters<typeof matchHistoryShortcut>[0]>) => ({
    key: "a",
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    ...over,
  });

  it("maps mod+Z to undo and mod+Shift+Z / mod+Y to redo", () => {
    expect(matchHistoryShortcut(ev({ key: "z", ctrlKey: true }))).toBe("undo");
    expect(matchHistoryShortcut(ev({ key: "Z", metaKey: true }))).toBe("undo");
    expect(matchHistoryShortcut(ev({ key: "z", metaKey: true, shiftKey: true }))).toBe("redo");
    expect(matchHistoryShortcut(ev({ key: "y", ctrlKey: true }))).toBe("redo");
  });

  it("returns null without a modifier or for unrelated keys", () => {
    expect(matchHistoryShortcut(ev({ key: "z" }))).toBeNull();
    expect(matchHistoryShortcut(ev({ key: "x", ctrlKey: true }))).toBeNull();
  });
});

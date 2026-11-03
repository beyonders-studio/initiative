import { createEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { LEGACY_NODES, registerLegacyNodes } from "@/components/ui/editor/nodes/legacy-nodes";

const text = (extra: Record<string, unknown>) => ({
  detail: 0,
  format: 0,
  mode: "normal",
  style: "",
  version: 1,
  ...extra,
});

/** What one node of a stored document is, once today's editor has opened it. */
type Opened = { type: string; text: string };

function opened(children: Record<string, unknown>[]): Opened[] {
  const editor = createEditor({
    nodes: LEGACY_NODES,
    onError: (error) => {
      throw error;
    },
  });
  editor.setEditorState(
    editor.parseEditorState(
      JSON.stringify({
        root: {
          children: [
            { children, direction: null, format: "", indent: 0, type: "paragraph", version: 1 },
          ],
          direction: null,
          format: "",
          indent: 0,
          type: "root",
          version: 1,
        },
      })
    )
  );
  registerLegacyNodes(editor);

  const found: Opened[] = [];
  editor.getEditorState().read(() => {
    for (const node of editor.getEditorState()._nodeMap.values()) {
      if (node.getType() === "root" || node.getType() === "paragraph") continue;
      found.push({ type: node.getType(), text: node.getTextContent() });
    }
  });
  return found;
}

describe("a document written before references were one thing", () => {
  it("reads a stored hashtag as the word it looks like", () => {
    // `#` is the reference trigger now, and the picker reads what is being
    // typed out of ordinary text — a hashtag of its own is not that.
    expect(opened([text({ type: "hashtag", text: "#launch" })])).toEqual([
      { type: "text", text: "#launch" },
    ]);
  });
});

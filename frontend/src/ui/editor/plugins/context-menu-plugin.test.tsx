import fs from "node:fs";
import path from "node:path";

import { fireEvent, waitFor } from "@testing-library/react";
import type { SerializedEditorState } from "lexical";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
// Smart chips are Initiative's, so a document holding one opens in its editor.
import { Editor as InitiativeEditor } from "@/components/editor/editor";
import { Editor } from "@/ui/editor/editor";

// Read from the frontend folder rather than imported: the tests' CSS setting
// (`css: false`) empties every stylesheet import, `?raw` ones too.
const THEME_CSS = fs.readFileSync(
  path.join(process.cwd(), "src/ui/editor/themes/editor-theme.css"),
  "utf-8"
);

const STATE = {
  root: {
    type: "root",
    version: 1,
    direction: null,
    format: "",
    indent: 0,
    children: [
      {
        type: "paragraph",
        version: 1,
        direction: null,
        format: "",
        indent: 0,
        textFormat: 0,
        textStyle: "",
        children: [
          { type: "text", version: 1, detail: 0, format: 0, mode: "normal", style: "", text: "Hi" },
        ],
      },
    ],
  },
};

/** "Hi " followed by a smart chip, in one paragraph. */
const CHIP_STATE = {
  root: {
    ...STATE.root,
    children: [
      {
        ...STATE.root.children[0],
        children: [
          { ...STATE.root.children[0].children[0], text: "Hi " },
          { type: "smart-chip", version: 1, chipKind: "task:due", entityId: 1, text: "Friday" },
        ],
      },
    ],
  },
};

/** The rule in the editor theme that lifts the menu's overlay, and its z-index. */
const overlayRule = (): { selector: string; zIndex: number } => {
  const match = THEME_CSS.match(/([^{}]*\.EditorContextMenu[^{}]*)\{([^}]*)\}/);
  if (!match) throw new Error("editor-theme.css has no rule for .EditorContextMenu");
  const zIndex = match[2].match(/z-index:\s*(\d+)/);
  if (!zIndex) throw new Error("the .EditorContextMenu rule sets no z-index");
  return { selector: match[1].trim(), zIndex: Number(zIndex[1]) };
};

describe("the editor's right-click menu", () => {
  // The menu opens inside a fixed, full-window overlay, which is its own
  // stacking context: the menu's z-index only orders it within the overlay, so
  // the overlay is what has to sit above the editor's sticky bars (z-10).
  it("lifts the overlay it opens in above the sticky bars", async () => {
    renderPage(() => <Editor editorSerializedState={STATE as unknown as SerializedEditorState} />);

    const content = await waitFor(() => {
      const element = document.querySelector<HTMLElement>("[contenteditable]");
      if (!element?.textContent?.includes("Hi")) throw new Error("the editor has not rendered");
      return element;
    });
    fireEvent.contextMenu(content.querySelector("span") ?? content);

    const menu = await waitFor(() => {
      const element = document.querySelector<HTMLElement>(".EditorContextMenu");
      if (!element) throw new Error("the menu did not open");
      return element;
    });
    const overlay = menu.parentElement;
    if (!overlay) throw new Error("the menu has no parent");

    expect(overlay.style.position).toBe("fixed");
    const rule = overlayRule();
    expect(overlay.matches(rule.selector)).toBe(true);
    expect(rule.zIndex).toBeGreaterThan(10);
  });

  it("deletes the chip it was opened on", async () => {
    renderPage(() => (
      <InitiativeEditor editorSerializedState={CHIP_STATE as unknown as SerializedEditorState} />
    ));

    const chip = await waitFor(() => {
      const element = document.querySelector<HTMLElement>("[data-lexical-decorator]");
      if (!element) throw new Error("the chip has not rendered");
      return element;
    });
    fireEvent.contextMenu(chip);

    const deleteItem = await waitFor(() => {
      const item = Array.from(
        document.querySelectorAll<HTMLElement>(".EditorContextMenu [role=menuitem]")
      ).find((element) => element.textContent?.includes("Delete Node"));
      if (!item) throw new Error("the menu has no Delete Node item");
      return item;
    });
    fireEvent.click(deleteItem);

    await waitFor(() => {
      expect(document.querySelector("[data-lexical-decorator]")).toBeNull();
    });
    expect(document.querySelector("[contenteditable]")?.textContent).toContain("Hi");
  });
});

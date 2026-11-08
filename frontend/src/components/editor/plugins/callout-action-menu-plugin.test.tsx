import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SerializedEditorState } from "lexical";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/editor/editor";

const paragraph = (text: string) => ({
  type: "paragraph",
  version: 1,
  direction: null,
  format: "",
  indent: 0,
  textFormat: 0,
  textStyle: "",
  children: [{ type: "text", version: 1, detail: 0, format: 0, mode: "normal", style: "", text }],
});

const callout = (variant: string, text: string) => ({
  type: "callout",
  version: 1,
  variant,
  direction: null,
  format: "",
  indent: 0,
  children: [paragraph(text)],
});

const STATE = {
  root: {
    type: "root",
    version: 1,
    direction: null,
    format: "",
    indent: 0,
    children: [callout("info", "First"), callout("note", "Second")],
  },
};

describe("a callout's icon", () => {
  it("opens the menu that changes its kind, on any callout", async () => {
    const saved: SerializedEditorState[] = [];
    renderPage(() => (
      <Editor
        editorSerializedState={STATE as unknown as SerializedEditorState}
        onSerializedChange={(state) => saved.push(state)}
      />
    ));

    await waitFor(() => expect(document.querySelectorAll("[data-callout]")).toHaveLength(2));
    const second = document.querySelectorAll<HTMLElement>("[data-callout]")[1];
    const icon = second.querySelector<HTMLElement>(":scope > .callout-icon");
    if (!icon) throw new Error("the callout drew no icon");

    fireEvent.pointerDown(icon);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Warning" }));

    await waitFor(() => {
      const variants = saved
        .at(-1)
        ?.root.children.map((node) => (node as { variant?: string }).variant);
      expect(variants).toEqual(["info", "warning"]);
    });
  });
});

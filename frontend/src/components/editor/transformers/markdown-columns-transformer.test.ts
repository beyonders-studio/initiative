import { buildEditorFromExtensions } from "@lexical/extension";
import { ListExtension } from "@lexical/list";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import { RichTextExtension } from "@lexical/rich-text";
import { $getRoot, defineExtension, type ElementNode, type LexicalEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { CalloutExtension } from "@/components/editor/extensions/callout-extension";
import { LayoutExtension } from "@/components/editor/extensions/layout-extension";
import { markdownTransformers } from "@/components/editor/extensions/markdown-shortcuts-extension";
import { $isLayoutContainerNode } from "@/components/editor/nodes/layout-container-node";
import {
  templateFromWidths,
  widthsFromTemplate,
} from "@/components/editor/transformers/markdown-columns-transformer";

const transformers = markdownTransformers([]);

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(
    defineExtension({
      name: "@test/columns",
      dependencies: [RichTextExtension, ListExtension, LayoutExtension, CalloutExtension],
      onError: (error) => {
        throw error;
      },
    })
  );
}

const SOURCE = [
  ":::: {.columns}",
  '::: {.column width="25%"}',
  "The narrow one.",
  ":::",
  '::: {.column width="75%"}',
  "- a list",
  "- in the wide one",
  ":::",
  "::::",
];

describe("columns in markdown", () => {
  it("are Pandoc's fenced divs, both ways", () => {
    const editor = makeEditor();
    let exported = "";
    editor.update(() => $convertFromMarkdownString(SOURCE.join("\n"), transformers), {
      discrete: true,
    });
    editor.getEditorState().read(() => {
      const container = $getRoot().getFirstChild();
      expect($isLayoutContainerNode(container) && container.getTemplateColumns()).toBe("1fr 3fr");
      const [narrow, wide] = $isLayoutContainerNode(container)
        ? container.getChildren<ElementNode>()
        : [];
      expect(narrow?.getTextContent()).toBe("The narrow one.");
      expect(wide?.getFirstChild()?.getType()).toBe("list");
      exported = $convertToMarkdownString(transformers);
    });
    expect(exported.split("\n")).toEqual(SOURCE);
  });

  it("read the short form, and share out a column with no width", () => {
    const editor = makeEditor();
    editor.update(
      () =>
        $convertFromMarkdownString(
          [
            ":::: columns",
            "::: column",
            "one",
            ":::",
            "::: column",
            "two",
            ":::",
            "::::",
            "after",
          ].join("\n"),
          transformers
        ),
      { discrete: true }
    );
    editor.getEditorState().read(() => {
      const [container, after] = $getRoot().getChildren();
      expect($isLayoutContainerNode(container) && container.getTemplateColumns()).toBe("1fr 1fr");
      expect(after.getTextContent()).toBe("after");
    });
  });

  it("turn a template into widths and back", () => {
    expect(widthsFromTemplate("1fr 2fr 1fr")).toEqual([25, 50, 25]);
    expect(templateFromWidths([25, 50, 25])).toBe("1fr 2fr 1fr");
    expect(templateFromWidths(widthsFromTemplate("1fr 1fr 1fr"))).toBe("1fr 1fr 1fr");
    expect(templateFromWidths([30, null])).toBe("3fr 7fr");
  });
});

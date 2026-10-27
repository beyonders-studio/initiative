import { buildEditorFromExtensions } from "@lexical/extension";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $isParagraphNode,
  type LexicalEditor,
} from "lexical";
import { describe, expect, it } from "vitest";

import { documentExtension } from "@/components/ui/editor/document-extension";
import { MARKDOWN_TRANSFORMERS } from "@/components/ui/editor/extensions/markdown-shortcuts-extension";
import {
  $createEntityMentionNode,
  $isEntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";
import { $createMentionNode, $isMentionNode } from "@/components/ui/editor/nodes/mention-node";
import { $isReferenceEmbedNode } from "@/components/ui/editor/nodes/reference-embed-node";
import {
  $createSmartChipNode,
  $isSmartChipNode,
} from "@/components/ui/editor/nodes/smart-chip-node";

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(documentExtension({ collaborative: false, editable: true }));
}

function update(editor: LexicalEditor, fn: () => void) {
  editor.update(fn, { discrete: true });
}

const toMarkdown = (editor: LexicalEditor) =>
  editor.getEditorState().read(() => $convertToMarkdownString(MARKDOWN_TRANSFORMERS));

const fromMarkdown = (markdown: string) => {
  const editor = makeEditor();
  update(editor, () => $convertFromMarkdownString(markdown, MARKDOWN_TRANSFORMERS));
  return editor;
};

/** Each node of the first paragraph, described. */
const inline = (editor: LexicalEditor): string[] =>
  editor.getEditorState().read(() => {
    const paragraph = $getRoot().getFirstChild();
    if (!$isParagraphNode(paragraph)) throw new Error("no paragraph");
    return paragraph.getChildren().map((node) => {
      if ($isSmartChipNode(node)) return `chip ${node.getRef()} ${node.getTextContent()}`;
      if ($isEntityMentionNode(node)) {
        return `link ${node.getEntityType()}:${node.getEntityId()} ${node.getTextContent()}`;
      }
      if ($isMentionNode(node)) return `person ${node.getMentionUserId()} ${node.getTextContent()}`;
      return `text ${node.getTextContent()}`;
    });
  });

describe("references in markdown", () => {
  it("survive the trip there and back", () => {
    const editor = makeEditor();
    update(editor, () => {
      $getRoot()
        .clear()
        .append(
          $createParagraphNode().append(
            $createTextNode("Ask "),
            $createMentionNode("Ada", 4),
            $createTextNode(" about "),
            $createEntityMentionNode("task", 12, "Roll call"),
            $createTextNode(", now "),
            $createSmartChipNode("task:status", 12, "Roll call"),
            $createTextNode(" and "),
            $createSmartChipNode("calendar_event:when", 3, "Kickoff")
          )
        );
    });

    const markdown = toMarkdown(editor);
    // The person goes by id alone: their name is read when the chip is drawn.
    expect(markdown).toBe(
      "Ask @[](4) about [[task:12|Roll call]], now [[task:12:status|Roll call]] and [[calendar_event:3:when|Kickoff]]"
    );

    expect(inline(fromMarkdown(markdown))).toEqual([
      "text Ask ",
      "person 4 ",
      "text  about ",
      "link task:12 Roll call",
      "text , now ",
      "chip task:12:status Roll call",
      "text  and ",
      "chip calendar_event:3:when Kickoff",
    ]);
  });

  it("keep a name that holds the brackets they are written with", () => {
    const editor = makeEditor();
    update(editor, () => {
      $getRoot()
        .clear()
        .append(
          $createParagraphNode().append($createEntityMentionNode("task", 12, "A | B [draft]"))
        );
    });
    expect(inline(fromMarkdown(toMarkdown(editor)))).toEqual(["link task:12 A  B [draft"]);
  });

  it("keep the name of somebody with no account, and drop it for somebody with one", () => {
    expect(inline(fromMarkdown("Hi @[Ada]()"))).toEqual(["text Hi ", "person null Ada"]);
    expect(inline(fromMarkdown("Hi @[Ada](4)"))).toEqual(["text Hi ", "person 4 "]);
    expect(toMarkdown(fromMarkdown("Hi @[Ada]() and @[Ada](4)"))).toBe("Hi @[Ada]() and @[](4)");
  });

  it("leave something this build cannot show as the words it was written as", () => {
    expect(inline(fromMarkdown("[[task:12:mood|Roll call]]"))).toEqual([
      "text [[task:12:mood|Roll call]]",
    ]);
  });

  it("leave an embed an embed", () => {
    const editor = fromMarkdown("![[task:12|Roll call]]");
    editor.getEditorState().read(() => {
      expect($isReferenceEmbedNode($getRoot().getFirstChild())).toBe(true);
    });
  });

  it("come back from inside a table cell, the pipe escaped as a table needs", () => {
    const row = "| [[task:12\\|Roll call]] | [[task:12:status\\|Roll call]] |";
    const editor = fromMarkdown(["| Task | State |", "| --- | --- |", row].join("\n"));
    const saved = JSON.stringify(editor.getEditorState().toJSON());
    expect(saved).toContain('"type":"entity-mention"');
    expect(saved).toContain('"type":"smart-chip"');
    expect(toMarkdown(editor).split("\n")[2]).toBe(row);
  });
});

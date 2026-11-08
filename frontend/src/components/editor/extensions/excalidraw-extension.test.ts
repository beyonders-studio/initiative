import { CodeExtension } from "@lexical/code";
import { buildEditorFromExtensions } from "@lexical/extension";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import { RichTextExtension } from "@lexical/rich-text";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  defineExtension,
  type ElementNode,
  type LexicalEditor,
  type SerializedLexicalNode,
} from "lexical";
import { describe, expect, it } from "vitest";

import {
  ExcalidrawExtension,
  INSERT_EXCALIDRAW_COMMAND,
} from "@/components/editor/extensions/excalidraw-extension";
import { MARKDOWN_TRANSFORMERS } from "@/components/editor/extensions/markdown-shortcuts-extension";
import {
  $createExcalidrawNode,
  $isExcalidrawNode,
  EMPTY_DRAWING,
} from "@/components/editor/nodes/excalidraw-node";

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(
    defineExtension({
      name: "@test/drawing",
      dependencies: [RichTextExtension, CodeExtension, ExcalidrawExtension],
      onError: (error) => {
        throw error;
      },
    })
  );
}

const SCENE = JSON.stringify({
  elements: [{ id: "a", type: "rectangle", isDeleted: false }],
  appState: { viewBackgroundColor: "#ffffff" },
  files: {},
});

describe("a drawing in a document", () => {
  it("is saved with its scene and read back", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        $getRoot()
          .clear()
          .append($createParagraphNode().append($createExcalidrawNode(SCENE, 320)));
      },
      { discrete: true }
    );
    const json = editor.getEditorState().toJSON();
    const paragraph = json.root.children[0] as SerializedLexicalNode & {
      children: Array<SerializedLexicalNode & { data?: string; width?: number }>;
    };
    expect(paragraph.children[0]).toEqual({
      type: "excalidraw",
      version: 1,
      data: SCENE,
      width: 320,
    });

    const restored = makeEditor();
    restored.setEditorState(restored.parseEditorState(json));
    restored.getEditorState().read(() => {
      const node = $getRoot().getFirstDescendant();
      expect($isExcalidrawNode(node) && node.getData()).toBe(SCENE);
    });
  });

  it("is inserted empty, inside a line of its own", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        const paragraph = $createParagraphNode();
        $getRoot().clear().append(paragraph);
        paragraph.select();
      },
      { discrete: true }
    );
    editor.update(() => editor.dispatchCommand(INSERT_EXCALIDRAW_COMMAND, undefined), {
      discrete: true,
    });
    editor.getEditorState().read(() => {
      const paragraph = $getRoot().getFirstChild<ElementNode>();
      const node = paragraph?.getFirstDescendant?.() ?? null;
      expect(paragraph?.getType()).toBe("paragraph");
      expect($isExcalidrawNode(node) && node.getData()).toBe(EMPTY_DRAWING);
    });
  });
});

describe("a drawing in markdown", () => {
  it("is a fenced excalidraw block, both ways", () => {
    const editor = buildEditorFromExtensions(
      defineExtension({
        name: "@test/drawing-markdown",
        dependencies: [RichTextExtension, ExcalidrawExtension],
        onError: (error) => {
          throw error;
        },
      })
    );
    const tricky = JSON.stringify({
      elements: [{ id: "t", type: "text", text: "```not the end```", isDeleted: false }],
      appState: {},
      files: {},
    });
    let exported = "";
    editor.update(
      () => {
        $getRoot()
          .clear()
          .append(
            $createParagraphNode().append($createTextNode("Before")),
            $createParagraphNode().append($createExcalidrawNode(tricky)),
            $createParagraphNode().append($createTextNode("After"))
          );
      },
      { discrete: true }
    );
    editor.getEditorState().read(() => {
      exported = $convertToMarkdownString(MARKDOWN_TRANSFORMERS);
    });
    // Longer than the backticks the drawing holds, so they cannot close it.
    expect(exported).toContain("````excalidraw\n");

    const restored = makeEditor();
    restored.update(() => $convertFromMarkdownString(exported, MARKDOWN_TRANSFORMERS), {
      discrete: true,
    });
    restored.getEditorState().read(() => {
      const [before, drawing, after] = $getRoot().getChildren<ElementNode>();
      expect(before.getTextContent()).toBe("Before");
      const node = drawing.getFirstDescendant?.() ?? null;
      expect($isExcalidrawNode(node) && node.getData()).toBe(tricky);
      expect(after.getTextContent()).toBe("After");
    });
  });

  it("leaves a fence whose contents are not a scene to be code", () => {
    const editor = makeEditor();
    editor.update(
      () => $convertFromMarkdownString("```excalidraw\nnot json\n```", MARKDOWN_TRANSFORMERS),
      { discrete: true }
    );
    editor.getEditorState().read(() => {
      expect($getRoot().getFirstChild()?.getType()).toBe("code");
    });
  });
});

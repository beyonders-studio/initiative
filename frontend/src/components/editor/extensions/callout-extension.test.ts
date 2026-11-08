import { buildEditorFromExtensions } from "@lexical/extension";
import { ListExtension } from "@lexical/list";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import { RichTextExtension } from "@lexical/rich-text";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  defineExtension,
  INSERT_PARAGRAPH_COMMAND,
  KEY_BACKSPACE_COMMAND,
  type LexicalEditor,
  type SerializedLexicalNode,
} from "lexical";
import { describe, expect, it } from "vitest";

import {
  CalloutExtension,
  INSERT_CALLOUT_COMMAND,
} from "@/components/editor/extensions/callout-extension";
import { MARKDOWN_TRANSFORMERS } from "@/components/editor/extensions/markdown-shortcuts-extension";
import {
  $createCalloutNode,
  $isCalloutNode,
  calloutVariantFrom,
} from "@/components/editor/nodes/callout-node";

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(
    defineExtension({
      name: "@test/callout",
      dependencies: [RichTextExtension, ListExtension, CalloutExtension],
      onError: (error) => {
        throw error;
      },
    })
  );
}

function update(editor: LexicalEditor, fn: () => void) {
  editor.update(fn, { discrete: true });
}

function rootJSON(editor: LexicalEditor) {
  return editor.getEditorState().toJSON().root.children as Array<
    SerializedLexicalNode & { children?: SerializedLexicalNode[]; variant?: string }
  >;
}

describe("callouts", () => {
  it("are saved with their kind and read back", () => {
    const editor = makeEditor();
    update(editor, () => {
      $getRoot()
        .clear()
        .append(
          $createCalloutNode("warning").append(
            $createParagraphNode().append($createTextNode("Mind the step"))
          )
        );
    });
    const [callout] = rootJSON(editor);
    expect(callout).toMatchObject({ type: "callout", variant: "warning", version: 1 });

    const restored = makeEditor();
    restored.setEditorState(restored.parseEditorState(editor.getEditorState().toJSON()));
    restored.getEditorState().read(() => {
      const node = $getRoot().getFirstChild();
      expect($isCalloutNode(node) && node.getVariant()).toBe("warning");
      expect(node?.getTextContent()).toBe("Mind the step");
    });
  });

  it("read another tool's names for a kind, and a note for one they do not know", () => {
    expect(calloutVariantFrom("INFO")).toBe("info");
    expect(calloutVariantFrom("danger")).toBe("error");
    expect(calloutVariantFrom("caution")).toBe("warning");
    expect(calloutVariantFrom("something-new")).toBe("note");
    expect(calloutVariantFrom(null)).toBe("note");
  });

  it("wrap the line the caret is on when inserted", () => {
    const editor = makeEditor();
    update(editor, () => {
      const paragraph = $createParagraphNode().append($createTextNode("Heads up"));
      $getRoot().clear().append(paragraph);
      paragraph.selectEnd();
    });
    update(editor, () => {
      editor.dispatchCommand(INSERT_CALLOUT_COMMAND, "tip");
    });
    const [callout] = rootJSON(editor);
    expect(callout).toMatchObject({ type: "callout", variant: "tip" });
    expect(callout.children?.[0]).toMatchObject({ type: "paragraph" });
  });

  it("let Enter on an empty last line step out below", () => {
    const editor = makeEditor();
    update(editor, () => {
      const empty = $createParagraphNode();
      $getRoot()
        .clear()
        .append(
          $createCalloutNode("info").append(
            $createParagraphNode().append($createTextNode("Said")),
            empty
          )
        );
      empty.select();
    });
    update(editor, () => {
      editor.dispatchCommand(INSERT_PARAGRAPH_COMMAND, undefined);
    });
    expect(rootJSON(editor).map((node) => node.type)).toEqual(["callout", "paragraph"]);
    expect(rootJSON(editor)[0].children).toHaveLength(1);
  });

  it("come apart on Backspace at the very start, keeping what they said", () => {
    const editor = makeEditor();
    update(editor, () => {
      const text = $createTextNode("Keep me");
      $getRoot()
        .clear()
        .append($createCalloutNode("note").append($createParagraphNode().append(text)));
      text.select(0, 0);
    });
    update(editor, () => {
      editor.dispatchCommand(KEY_BACKSPACE_COMMAND, null as unknown as KeyboardEvent);
    });
    const nodes = rootJSON(editor);
    expect(nodes.map((node) => node.type)).toEqual(["paragraph"]);
    editor.getEditorState().read(() => expect($getRoot().getTextContent()).toBe("Keep me"));
  });
});

describe("folding a callout", () => {
  const twoLines = () =>
    $createCalloutNode("tip").append(
      $createParagraphNode().append($createTextNode("Spoilers")),
      $createParagraphNode().append($createTextNode("The butler did it."))
    );

  it("is saved with the page, and a page from before it reads as open", () => {
    const editor = makeEditor();
    update(editor, () => {
      const callout = twoLines();
      $getRoot().clear().append(callout);
      callout.setCollapsed(true);
    });
    expect(rootJSON(editor)[0]).toMatchObject({ type: "callout", collapsed: true });

    const older = makeEditor();
    const state = editor.getEditorState().toJSON();
    delete (state.root.children[0] as { collapsed?: boolean }).collapsed;
    older.setEditorState(older.parseEditorState(state));
    older.getEditorState().read(() => {
      const callout = $getRoot().getFirstChild();
      expect($isCalloutNode(callout) && callout.getCollapsed()).toBe(false);
    });
  });

  it("is what its button does, for somebody who can edit", () => {
    const editor = makeEditor();
    const root = document.createElement("div");
    root.contentEditable = "true";
    document.body.append(root);
    editor.setRootElement(root);
    update(editor, () => {
      $getRoot().clear().append(twoLines());
    });

    const element = root.querySelector<HTMLElement>("[data-callout]");
    const toggle = element?.querySelector<HTMLButtonElement>(".callout-toggle");
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
    toggle?.click();
    editor.update(() => {}, { discrete: true });

    editor.getEditorState().read(() => {
      const callout = $getRoot().getFirstChild();
      expect($isCalloutNode(callout) && callout.getCollapsed()).toBe(true);
    });
    expect(element?.hasAttribute("data-collapsed")).toBe(true);
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    editor.setRootElement(null);
    root.remove();
  });

  it("opens when the caret lands in a line it hides", () => {
    const editor = makeEditor();
    update(editor, () => {
      const callout = twoLines();
      $getRoot().clear().append(callout);
      callout.setCollapsed(true);
      // Its first line shows, so writing there leaves it folded.
      callout.getFirstChildOrThrow().selectEnd();
    });
    editor.getEditorState().read(() => {
      const callout = $getRoot().getFirstChild();
      expect($isCalloutNode(callout) && callout.getCollapsed()).toBe(true);
    });

    update(editor, () => {
      const callout = $getRoot().getFirstChild();
      if ($isCalloutNode(callout)) callout.getLastChildOrThrow().selectEnd();
    });
    editor.update(() => {}, { discrete: true });
    editor.getEditorState().read(() => {
      const callout = $getRoot().getFirstChild();
      expect($isCalloutNode(callout) && callout.getCollapsed()).toBe(false);
    });
  });
});

describe("callouts in markdown", () => {
  it("are Obsidian's syntax, both ways, with lists inside them intact", () => {
    const editor = makeEditor();
    const source = ["> [!warning] Careful", "> Two things:", ">", "> - one", "> - two"].join("\n");
    let exported = "";
    update(editor, () => {
      $convertFromMarkdownString(source, MARKDOWN_TRANSFORMERS);
    });
    editor.getEditorState().read(() => {
      const callout = $getRoot().getFirstChild();
      expect($isCalloutNode(callout) && callout.getVariant()).toBe("warning");
      exported = $convertToMarkdownString(MARKDOWN_TRANSFORMERS);
    });
    const [callout] = rootJSON(editor);
    expect(callout.children?.map((node) => node.type)).toEqual(["paragraph", "paragraph", "list"]);
    expect(exported.split("\n")[0]).toBe("> [!warning]");
    expect(exported).toContain("> **Careful**");
    expect(exported).toContain("> - one");
  });

  it("carry Obsidian's fold marker, both ways", () => {
    const editor = makeEditor();
    let exported = "";
    update(editor, () => {
      $convertFromMarkdownString(
        ["> [!tip]- Spoilers", "> The butler did it.", "", "> [!note]+ Open", "> Seen."].join("\n"),
        MARKDOWN_TRANSFORMERS
      );
    });
    editor.getEditorState().read(() => {
      const [folded, open] = $getRoot().getChildren().filter($isCalloutNode);
      expect(folded.getCollapsed()).toBe(true);
      expect(open.getCollapsed()).toBe(false);
      exported = $convertToMarkdownString(MARKDOWN_TRANSFORMERS);
    });
    expect(exported).toContain("> [!tip]-\n");
    expect(exported).toContain("> [!note]\n");
  });

  it("leave an ordinary quote a quote", () => {
    const editor = makeEditor();
    update(editor, () => {
      $convertFromMarkdownString("> just a quote", MARKDOWN_TRANSFORMERS);
    });
    expect(rootJSON(editor).map((node) => node.type)).toEqual(["quote"]);
  });
});

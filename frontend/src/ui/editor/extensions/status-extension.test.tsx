import { buildEditorFromExtensions } from "@lexical/extension";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { RichTextExtension } from "@lexical/rich-text";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $isElementNode,
  defineExtension,
  type LexicalEditor,
} from "lexical";
import { useMemo } from "react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { documentExtension } from "@/ui/editor/document-extension";
import { markdownTransformers } from "@/ui/editor/extensions/markdown-shortcuts-extension";
import { INSERT_STATUS_COMMAND, StatusExtension } from "@/ui/editor/extensions/status-extension";
import { $createStatusNode, $isStatusNode } from "@/ui/editor/nodes/status-node";
import { Plugins } from "@/ui/editor/plugins";
import { TooltipProvider } from "@/ui/tooltip";

const transformers = markdownTransformers([]);

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(
    defineExtension({
      name: "@test/status",
      dependencies: [RichTextExtension, StatusExtension],
      onError: (error) => {
        throw error;
      },
    })
  );
}

describe("a status", () => {
  it("is saved as its word and colour, and read back", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        $getRoot()
          .clear()
          .append($createParagraphNode().append($createStatusNode("Done", "green")));
      },
      { discrete: true }
    );
    const json = editor.getEditorState().toJSON();
    const paragraph = json.root.children[0] as unknown as { children: unknown[] };
    expect(paragraph.children[0]).toEqual({
      type: "status",
      version: 1,
      text: "Done",
      color: "green",
    });
    editor.getEditorState().read(() => {
      // Its word is its text: what search and a copy both take.
      expect($getRoot().getTextContent()).toBe("Done");
    });
  });

  it("is a text directive in markdown, both ways", () => {
    const editor = makeEditor();
    let exported = "";
    editor.update(
      () => {
        $getRoot()
          .clear()
          .append(
            $createParagraphNode().append(
              $createTextNode("State: "),
              $createStatusNode("In progress", "blue")
            )
          );
      },
      { discrete: true }
    );
    editor.getEditorState().read(() => {
      exported = $convertToMarkdownString(transformers);
    });
    expect(exported).toBe('State: :status[In progress]{color="blue"}');

    const restored = makeEditor();
    restored.update(() => $convertFromMarkdownString(exported, transformers), {
      discrete: true,
    });
    restored.getEditorState().read(() => {
      const line = $getRoot().getFirstChild();
      const node = $isElementNode(line) ? line.getLastChild() : null;
      expect($isStatusNode(node) && [node.getText(), node.getColor()]).toEqual([
        "In progress",
        "blue",
      ]);
    });
  });
});

let editor!: LexicalEditor;

function Grab(): null {
  const [found] = useLexicalComposerContext();
  editor = found;
  return null;
}

function Harness() {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: true }), []);
  return (
    <LexicalExtensionComposer extension={extension} contentEditable={null}>
      <TooltipProvider>
        <Grab />
        <Plugins showToolbar={false} readOnly={false} />
      </TooltipProvider>
    </LexicalExtensionComposer>
  );
}

describe("a status on the page", () => {
  it("opens to change its colour", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    editor.update(
      () => {
        $getRoot()
          .clear()
          .append($createParagraphNode().append($createStatusNode("Blocked", "neutral")));
      },
      { discrete: true }
    );

    await userEvent.click(await screen.findByRole("button", { name: /change status/i }));
    await userEvent.click(await screen.findByRole("button", { name: /^red$/i }));

    await waitFor(() =>
      editor.getEditorState().read(() => {
        const line = $getRoot().getFirstChild();
        const node = $isElementNode(line) ? line.getFirstChild() : null;
        expect($isStatusNode(node) && node.getColor()).toBe("red");
      })
    );
  });

  it("stays open when focus moves away as it is inserted", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    editor.update(
      () => {
        const paragraph = $createParagraphNode();
        $getRoot().clear().append(paragraph);
        paragraph.select();
      },
      { discrete: true }
    );
    editor.update(() => editor.dispatchCommand(INSERT_STATUS_COMMAND, undefined), {
      discrete: true,
    });

    const field = await screen.findByRole("textbox", { name: /status text/i });
    // What the insert menu does as it closes: hand focus back to its button.
    const elsewhere = document.createElement("button");
    document.body.append(elsewhere);
    elsewhere.focus();

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(field).toBeInTheDocument();
    await userEvent.type(field, "Waiting{Enter}");
    await waitFor(() =>
      editor.getEditorState().read(() => {
        const line = $getRoot().getFirstChild();
        const node = $isElementNode(line) ? line.getFirstChild() : null;
        expect($isStatusNode(node) && node.getText()).toBe("Waiting");
      })
    );
    elsewhere.remove();
  });

  it("takes a colour picked on a new status, before or after its word", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    editor.update(
      () => {
        const paragraph = $createParagraphNode();
        $getRoot().clear().append(paragraph);
        paragraph.select();
      },
      { discrete: true }
    );
    editor.update(() => editor.dispatchCommand(INSERT_STATUS_COMMAND, undefined), {
      discrete: true,
    });

    await userEvent.click(await screen.findByRole("button", { name: /^green$/i }));
    const field = await screen.findByRole("textbox", { name: /status text/i });
    await userEvent.type(field, "Done");
    await userEvent.click(screen.getByRole("button", { name: /^blue$/i }));
    await userEvent.type(field, "{Enter}");

    await waitFor(() =>
      editor.getEditorState().read(() => {
        const line = $getRoot().getFirstChild();
        const node = $isElementNode(line) ? line.getFirstChild() : null;
        expect($isStatusNode(node) && [node.getText(), node.getColor()]).toEqual(["Done", "blue"]);
      })
    );
  });
});

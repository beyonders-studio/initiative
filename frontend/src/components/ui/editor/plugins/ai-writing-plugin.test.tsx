import { LinkNode } from "@lexical/link";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $isTextNode,
  type LexicalEditor,
} from "lexical";
import { useEffect, useState } from "react";
import { describe, expect, it } from "vitest";

import { AIWriteAction, type AIWriteRequest } from "@/api/generated/initiativeAPI.schemas";

import { AI_WRITE_COMMAND, AIWritingPlugin } from "./ai-writing-plugin";

let editor: LexicalEditor | null = null;
let asked: AIWriteRequest[] = [];

function CaptureEditor() {
  const [current] = useLexicalComposerContext();
  useEffect(() => {
    editor = current;
  }, [current]);
  return null;
}

/** One paragraph, and a provider that answers ``list``. */
function Harness() {
  const [anchor, setAnchor] = useState<HTMLDivElement | null>(null);
  return (
    <LexicalComposer
      initialConfig={{
        namespace: "ai-writing-test",
        nodes: [LinkNode],
        onError: (error) => {
          throw error;
        },
        editorState: () => {
          $getRoot().append($createParagraphNode().append($createTextNode("The rota is sorted.")));
        },
      }}
    >
      <div ref={setAnchor}>
        <RichTextPlugin
          contentEditable={<ContentEditable />}
          ErrorBoundary={LexicalErrorBoundary}
        />
      </div>
      <CaptureEditor />
      <AIWritingPlugin
        anchorElem={anchor}
        write={(body) => {
          asked.push(body);
          return async () => '{"text":"list"}\n';
        }}
      />
    </LexicalComposer>
  );
}

const text = () => editor?.getEditorState().read(() => $getRoot().getTextContent());

/** Select "rota", ask to shorten it, and wait for the answer. */
const askAboutRota = async () => {
  asked = [];
  render(<Harness />);
  await waitFor(() => expect(editor).not.toBeNull());
  // jsdom keeps no selection between updates, so it is made where it is asked.
  act(() => {
    editor?.update(() => {
      const node = $getRoot().getFirstDescendant();
      if ($isTextNode(node)) node.select(4, 8);
      editor?.dispatchCommand(AI_WRITE_COMMAND, { action: AIWriteAction.shorten });
    });
  });
  await screen.findByText("list");
};

describe("AIWritingPlugin", () => {
  it("sends the selection and puts the answer in its place", async () => {
    await askAboutRota();
    expect(asked).toEqual([
      expect.objectContaining({ action: "shorten", text: "rota", before: "", after: "" }),
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Replace" }));

    await waitFor(() => expect(text()).toBe("The list is sorted."));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("inserts the answer below, or drops it", async () => {
    await askAboutRota();
    fireEvent.click(screen.getByRole("button", { name: "Insert below" }));
    await waitFor(() => expect(text()).toBe("The rota is sorted.\n\nlist"));

    await askAboutRota();
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(text()).toBe("The rota is sorted.");
  });

  it("does not replace text that changed while it was written", async () => {
    await askAboutRota();
    act(() => {
      editor?.update(() => {
        const node = $getRoot().getFirstDescendant();
        if ($isTextNode(node)) node.setTextContent("The plan is sorted.");
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Replace" }));

    expect(await screen.findByText(/The text changed while writing/)).toBeInTheDocument();
    expect(text()).toBe("The plan is sorted.");
    // Below it still goes.
    fireEvent.click(screen.getByRole("button", { name: "Insert below" }));
    await waitFor(() => expect(text()).toBe("The plan is sorted.\n\nlist"));
  });
});

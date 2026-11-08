import { $createLinkNode, LinkNode } from "@lexical/link";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { $createParagraphNode, $createTextNode, $getRoot, type LexicalEditor } from "lexical";
import { useEffect, useState } from "react";
import { describe, expect, it } from "vitest";

import { FloatingLinkEditorPlugin } from "./floating-link-editor-plugin";

let editorHandle: LexicalEditor | null = null;

function CaptureEditor() {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    editorHandle = editor;
  }, [editor]);
  return null;
}

/** An editor whose one paragraph is a link just inserted with the default URL. */
function Harness() {
  const [anchor, setAnchor] = useState<HTMLDivElement | null>(null);
  const [isLinkEditMode, setIsLinkEditMode] = useState(true);
  return (
    <LexicalComposer
      initialConfig={{
        namespace: "link-editor-test",
        nodes: [LinkNode],
        onError: (error) => {
          throw error;
        },
        editorState: () => {
          const link = $createLinkNode("https://");
          link.append($createTextNode("Hi"));
          $getRoot().append($createParagraphNode().append(link));
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
      <FloatingLinkEditorPlugin
        anchorElem={anchor}
        isLinkEditMode={isLinkEditMode}
        setIsLinkEditMode={setIsLinkEditMode}
      />
    </LexicalComposer>
  );
}

const openLinkField = async (): Promise<HTMLInputElement> => {
  render(<Harness />);
  await waitFor(() => expect(editorHandle).not.toBeNull());
  act(() => {
    editorHandle?.update(() => {
      $getRoot().getFirstDescendant()?.selectStart();
    });
  });
  // jsdom has no native selection for the plugin to follow, so it shows the
  // link rather than the field; its edit button opens the field on the link's URL.
  const edit = await waitFor(() => {
    const button = document.querySelector<HTMLButtonElement>("button");
    if (!button) throw new Error("the link editor is not showing");
    return button;
  });
  fireEvent.click(edit);
  return waitFor(() => {
    const input = document.querySelector<HTMLInputElement>("input");
    if (input?.value !== "https://") throw new Error("the link field is not open");
    return input;
  });
};

const paste = (input: HTMLInputElement, text: string) =>
  fireEvent.paste(input, { clipboardData: { getData: () => text } });

describe("the floating link field", () => {
  it("replaces its https:// default with a pasted URL", async () => {
    const input = await openLinkField();
    input.setSelectionRange(input.value.length, input.value.length);

    paste(input, "https://example.com/page");

    expect(input.value).toBe("https://example.com/page");
  });

  it("replaces the default wherever the caret was", async () => {
    const input = await openLinkField();
    input.setSelectionRange(0, 0);

    paste(input, "http://example.com");

    expect(input.value).toBe("http://example.com");
  });

  it("keeps https:// in front of a pasted bare host", async () => {
    const input = await openLinkField();

    paste(input, "example.com/page");

    expect(input.value).toBe("https://example.com/page");
  });

  // A keyboard's clipboard suggestion inserts text without a paste event.
  it("drops the default when a URL is inserted after it without a paste", async () => {
    const input = await openLinkField();

    fireEvent.change(input, { target: { value: "https://https://example.com" } });

    expect(input.value).toBe("https://example.com");
  });

  it("leaves a paste into a URL already typed to the browser", async () => {
    const input = await openLinkField();
    fireEvent.change(input, { target: { value: "https://example.com/" } });

    const event = paste(input, "page");

    expect(event).toBe(true);
    expect(input.value).toBe("https://example.com/");
  });
});

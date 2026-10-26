import { $createLinkNode, $isLinkNode, LinkNode } from "@lexical/link";
import { $createListItemNode, $createListNode, ListItemNode, ListNode } from "@lexical/list";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import {
  $createHorizontalRuleNode,
  HorizontalRuleNode,
} from "@lexical/react/LexicalHorizontalRuleNode";
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
import { afterEach, describe, expect, it } from "vitest";

import { AIWriteAction, type AIWriteRequest } from "@/api/generated/initiativeAPI.schemas";

import { AI_WRITE_COMMAND, AIWritingPlugin } from "./ai-writing-plugin";

let editor: LexicalEditor | null = null;
let asked: AIWriteRequest[] = [];
/** The document a test starts from: one paragraph unless it says otherwise. */
const ONE_PARAGRAPH = () => {
  $getRoot().append($createParagraphNode().append($createTextNode("The rota is sorted.")));
};
let content = ONE_PARAGRAPH;

function CaptureEditor() {
  const [current] = useLexicalComposerContext();
  useEffect(() => {
    editor = current;
  }, [current]);
  return null;
}

/** The document, and a provider that answers ``list``. */
function Harness() {
  const [anchor, setAnchor] = useState<HTMLDivElement | null>(null);
  return (
    <LexicalComposer
      initialConfig={{
        namespace: "ai-writing-test",
        nodes: [LinkNode, HorizontalRuleNode, ListNode, ListItemNode],
        onError: (error) => {
          throw error;
        },
        editorState: () => content(),
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

/** Make the selection ``select`` makes, and ask to shorten it. */
const ask = async (select: () => void) => {
  asked = [];
  render(<Harness />);
  await waitFor(() => expect(editor).not.toBeNull());
  // jsdom keeps no selection between updates, so it is made where it is asked.
  act(() => {
    editor?.update(() => {
      select();
      editor?.dispatchCommand(AI_WRITE_COMMAND, { action: AIWriteAction.shorten });
    });
  });
};

/** Select "rota", ask to shorten it, and wait for the answer. */
const askAboutRota = async () => {
  await ask(() => {
    const node = $getRoot().getFirstDescendant();
    if ($isTextNode(node)) node.select(4, 8);
  });
  await screen.findByText("list");
};

afterEach(() => {
  content = ONE_PARAGRAPH;
});

describe("AIWritingPlugin", () => {
  it("sends the selection, with the sentence it sits in, and puts the answer in its place", async () => {
    await askAboutRota();
    expect(asked).toEqual([
      expect.objectContaining({
        action: "shorten",
        text: "rota",
        before: "The ",
        after: " is sorted.",
      }),
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

  it("puts an answer below where a selection drawn upwards ends", async () => {
    content = () => {
      $getRoot().append(
        $createParagraphNode().append($createTextNode("First.")),
        $createParagraphNode().append($createTextNode("Second.")),
        $createParagraphNode().append($createTextNode("Third."))
      );
    };
    await ask(() => {
      const [first, second] = $getRoot().getAllTextNodes();
      const selection = second.select(7, 7);
      selection.focus.set(first.getKey(), 0, "text");
    });
    await screen.findByText("list");

    expect(asked[0]).toMatchObject({ text: "First.\n\nSecond.", after: "\n\nThird." });
    fireEvent.click(screen.getByRole("button", { name: "Insert below" }));
    await waitFor(() => expect(text()).toBe("First.\n\nSecond.\n\nlist\n\nThird."));
  });

  it("does not replace a link that changed while it was written", async () => {
    content = () => {
      const link = $createLinkNode("https://example.com/rota").append($createTextNode("rota"));
      $getRoot().append(
        $createParagraphNode().append($createTextNode("The "), link, $createTextNode(" is up."))
      );
    };
    await ask(() => {
      const [, rota] = $getRoot().getAllTextNodes();
      rota.select(0, 4);
    });
    await screen.findByText("list");
    expect(asked[0].text).toBe("[rota](https://example.com/rota)");

    act(() => {
      editor?.update(() => {
        const [, rota] = $getRoot().getAllTextNodes();
        const link = rota.getParent();
        if ($isLinkNode(link)) link.setURL("https://example.com/new-rota");
      });
    });
    fireEvent.click(screen.getByRole("button", { name: "Replace" }));

    expect(await screen.findByText(/The text changed while writing/)).toBeInTheDocument();
  });

  it("asks nothing about a selection it could not put back whole", async () => {
    content = () => {
      $getRoot().append(
        $createParagraphNode().append($createTextNode("Above.")),
        $createHorizontalRuleNode(),
        $createParagraphNode().append($createTextNode("Below."))
      );
    };
    await ask(() => {
      const [above, below] = $getRoot().getAllTextNodes();
      const selection = above.select(0, 0);
      selection.focus.set(below.getKey(), 6, "text");
    });

    expect(await screen.findByText(/can't put this selection back whole/)).toBeInTheDocument();
    expect(asked).toEqual([]);
  });

  it("asks nothing about list items it would run together", async () => {
    content = () => {
      $getRoot().append(
        $createListNode("bullet").append(
          $createListItemNode().append($createTextNode("First.")),
          $createListItemNode().append($createTextNode("Second."))
        )
      );
    };
    await ask(() => {
      const [first, second] = $getRoot().getAllTextNodes();
      const selection = first.select(0, 0);
      selection.focus.set(second.getKey(), 7, "text");
    });

    expect(await screen.findByText(/can't put this selection back whole/)).toBeInTheDocument();
    expect(asked).toEqual([]);
  });

  it("continues from the cursor, and writes there", async () => {
    asked = [];
    render(<Harness />);
    await waitFor(() => expect(editor).not.toBeNull());
    act(() => {
      editor?.update(() => {
        const node = $getRoot().getFirstDescendant();
        if ($isTextNode(node)) node.select(8, 8);
        editor?.dispatchCommand(AI_WRITE_COMMAND, { action: AIWriteAction.continue });
      });
    });
    await screen.findByText("list");

    expect(asked[0]).toMatchObject({ text: "", before: "The rota", after: " is sorted." });
    fireEvent.click(screen.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(text()).toBe("The rotalist is sorted."));
  });
});

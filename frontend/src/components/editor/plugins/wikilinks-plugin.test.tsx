/**
 * `[[ ]]` offers to make what it could not find. The plugin opens the dialog
 * itself, so every editor that has it — a document, a wiki page, a post — makes
 * the thing and links it, rather than only the hosts that remembered to.
 */
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $nodesOfType,
  type LexicalEditor,
} from "lexical";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { EntityMentionNode } from "@/components/editor/nodes/entity-mention-node";
import { ReferenceEmbedNode } from "@/components/editor/nodes/reference-embed-node";

import { WikilinksPlugin } from "./wikilinks-plugin";

// Nothing in the initiative matches, so the only row is the one that makes it.
vi.mock("@/hooks/useSearch", () => ({
  useCommunityPickerSuggestions: () => ({ items: [], isFetching: false }),
}));
vi.mock("@/hooks/useInitiatives", () => ({
  useInitiative: () => ({ data: undefined }),
}));
vi.mock("@/components/references/CreateReferencedThingDialog", () => ({
  CreateReferencedThingDialog: ({
    name,
    onCreated,
  }: {
    name: string;
    onCreated: (made: { entityType: string; entityId: number; name: string }) => void;
  }) => (
    <button type="button" onClick={() => onCreated({ entityType: "project", entityId: 9, name })}>
      make-it
    </button>
  ),
}));

let editorRef: LexicalEditor | null = null;
const Capture = () => {
  const [editor] = useLexicalComposerContext();
  useEffect(() => {
    editorRef = editor;
  }, [editor]);
  return null;
};

const setup = () =>
  renderWithProviders(
    <LexicalComposer
      initialConfig={{
        namespace: "wikilinks-test",
        nodes: [EntityMentionNode, ReferenceEmbedNode],
        onError: (error) => {
          throw error;
        },
      }}
    >
      <RichTextPlugin
        contentEditable={<ContentEditable aria-label="body" />}
        ErrorBoundary={LexicalErrorBoundary}
      />
      <WikilinksPlugin initiativeId={1} />
      <Capture />
    </LexicalComposer>
  );

describe("making what [[ ]] could not find", () => {
  it("makes it and puts the link where the name was typed", async () => {
    const user = userEvent.setup();
    setup();
    screen.getByLabelText("body").focus();

    await act(async () => {
      editorRef?.update(() => {
        const text = $createTextNode("[[Budget");
        $getRoot().clear().append($createParagraphNode().append(text));
        text.select();
      });
    });

    await user.click(await screen.findByText(/^Create .Budget.$/));
    await user.click(await screen.findByRole("button", { name: "make-it" }));

    await waitFor(() => {
      const links = editorRef?.getEditorState().read(() => $nodesOfType(EntityMentionNode)) ?? [];
      expect(links).toHaveLength(1);
    });
    expect(screen.queryByRole("button", { name: "make-it" })).toBeNull();
  });
});

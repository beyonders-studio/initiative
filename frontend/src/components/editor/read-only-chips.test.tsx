import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { waitFor } from "@testing-library/react";
import { $createParagraphNode, $getRoot, type LexicalEditor } from "lexical";
import { HttpResponse } from "msw";
import { useMemo } from "react";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { documentExtension } from "@/components/editor/document-extension";
import { $createSmartChipNode } from "@/components/editor/nodes/smart-chip-node";
import { Plugins } from "@/components/editor/plugins";
import { TooltipProvider } from "@/ui/tooltip";

/**
 * A chip reads its live state where it is only being READ.
 *
 * Chips do not fetch for themselves — the page collects their references and
 * asks once. That collecting used to be gated on `supportsEntityMentions`,
 * which says whether this editor lets you *insert* a reference: a different
 * question, and one a read-only view answers no to. So the post feed, which
 * renders its notices through a read-only editor, reported nothing, and every
 * chip in it said "no longer available to you" instead of showing a reading.
 */

let editor!: LexicalEditor;
let asked: string[] = [];

function Grab(): null {
  const [found] = useLexicalComposerContext();
  editor = found;
  return null;
}

function ReadOnlyHarness() {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: false }), []);
  return (
    <LexicalExtensionComposer extension={extension} contentEditable={null}>
      <TooltipProvider>
        <Grab />
        {/* Exactly how a post's body is rendered on the board: read-only,
              no toolbar, and no mention-inserting. */}
        <Plugins showToolbar={false} readOnly initiativeId={7} />
      </TooltipProvider>
    </LexicalExtensionComposer>
  );
}

describe("a read-only document's smart chips", () => {
  it("asks for the state of what it refers to", async () => {
    asked = [];
    server.use(
      communityHttp.post("/smart-chips", async ({ request }) => {
        asked = ((await request.json()) as { refs: string[] }).refs;
        return HttpResponse.json({ items: [] });
      })
    );

    renderPage(ReadOnlyHarness);
    await waitFor(() => expect(editor).toBeTruthy());

    editor.update(
      () => {
        const paragraph = $createParagraphNode();
        paragraph.append($createSmartChipNode("task:status", 12, "In Progress"));
        $getRoot().clear().append(paragraph);
      },
      { discrete: true }
    );

    await waitFor(() => expect(asked).toContain("task:12:status"), { timeout: 4000 });
  });
});

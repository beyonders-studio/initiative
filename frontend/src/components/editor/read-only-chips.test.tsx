import { waitFor } from "@testing-library/react";
import { $createParagraphNode, $getRoot, type LexicalEditor } from "lexical";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/editor/editor";
import { $createSmartChipNode } from "@/components/editor/nodes/smart-chip-node";

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

let asked: string[] = [];

type Editable = HTMLElement & { __lexicalEditor: LexicalEditor };

/** The editor the page drew. */
const drawnEditor = () =>
  waitFor(() => {
    const root = document.querySelector<Editable>('[data-lexical-editor="true"]');
    expect(root).not.toBeNull();
    return (root as Editable).__lexicalEditor;
  });

/** Exactly how a post's body is rendered on the board: read-only, no toolbar,
 *  and no mention-inserting. */
function ReadOnlyHarness() {
  return <Editor showToolbar={false} readOnly initiativeId={7} />;
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
    const editor = await drawnEditor();

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

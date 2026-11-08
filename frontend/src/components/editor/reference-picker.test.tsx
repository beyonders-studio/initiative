import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { screen, waitFor } from "@testing-library/react";
import { $createParagraphNode, $createTextNode, $getRoot, type LexicalEditor } from "lexical";
import { HttpResponse } from "msw";
import { useMemo } from "react";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { documentExtension } from "@/components/editor/document-extension";
import { Plugins } from "@/components/editor/plugins";
import { TooltipProvider } from "@/ui/tooltip";

/**
 * `#` and the smart-chip picker, in a real document.
 *
 * Both are scoped to the document's own initiative, so a community full of matching
 * work can still answer nothing — and when it did, neither surface rendered
 * anything at all. A reader saw an unchanged caret and an empty box and
 * reasonably concluded the feature was broken. What is asserted here is that an
 * empty answer LOOKS like an answer.
 */

const suggestion = {
  entity_type: "task",
  entity_id: 12,
  title: "Ship the release",
  initiative_id: 7,
  tool: "project",
  tool_id: 3,
};

let editor!: LexicalEditor;

function Grab(): null {
  const [found] = useLexicalComposerContext();
  editor = found;
  return null;
}

function Harness({ subject }: { subject?: string }) {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: true }), []);
  return (
    <LexicalExtensionComposer extension={extension} contentEditable={null}>
      <TooltipProvider>
        <Grab />
        <Plugins showToolbar={false} initiativeId={7} subject={subject} supportsEntityMentions />
      </TooltipProvider>
    </LexicalExtensionComposer>
  );
}

/** Type into the document the way a person would, via the editor's own API —
 *  `userEvent` cannot drive a Lexical contenteditable under jsdom. */
function type(text: string) {
  editor.update(
    () => {
      const paragraph = $createParagraphNode();
      const node = $createTextNode(text);
      paragraph.append(node);
      $getRoot().clear().append(paragraph);
      node.select(text.length, text.length);
    },
    { discrete: true }
  );
}

describe("probe: # in a document", () => {
  it("opens the picker on a match", async () => {
    server.use(communityHttp.get("/search/suggest", () => HttpResponse.json([suggestion])));

    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    type("#ship");

    await waitFor(() => expect(screen.getByText("Ship the release")).toBeInTheDocument(), {
      timeout: 4000,
    });
  });

  it("says so when nothing in the initiative matches", async () => {
    server.use(communityHttp.get("/search/suggest", () => HttpResponse.json([])));

    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    type("#zzz");

    // The answer, and why the answer might be empty when the community is not.
    await waitFor(
      () => expect(screen.getByText(/Nothing in this initiative/)).toBeInTheDocument(),
      {
        timeout: 4000,
      }
    );
    expect(screen.getByText(/Only this document.s initiative/)).toBeInTheDocument();
  });

  it("does not answer for words it has not searched for yet", async () => {
    server.use(communityHttp.get("/search/suggest", () => HttpResponse.json([])));

    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());
    type("#a");
    await waitFor(() => expect(screen.getByText(/matches “a”/)).toBeInTheDocument(), {
      timeout: 4000,
    });

    // The answer for "a" is still on screen while "zzz" waits out the debounce.
    type("#zzz");
    await waitFor(() => expect(screen.queryByText(/matches “a”/)).not.toBeInTheDocument());
    expect(screen.queryByText(/matches “zzz”/)).not.toBeInTheDocument();
    expect(screen.getByText("Searching…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/matches “zzz”/)).toBeInTheDocument(), {
      timeout: 4000,
    });
  });
});

describe("a page does not point at itself", () => {
  /** The page the link would open is the page the words are on. The server is
   *  what leaves it out — asked before `limit`, so a picker wanting five rows
   *  is offered five — and this is the half that asks. */
  it("names what is being written in, so it is not offered", async () => {
    const asked: (string | null)[] = [];
    server.use(
      communityHttp.get("/search/suggest", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("subject"));
        return HttpResponse.json([]);
      })
    );

    renderPage(() => <Harness subject="file:42" />);
    await waitFor(() => expect(editor).toBeTruthy());
    type("#ship");

    await waitFor(() => expect(asked).toContain("file:42"), { timeout: 4000 });
  });

  it("asks for everything when there is nothing to be written in yet", async () => {
    const asked: (string | null)[] = [];
    server.use(
      communityHttp.get("/search/suggest", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("subject"));
        return HttpResponse.json([suggestion]);
      })
    );

    renderPage(() => <Harness />);
    await waitFor(() => expect(editor).toBeTruthy());
    type("#ship");

    await waitFor(() => expect(screen.getByText("Ship the release")).toBeInTheDocument(), {
      timeout: 4000,
    });
    expect(asked.every((value) => value === null)).toBe(true);
  });
});

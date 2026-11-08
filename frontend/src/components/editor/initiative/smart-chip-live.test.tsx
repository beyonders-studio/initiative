import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SerializedEditorState } from "lexical";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/editor/initiative/editor";

/**
 * A chip is only a chip if it reads.
 *
 * It renders as a Lexical decorator, which the composer portals in itself. A
 * chip that never hears its answer falls back to the words stored beside it,
 * and the whole feature reads as a static label — so this renders the real
 * page rather than asking the pieces.
 */

/** A document holding one chip. */
const documentWithAChip = (
  chipKind = "counter:value",
  entityId = 4,
  text = "Launch signups"
): SerializedEditorState =>
  ({
    root: {
      type: "root",
      version: 1,
      format: "",
      indent: 0,
      direction: null,
      children: [
        {
          type: "paragraph",
          version: 1,
          format: "",
          indent: 0,
          direction: null,
          children: [
            {
              type: "smart-chip",
              version: 1,
              chipKind,
              entityId,
              // What it was called when it was inserted.
              text,
            },
          ],
        },
      ],
    },
  }) as unknown as SerializedEditorState;

function DocumentUnderTest({ document = documentWithAChip() }) {
  return (
    <Editor
      editorSerializedState={document}
      readOnly
      showToolbar={false}
      initiativeId={7}
      supportsEntityMentions
    />
  );
}

describe("a smart chip in a real document", () => {
  it("shows what the thing is doing now, not the words stored beside it", async () => {
    server.use(
      communityHttp.post("/smart-chips/", async ({ request }) => {
        const { refs } = (await request.json()) as { refs: string[] };
        // One reference per chip: the answer names its own thing.
        expect(refs).toEqual(["counter:4:value"]);
        return HttpResponse.json({
          items: [
            {
              ref: "counter:4:value",
              entity_type: "counter",
              aspect: "value",
              text: "42 / 100",
              title: "Launch signups",
              tone: "neutral",
              color: null,
              date: null,
              number: "42",
            },
          ],
        });
      })
    );

    renderPage(DocumentUnderTest);

    await waitFor(() => expect(screen.getByText("42 / 100")).toBeInTheDocument());
    // The stored label is the fallback, and a chip that read is past it.
    expect(screen.queryByText("Launch signups")).not.toBeInTheDocument();
  });

  it("falls back to the stored label when the thing cannot be read", async () => {
    server.use(communityHttp.post("/smart-chips/", () => HttpResponse.json({ items: [] })));

    renderPage(DocumentUnderTest);

    await waitFor(() => expect(screen.getByText("Launch signups")).toBeInTheDocument());
  });

  /** A task's box as the server reads it: done once a save says so. */
  const serveTheBox = (task: { done: boolean }) =>
    communityHttp.post("/smart-chips/", () =>
      HttpResponse.json({
        items: [
          {
            ref: "task:12:checklist",
            entity_type: "task",
            aspect: "checklist",
            text: task.done ? "done" : "",
            title: "Ship it",
            tone: task.done ? "good" : "neutral",
            color: null,
            date: null,
            number: null,
            writable: true,
          },
        ],
      })
    );

  const clickTheBox = async () => {
    renderPage(() => (
      <DocumentUnderTest document={documentWithAChip("task:checklist", 12, "Ship it")} />
    ));
    const box = await screen.findByRole("checkbox");
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.click(box);
    return box;
  };

  it("ticks a task the moment its box is clicked, and asks the server once", async () => {
    const task = { done: false };
    let sent: unknown;
    let answer!: () => void;
    const answered = new Promise<void>((resolve) => {
      answer = resolve;
    });
    server.use(
      serveTheBox(task),
      communityHttp.patch("/tasks/12", async ({ request }) => {
        sent = await request.json();
        await answered;
        task.done = true;
        return HttpResponse.json(buildTask({ id: 12 }));
      })
    );

    const box = await clickTheBox();

    // Ticked before the server has answered, and the project's columns were
    // never read: the server picks the done column from the category.
    await waitFor(() => expect(sent).toMatchObject({ status_category: "done" }));
    expect(box).toBeChecked();

    answer();
    await waitFor(() => expect(box).toBeEnabled());
    expect(box).toBeChecked();
  });

  it("puts the box back when the server refuses the change", async () => {
    server.use(
      serveTheBox({ done: false }),
      communityHttp.patch("/tasks/12", () =>
        HttpResponse.json({ detail: "TASK_STATUS_NOT_FOUND_FOR_PROJECT" }, { status: 400 })
      )
    );

    const box = await clickTheBox();

    await waitFor(() => expect(box).toBeEnabled());
    expect(box).not.toBeChecked();
  });
});

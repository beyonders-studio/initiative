import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SerializedEditorState } from "lexical";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildShareStanding, buildTask, buildTaskListResponse } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/ui/editor/editor";
import { EMPTY_TASK_FILTERS } from "@/lib/filters/taskFilters";

const paragraph = (text: string) => ({
  type: "paragraph",
  version: 1,
  direction: null,
  format: "",
  indent: 0,
  textFormat: 0,
  textStyle: "",
  children: [{ type: "text", version: 1, detail: 0, format: 0, mode: "normal", style: "", text }],
});

const embed = (entityId: number, text: string, collapsed = false) => ({
  type: "reference-embed",
  version: 1,
  entityType: "file",
  entityId,
  text,
  collapsed,
});

const page = (...children: object[]) => ({
  root: { type: "root", version: 1, direction: null, format: "", indent: 0, children },
});

// Two pages embedding each other: 1 embeds 2, and 2 embeds 1 back.
const OUTER = page(paragraph("The outer page."), embed(2, "Inner"));
const INNER = page(paragraph("Here be dragons."), embed(1, "Outer"));

const BODIES: Record<string, { title: string; body: object }> = {
  "file:1": { title: "Outer", body: OUTER },
  "file:2": { title: "Inner", body: INNER },
};

const serveBodies = () =>
  server.use(
    communityHttp.post("/smart-chips/embeds", async ({ request }) => {
      const { refs } = (await request.json()) as { refs: string[] };
      return HttpResponse.json({
        items: refs.map((ref) => ({
          ref,
          entity_type: "file",
          title: BODIES[ref].title,
          description: null,
          body: BODIES[ref].body,
        })),
      });
    })
  );

describe("an embedded page", () => {
  it("folds to its name, and saves that with the page", async () => {
    serveBodies();
    const saved: SerializedEditorState[] = [];
    const folded = page(paragraph("The outer page."), embed(2, "Inner", true));

    renderPage(() => (
      <Editor
        editorSerializedState={folded as unknown as SerializedEditorState}
        onSerializedChange={(state) => saved.push(state)}
      />
    ));

    const expand = await screen.findByRole("button", { name: "Expand" }, { timeout: 4000 });
    expect(screen.queryByText("Here be dragons.")).not.toBeInTheDocument();

    await userEvent.click(expand);
    expect(await screen.findByText("Here be dragons.", {}, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => {
      const last = saved.at(-1)?.root.children[1] as { collapsed?: boolean } | undefined;
      expect(last?.collapsed).toBe(false);
    });
  });

  it("shows what the page says, and stops one level down", async () => {
    serveBodies();

    renderPage(() => (
      <Editor
        editorSerializedState={OUTER as unknown as SerializedEditorState}
        readOnly
        showToolbar={false}
      />
    ));

    expect(await screen.findByText("Here be dragons.", {}, { timeout: 4000 })).toBeInTheDocument();
    // The inner page's embed of the outer one is a name, not the outer page again.
    await waitFor(() => expect(screen.getByRole("button", { name: "Outer" })).toBeInTheDocument());
    expect(screen.getAllByText("The outer page.")).toHaveLength(1);
  });

  it("offers to ask for one the reader knows is there and cannot open", async () => {
    server.use(
      communityHttp.post("/smart-chips/embeds", () => HttpResponse.json({ items: [] })),
      communityHttp.get("/share-requests/standing", () =>
        HttpResponse.json(buildShareStanding({ resource_id: 5 }))
      )
    );

    renderPage(() => (
      <Editor
        editorSerializedState={page(embed(5, "Budget")) as unknown as SerializedEditorState}
      />
    ));

    expect(
      await screen.findByText("You can't see this", {}, { timeout: 4000 })
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request access" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

const taskEmbed = (display: object, query: object) => ({
  type: "reference-embed",
  version: 2,
  entityType: "task",
  entityId: 0,
  text: "Open launch tasks",
  collapsed: false,
  display,
  query,
});

const LAUNCH = {
  initiative_id: 3,
  project_id: null,
  filters: { ...EMPTY_TASK_FILTERS, assignees: ["me"], status_categories: ["todo"] },
  sort: [],
};

describe("an embed of the tasks a filter matches", () => {
  it("asks the task list as the reader, inside the page's initiative", async () => {
    let asked: unknown;
    server.use(
      communityHttp.get("/tasks/", ({ request }) => {
        asked = JSON.parse(new URL(request.url).searchParams.get("conditions") ?? "[]");
        return HttpResponse.json(
          buildTaskListResponse([
            buildTask({ title: "Book the venue" }),
            buildTask({ title: "Print the flyers" }),
          ])
        );
      })
    );

    renderPage(() => (
      <Editor
        editorSerializedState={
          page(taskEmbed({ mode: "list" }, LAUNCH)) as unknown as SerializedEditorState
        }
        readOnly
        showToolbar={false}
      />
    ));

    expect(await screen.findByText("Book the venue", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText("Print the flyers")).toBeInTheDocument();
    expect(screen.getByText("Open launch tasks")).toBeInTheDocument();
    // `me` goes to the server as `me`: each reader sees their own work.
    expect(asked).toEqual(
      expect.arrayContaining([
        { field: "initiative_ids", op: "in_", value: [3] },
        { field: "assignee_ids", op: "in_", value: ["me"] },
      ])
    );
  });

  it("counts them", async () => {
    server.use(
      communityHttp.get("/tasks/", () =>
        HttpResponse.json({ ...buildTaskListResponse([buildTask()]), total_count: 12 })
      )
    );

    renderPage(() => (
      <Editor
        editorSerializedState={
          page(taskEmbed({ mode: "count" }, LAUNCH)) as unknown as SerializedEditorState
        }
        readOnly
        showToolbar={false}
      />
    ));

    expect(await screen.findByText("12", {}, { timeout: 4000 })).toBeInTheDocument();
  });

  it("says it could not load them, rather than that none match", async () => {
    server.use(communityHttp.get("/tasks/", () => HttpResponse.json({}, { status: 500 })));

    renderPage(() => (
      <Editor
        editorSerializedState={
          page(taskEmbed({ mode: "count" }, LAUNCH)) as unknown as SerializedEditorState
        }
        readOnly
        showToolbar={false}
      />
    ));

    expect(
      await screen.findByText("These tasks couldn't be loaded.", {}, { timeout: 6000 })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

/**
 * How a project's tasks are shown, and what a link to them means.
 *
 * A project draws its tasks in its layouts (a table, a board, a Gantt); what
 * one person narrows the list to and how they sort it are theirs, kept per
 * layout in their view of the project. These cover choosing a layout (which
 * writes it to the URL, so it is linkable), a person's own filters and sort,
 * and a layout's columns.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildTag,
  buildTagSummary,
  buildTask,
  buildTaskListResponse,
  buildToolLayoutSet,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { TaskStatusRead, ToolLayoutSetRead } from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { toast } from "@/lib/mascotToast";
import { fireTaskCompletionFeedback } from "@/lib/taskCompletionFeedback";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/taskCompletionFeedback", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/taskCompletionFeedback")>()),
  fireTaskCompletionFeedback: vi.fn(),
}));

type Condition = { field?: string; op?: string; value?: unknown; logic?: string };

/** The `conditions` of the most recent tasks request. */
let lastConditions: Condition[] = [];

const captureTaskRequests = () => {
  lastConditions = [];
  server.use(
    communityHttp.get("/tasks/", ({ request }) => {
      const raw = new URL(request.url).searchParams.get("conditions");
      if (raw) lastConditions = JSON.parse(raw) as Condition[];
      return HttpResponse.json(buildTaskListResponse([]));
    })
  );
};

/** The section inside the app's scroller, which its table measures against. */
const section = ({
  routerSearch = {},
  taskStatuses = buildDefaultTaskStatuses(1),
}: {
  routerSearch?: Record<string, unknown>;
  taskStatuses?: TaskStatusRead[];
} = {}) =>
  renderPage(
    () => (
      <main data-app-scroll="">
        <ProjectTasksSection
          projectId={1}
          initiativeId={1}
          taskStatuses={taskStatuses}
          canEditTaskDetails
          projectIsArchived={false}
          taskHref={(taskId) => `/tasks/${taskId}`}
        />
      </main>
    ),
    { routerSearch }
  );

const fieldsUsed = () => lastConditions.map((entry) => entry.field ?? `group:${entry.logic}`);

/** The community's tags, which the default handler leaves empty. */
const withTags = (ids: number[]) => {
  server.use(
    communityHttp.get("/tags/", () =>
      HttpResponse.json(ids.map((id) => buildTag({ id, name: `Tag ${id}` })))
    )
  );
};

/** A project's layouts, but for `overrides`. */
const withLayouts = (overrides: Parameters<typeof buildToolLayoutSet>[0]) => {
  server.use(
    communityHttp.get("/layouts/", () =>
      HttpResponse.json<ToolLayoutSetRead>(buildToolLayoutSet(overrides))
    )
  );
};

/** Seed this person's view of project 1. */
/** This person's view of project 1, in community 1: the layout they were
 *  last in, and their filters and sort for each layout. */
const rememberView = ({
  layout,
  filters = {},
  sorting = {},
}: {
  layout: string;
  filters?: Record<string, unknown>;
  sorting?: Record<string, unknown>;
}) => {
  const kinds = [...new Set([...Object.keys(filters), ...Object.keys(sorting)])];
  const parts = Object.fromEntries(
    kinds.map((kind) => [
      kind,
      {
        ...(filters[kind] !== undefined && { filters: filters[kind] }),
        ...(sorting[kind] !== undefined && { sorting: sorting[kind] }),
      },
    ])
  );
  server.use(
    communityHttp.get("/view-preferences", () =>
      HttpResponse.json({ items: { "view:project:1": { layout, mode: null, parts } } })
    )
  );
};

/** What this person's view of project 1 is written as, each time. */
const captureViewWrites = () => {
  const writes: unknown[] = [];
  server.use(
    communityHttp.put("/view-preferences/:scopeKey", async ({ request }) => {
      writes.push(((await request.json()) as { value: unknown }).value);
      return HttpResponse.json({});
    })
  );
  return writes;
};

/** The filters live in a panel, which starts closed. */
const openFilters = async () => {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /filters/i }));
  return user;
};

/** Toggle one of the assignee tokens ("Assigned to me" / "Unassigned").
 *  They live inside the assignee picker, not as checkboxes of their own —
 *  they answer the same question the people list does. */
const toggleAssigneeToken = async (user: ReturnType<typeof userEvent.setup>, name: RegExp) => {
  await user.click(await screen.findByRole("combobox", { name: /filter by assignee/i }));
  await user.click(await screen.findByRole("option", { name }));
  await user.keyboard("{Escape}");
};

const layoutSwitcher = () => screen.findByRole("combobox", { name: /^layout$/i });

/** Pick a layout the way someone would, rather than seeding the URL. */
const pickLayout = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  await user.click(await layoutSwitcher());
  await user.click(await screen.findByRole("option", { name }));
};

const presetPicker = () => screen.findByRole("combobox", { name: /^presets$/i });

/** Pick a preset from the filter panel, opening it if it is closed. */
const pickPreset = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  if (!screen.queryByRole("combobox", { name: /^presets$/i })) {
    await user.click(await screen.findByRole("button", { name: /filters/i }));
  }
  await user.click(await presetPicker());
  await user.click(await screen.findByRole("option", { name }));
};

const urlLayout = (router: ReturnType<typeof section>["router"]) =>
  (router.state.location.search as { layout?: string }).layout;

const urlPreset = (router: ReturnType<typeof section>["router"]) =>
  (router.state.location.search as { preset?: string }).preset;

beforeEach(() => {
  captureTaskRequests();
  withLayouts({});
});

describe("ProjectTasksSection layouts", () => {
  it("offers the project's layouts, and opens on the one it opens on", async () => {
    withLayouts({
      layouts: [
        { kind: "table", is_default: false, hidden: false, definition: {}, updated_at: null },
        { kind: "board", is_default: true, hidden: false, definition: {}, updated_at: null },
      ],
    });
    const user = userEvent.setup();
    section();

    await waitFor(async () => expect(await layoutSwitcher()).toHaveTextContent("Board"));
    await user.click(await layoutSwitcher());
    // Only layouts: the presets lead the filter panel.
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Table",
      "Board",
      "Gantt",
      "Calendar",
    ]);
  });

  it("offers a calendar a project shows, and draws its tasks on it", async () => {
    withLayouts({
      layouts: [
        { kind: "table", is_default: false, hidden: false, definition: {}, updated_at: null },
        { kind: "calendar", is_default: true, hidden: false, definition: {}, updated_at: null },
      ],
    });
    const user = userEvent.setup();
    section();

    await waitFor(async () => expect(await layoutSwitcher()).toHaveTextContent("Calendar"));
    expect(await screen.findByRole("button", { name: "Today" })).toBeInTheDocument();
    await user.click(await layoutSwitcher());
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Table",
      "Board",
      "Gantt",
      "Calendar",
    ]);
  });

  it("shows a layout when one is chosen, names it in the URL, and keeps it", async () => {
    const writes = captureViewWrites();
    const { router } = section();
    const user = userEvent.setup();
    const navigate = vi.spyOn(router, "navigate");

    await pickLayout(user, "Board");

    await waitFor(() => expect(urlLayout(router)).toBe("board"));
    await waitFor(() =>
      expect(document.querySelector("[data-kanban-scroll-container]")).not.toBeNull()
    );
    // Naming the layout in the URL is bookkeeping about the list you are
    // already looking at, so the router's scroll reset must not fire.
    expect(navigate.mock.calls.at(-1)?.[0]).toMatchObject({ replace: true, resetScroll: false });
    await waitFor(() =>
      expect(writes).toContainEqual(expect.objectContaining({ layout: "board" }))
    );
  });

  it("opens the layout a link names", async () => {
    section({ routerSearch: { layout: "board" } });

    await waitFor(async () => expect(await layoutSwitcher()).toHaveTextContent("Board"));
  });

  it("shows the columns the project's table names, in its order", async () => {
    withLayouts({
      layouts: [
        {
          kind: "table",
          is_default: true,
          hidden: false,
          definition: { columns: ["priority", "title", "dueDate"] },
          updated_at: "2026-10-01T12:00:00.000Z",
        },
      ],
    });
    section();

    const headers = () =>
      screen.queryAllByRole("columnheader").map((cell) => cell.textContent ?? "");
    // The start date, which the table leaves out, is gone once it arrives.
    await waitFor(() => expect(headers()).toContain("Due date"));
    await waitFor(() => expect(headers()).not.toContain("Start date"));
    const at = (name: string) => headers().indexOf(name);
    expect(at("Priority")).toBeLessThan(at("Task"));
    expect(at("Task")).toBeLessThan(at("Due date"));
  });

  it("says the layouts failed to load, and asks again, before listing any tasks", async () => {
    let fail = true;
    let taskRequests = 0;
    server.use(
      communityHttp.get("/layouts/", () =>
        fail ? new HttpResponse(null, { status: 500 }) : HttpResponse.json(buildToolLayoutSet())
      ),
      communityHttp.get("/tasks/", () => {
        taskRequests += 1;
        return HttpResponse.json(buildTaskListResponse([]));
      })
    );
    section();
    const user = userEvent.setup();

    const retry = await screen.findByRole("button", { name: /try again/i });
    expect(screen.getByText(/couldn't load this project's layouts/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /filters/i })).toBeNull();
    expect(taskRequests).toBe(0);

    fail = false;
    await user.click(retry);

    await waitFor(async () => expect(await layoutSwitcher()).toHaveTextContent("Table"));
    await waitFor(() => expect(taskRequests).toBe(1));
  });
});

describe("ProjectTasksSection presets", () => {
  it("offers the layout's shipped presets in the filter panel", async () => {
    section();
    const user = await openFilters();

    await user.click(await presetPicker());
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Incomplete",
      "Unassigned",
      "Mine",
    ]);
  });

  it("applies a preset as this person's own, and names it in the URL", async () => {
    const writes = captureViewWrites();
    const { router } = section();
    const user = userEvent.setup();

    await pickPreset(user, "Unassigned");

    await waitFor(() => expect(urlPreset(router)).toBe("unassigned"));
    await waitFor(() =>
      expect(lastConditions).toContainEqual({ field: "assignee_ids", op: "is_null", value: true })
    );
    // The layout stays the one shown, and the picker says which preset is.
    expect(await layoutSwitcher()).toHaveTextContent("Table");
    expect(await presetPicker()).toHaveTextContent("Unassigned");
    await waitFor(() =>
      expect(writes).toContainEqual(
        expect.objectContaining({
          parts: {
            table: expect.objectContaining({
              filters: expect.objectContaining({ assignees: ["none"] }),
            }),
          },
        })
      )
    );
  });

  it("opens the preset a link names, and lets go of it once the person narrows it", async () => {
    const { router } = section({ routerSearch: { layout: "table", preset: "mine" } });

    await waitFor(() =>
      expect(lastConditions).toContainEqual({ field: "assignee_ids", op: "in_", value: ["me"] })
    );
    const user = await openFilters();
    await toggleAssigneeToken(user, /^Unassigned$/);

    await waitFor(() => expect(urlPreset(router)).toBeUndefined());
    expect(urlLayout(router)).toBe("table");
  });

  it("saves a preset picked again after the person changed its filters", async () => {
    const writes = captureViewWrites();
    const { router } = section();
    const user = userEvent.setup();
    await pickPreset(user, "Unassigned");
    await waitFor(() => expect(urlPreset(router)).toBe("unassigned"));

    // Their own change lets go of the preset...
    await toggleAssigneeToken(user, /^Assigned to me$/);
    await waitFor(() => expect(urlPreset(router)).toBeUndefined());
    writes.length = 0;

    // ...and picking it again makes it theirs again.
    await pickPreset(user, "Unassigned");
    await waitFor(() =>
      expect(writes.at(-1)).toMatchObject({
        parts: { table: { filters: { assignees: ["none"] } } },
      })
    );
  });

  it("offers the layout's own presets, with their sort", async () => {
    withLayouts({
      layouts: [
        {
          kind: "table",
          is_default: true,
          hidden: false,
          definition: {
            presets: [
              {
                name: "Overdue first",
                slug: "overdue",
                filters: { due: "overdue" },
                sort: [{ field: "due_date", dir: "desc" }],
              },
            ],
          },
          updated_at: "2026-10-01T12:00:00.000Z",
        },
      ],
    });
    const writes = captureViewWrites();
    section();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /filters/i }));
    await user.click(await presetPicker());
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Overdue first",
    ]);
    await user.click(screen.getByRole("option", { name: "Overdue first" }));

    await waitFor(() =>
      expect(writes).toContainEqual(
        expect.objectContaining({
          parts: {
            table: expect.objectContaining({ sorting: [{ id: "due date", desc: true }] }),
          },
        })
      )
    );
  });

  it("drops a preset the layout doesn't offer", async () => {
    const { router } = section({ routerSearch: { layout: "board", preset: "nowhere" } });

    await waitFor(() => expect(urlLayout(router)).toBe("board"));
    await waitFor(() => expect(urlPreset(router)).toBeUndefined());
  });
});

describe("ProjectTasksSection a person's filters", () => {
  it("offers statuses and status categories in one control", async () => {
    // One question — "which statuses?" — answered either by naming them or by
    // naming a category, so they share a control rather than sitting in two
    // that could contradict each other.
    section();
    const user = await openFilters();

    await user.click(await screen.findByRole("combobox", { name: /filter by status/i }));

    // "To Do" is a status of this project; the categories sit under their own
    // heading below. A project's statuses are named after categories by
    // default, so "Done" legitimately appears on both sides of the control.
    expect(await screen.findByRole("option", { name: "To Do" })).toBeInTheDocument();
    expect(await screen.findByText(/status category/i)).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "Done" })).toHaveLength(2);
    // Backlog is a category no default status is named after any more, so it
    // appears once — on the category side alone.
    expect(screen.getAllByRole("option", { name: "Backlog" })).toHaveLength(1);
  });

  it("offers 'me' and 'unassigned' inside the assignee picker", async () => {
    // Neither is a person the roster could return — the server resolves both
    // per request. They answer the same question as the people list, so they
    // live in the same control. Unassigned asks with is_null, which no id list
    // can express, and "me" stays a token.
    section();
    const user = await openFilters();

    await toggleAssigneeToken(user, /^Assigned to me$/);
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: /filter by assignee/i })).toHaveTextContent(
        "Assigned to me"
      )
    );
    await toggleAssigneeToken(user, /^Unassigned$/);

    await waitFor(() =>
      expect(lastConditions).toContainEqual({
        logic: "or",
        conditions: [
          { field: "assignee_ids", op: "is_null", value: true },
          { field: "assignee_ids", op: "in_", value: ["me"] },
        ],
      })
    );
  });

  it("keeps a person's filters with the layout they set them on", async () => {
    section();
    const user = await openFilters();
    await toggleAssigneeToken(user, /^Unassigned$/);
    await waitFor(async () => expect(await layoutSwitcher()).toHaveTextContent(/modified/i));

    // Another layout starts from its own, which are none.
    await pickLayout(user, "Board");
    await waitFor(() => expect(fieldsUsed()).not.toContain("assignee_ids"));
    expect(await layoutSwitcher()).not.toHaveTextContent(/modified/i);

    // And coming back finds them as they were left.
    await pickLayout(user, "Table");
    await waitFor(async () => expect(await layoutSwitcher()).toHaveTextContent(/modified/i));
    expect(lastConditions).toContainEqual({ field: "assignee_ids", op: "is_null", value: true });
  });

  it("clears a person's filters for the layout on screen", async () => {
    rememberView({ layout: "table", filters: { table: { assignees: ["none"] } } });
    const writes = captureViewWrites();
    section();
    const user = await openFilters();
    await waitFor(() => expect(fieldsUsed()).toContain("assignee_ids"));

    await user.click(screen.getByRole("button", { name: /clear all/i }));

    await waitFor(() => expect(fieldsUsed()).not.toContain("assignee_ids"));
    await waitFor(() =>
      expect(writes).toContainEqual(
        expect.objectContaining({
          layout: "table",
          parts: { table: expect.not.objectContaining({ filters: expect.anything() }) },
        })
      )
    );
  });

  it("keeps a remembered tag that still exists", async () => {
    // The positive control for the next case: this proves the remembered
    // filter reaches the query at all.
    withTags([7]);
    rememberView({ layout: "table", filters: { table: { tag_ids: [7] } } });
    section();

    await waitFor(() =>
      expect(lastConditions).toContainEqual({ field: "tag_ids", op: "in_", value: [7] })
    );
  });

  it("drops a remembered tag that no longer exists rather than emptying the list", async () => {
    // A deleted tag does not quietly stop narrowing: sent as `tag_ids in (999)`
    // it matches nothing, so the list goes empty and the control that would
    // explain why has no option left to render.
    withTags([7]);
    rememberView({ layout: "table", filters: { table: { tag_ids: [999] } } });
    section();

    // Both in one tick: the first request goes out before the tag list has
    // loaded, when there is nothing yet to prune against, and an empty
    // `lastConditions` would satisfy the negative assertion on its own.
    await waitFor(() => {
      expect(fieldsUsed()).toContain("project_id");
      expect(fieldsUsed()).not.toContain("tag_ids");
    });
  });

  it("stops trusting a remembered tag when the tag list cannot be loaded", async () => {
    // An id that cannot be checked may be hiding every task in the project.
    // Showing more than was asked for is recoverable; an unexplained empty
    // list is not.
    server.use(communityHttp.get("/tags/", () => new HttpResponse(null, { status: 500 })));
    rememberView({ layout: "table", filters: { table: { tag_ids: [7] } } });
    section();

    await waitFor(() => {
      expect(fieldsUsed()).toContain("project_id");
      expect(fieldsUsed()).not.toContain("tag_ids");
    });
  });
});

describe("ProjectTasksSection export", () => {
  /** The `sorting` of the export request a PDF export sends. */
  const exportSorting = async (layout: string) => {
    let sorting: string | null = "unsent";
    server.use(
      communityHttp.get("/exports/tasks", ({ request }) => {
        sorting = new URL(request.url).searchParams.get("sorting");
        return new HttpResponse(new Uint8Array([0x25]), {
          headers: { "Content-Type": "application/pdf" },
        });
      })
    );
    section({ routerSearch: { layout } });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^export$/i }));
    await user.click(await screen.findByRole("menuitem", { name: /pdf document/i }));
    await waitFor(() => expect(sorting).not.toBe("unsent"));
    return sorting;
  };

  beforeEach(() => {
    // The reader's own sort of the table, kept in their view of the project.
    rememberView({ layout: "table", sorting: { table: [{ id: "due date", desc: true }] } });
  });

  it("lists the tasks in the order the reader sorted the table", async () => {
    expect(JSON.parse((await exportSorting("table")) ?? "null")).toEqual([
      { field: "due_date", dir: "desc" },
      { field: "position", dir: "asc" },
    ]);
  });

  it("keeps the project's order from a layout the table's sort does not reach", async () => {
    expect(await exportSorting("board")).toBeNull();
  });
});

describe("ProjectTasksSection ticking tasks off", () => {
  const statuses = buildDefaultTaskStatuses(1);
  const [todo, , done] = statuses;

  /** Task PATCHes wait here until the test answers them. */
  let replies: Array<(response: Response) => void> = [];

  const answer = (index: number, response: Response) => replies[index](response);

  const doneReply = (taskId: number) =>
    HttpResponse.json({
      ...buildTask({ id: taskId, title: `Chore ${taskId}` }),
      task_status_id: done.id,
      task_status: done,
    });

  const table = (count: number) => {
    const tasks = Array.from({ length: count }, (_, index) =>
      buildTask({
        id: index + 1,
        title: `Chore ${index + 1}`,
        task_status_id: todo.id,
        task_status: todo,
      })
    );
    server.use(
      communityHttp.get("/tasks/", () => HttpResponse.json(buildTaskListResponse(tasks))),
      communityHttp.patch(
        "/tasks/:taskId",
        () => new Promise<Response>((resolve) => replies.push(resolve))
      )
    );
    return section({ taskStatuses: statuses });
  };

  const doneBox = async (title: string) => {
    const row = (await screen.findByText(title)).closest("tr");
    if (!row) throw new Error(`no row for ${title}`);
    return within(row).getByRole("checkbox");
  };

  beforeEach(() => {
    replies = [];
    vi.mocked(fireTaskCompletionFeedback).mockClear();
    // The table is virtualized, and jsdom gives every element a zero height,
    // which windows it down to no rows at all. The virtualizer sizes the
    // app's scroller by its client box and each row by its offset box.
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1200);
  });

  it("ticks the box and celebrates before the server answers", async () => {
    table(1);
    const user = userEvent.setup();
    await user.click(await doneBox("Chore 1"));

    await waitFor(() => expect(replies).toHaveLength(1));
    expect(await doneBox("Chore 1")).toBeChecked();
    expect(fireTaskCompletionFeedback).toHaveBeenCalledTimes(1);

    answer(0, await doneReply(1));
    await waitFor(() => expect(replies).toHaveLength(1));
    expect(await doneBox("Chore 1")).toBeChecked();
    // Once, at the click, not again when the reply lands.
    expect(fireTaskCompletionFeedback).toHaveBeenCalledTimes(1);
  });

  it("leaves the other boxes open while one is on its way", async () => {
    table(2);
    const user = userEvent.setup();

    await user.click(await doneBox("Chore 1"));
    const second = await doneBox("Chore 2");

    expect(second).toBeEnabled();
    await user.click(second);

    await waitFor(() => expect(replies).toHaveLength(2));
    expect(await doneBox("Chore 1")).toBeChecked();
    expect(await doneBox("Chore 2")).toBeChecked();
  });

  it("does not toast each tick", async () => {
    const success = vi.spyOn(toast, "success");
    table(1);
    const user = userEvent.setup();

    await user.click(await doneBox("Chore 1"));
    await waitFor(() => expect(replies).toHaveLength(1));
    answer(0, await doneReply(1));

    await waitFor(() => expect(fireTaskCompletionFeedback).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(success).not.toHaveBeenCalled();
    success.mockRestore();
  });

  it("puts the box back when the change fails", async () => {
    table(1);
    const user = userEvent.setup();
    await user.click(await doneBox("Chore 1"));
    await waitFor(() => expect(replies).toHaveLength(1));
    expect(await doneBox("Chore 1")).toBeChecked();

    answer(
      0,
      HttpResponse.json({ detail: "NOT_FOUND", params: { kind: "task" } }, { status: 404 })
    );

    await waitFor(async () => expect(await doneBox("Chore 1")).not.toBeChecked());
  });

  it("keeps the newest choice when an older reply for the same task lands after it", async () => {
    table(1);
    const user = userEvent.setup();

    await user.click(await doneBox("Chore 1"));
    await waitFor(() => expect(replies).toHaveLength(1));
    expect(await doneBox("Chore 1")).toBeChecked();
    await user.click(await doneBox("Chore 1"));
    await waitFor(() => expect(replies).toHaveLength(2));
    expect(await doneBox("Chore 1")).not.toBeChecked();

    // The tick's reply arrives while the untick is still out.
    answer(0, await doneReply(1));
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(await doneBox("Chore 1")).not.toBeChecked();
  });
});

describe("ProjectTasksSection table", () => {
  beforeEach(() => {
    // The table is virtualized, and jsdom gives every element a zero height,
    // which windows it down to no rows at all. The virtualizer sizes the
    // app's scroller by its client box and each row by its offset box.
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1200);
  });

  it("draws a row from the task's fields, as the board's card does", async () => {
    const task = buildTask({
      id: 4,
      title: "Chore 4",
      comment_count: 2,
      tags: [buildTagSummary({ id: 7, name: "Urgent" })],
    });
    server.use(
      communityHttp.get("/tasks/", () => HttpResponse.json(buildTaskListResponse([task])))
    );
    section({ routerSearch: { view: "table" } });

    const row = (await screen.findByRole("link", { name: "Chore 4" })).closest("tr");
    if (!row) throw new Error("no row for Chore 4");
    expect(within(row).getByRole("link", { name: "Chore 4" })).toHaveAttribute("href", "/tasks/4");
    expect(within(row).getByRole("link", { name: "Urgent" })).toHaveAttribute(
      "href",
      "/c/1/tags/7"
    );
    expect(within(row).getByText("2")).toBeInTheDocument();
  });

  it("lets go of a selection when the layout changes", async () => {
    server.use(
      communityHttp.get("/tasks/", () =>
        HttpResponse.json(buildTaskListResponse([buildTask({ title: "Chore 1" })]))
      )
    );
    section();
    const user = userEvent.setup();
    await screen.findByRole("link", { name: "Chore 1" });
    await user.click(await screen.findByRole("button", { name: /^select$/i }));
    await user.click(await screen.findByRole("checkbox", { name: /select row/i }));
    expect(await screen.findByText(/1 task selected/i)).toBeInTheDocument();

    await pickLayout(user, "Board");

    await waitFor(() => expect(screen.queryByText(/1 task selected/i)).not.toBeInTheDocument());
  });
});

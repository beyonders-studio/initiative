/**
 * The task's page: every field saves on its own, as its kind says, and the
 * rest of what a task can do is behind one menu.
 *
 * Deleting from a task's page used to drop you at the initiative's projects
 * list — one step further out than you asked to go, and away from the sibling
 * tasks you were most likely working through. It now returns to the project
 * the task belonged to.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildInitiative,
  buildPage,
  buildProject,
  buildProjectTaskStatus,
  buildPropertyDefinition,
  buildPropertySummary,
  buildTag,
  buildTask,
  buildTaskAssignee,
  buildTaskType,
  buildToolLayoutSet,
  buildUser,
  initiativeCan,
} from "@/__tests__/factories";
import { readerCan } from "@/__tests__/factories/can";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { DetailLayoutRead } from "@/api/generated/initiativeAPI.schemas";
import {
  MetadataType,
  type ProjectRead,
  type PropertySummary,
  type TaskRead,
  type TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { getReadTaskQueryKey } from "@/api/generated/tasks/tasks";
import { clearStoredServerUrl, setStoredServerUrl } from "@/lib/serverStorage";

import { TaskEditPage } from "./TaskEditPage";

const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/mascotToast", () => ({ toast: toasts }));

const COMMUNITY_ID = 1;
const INITIATIVE_ID = 5;
const PROJECT_ID = 7;
const TASK_ID = 2726;

const TASK_ROUTE = "/c/$communityId/i/$initiativeId/projects/$projectId/tasks/$taskId";

const TODO = buildProjectTaskStatus({ id: 1, name: "To Do", category: "todo" });
const DOING = buildProjectTaskStatus({ id: 2, name: "Doing", category: "in_progress" });

/** What the page asked the project list for, newest last. */
const listed: URLSearchParams[] = [];

/** The project the task actually belongs to, which a move can change. */
const renderTaskPage = ({
  taskProjectId = PROJECT_ID,
  /** What the project reports; a column the task uses can be missing from it. */
  statuses = [TODO, DOING],
  recurrence = null,
  lastOccurrence = false,
  properties = [],
  destinations = [],
  keepContentIn = false,
  description = null,
  dueDate = null,
  assignees = [],
  canEdit = true,
  moderates = false,
  refuse,
  userId,
}: {
  taskProjectId?: number;
  /** Other projects the person may move the task into. */
  destinations?: ProjectRead[];
  keepContentIn?: boolean;
  properties?: PropertySummary[];
  statuses?: TaskStatusRead[];
  recurrence?: string | null;
  /** Deleting just this task trashes it, as nothing comes after it. */
  lastOccurrence?: boolean;
  description?: string | null;
  dueDate?: string | null;
  assignees?: TaskRead["assignees"];
  canEdit?: boolean;
  /** Whether the reader moderates the task's initiative. */
  moderates?: boolean;
  /** An answer to an update in place of saving it, when it returns one; it
   *  may hold the update until it settles. */
  refuse?: (body: Record<string, unknown>) => Response | undefined | Promise<Response | undefined>;
  /** Who is signed in. */
  userId?: number;
} = {}) => {
  let gone = false;
  const task = {
    ...buildTask({
      id: TASK_ID,
      project_id: taskProjectId,
      title: "Wire the doorbell",
      recurrence,
      properties,
      due_date: dueDate,
      assignees,
    }),
    description,
    series_size: 3,
  };
  const project = buildProject({
    id: taskProjectId,
    initiative_id: INITIATIVE_ID,
    name: "Rewiring",
    ...(canEdit ? {} : { can: { ...readerCan(), configure: false } }),
  });
  const deleted = vi.fn();
  /** Every update the page sent, in order. */
  const sent: Record<string, unknown>[] = [];

  server.use(
    communityHttp.get("/tasks/:taskId", () =>
      gone ? new HttpResponse(null, { status: 404 }) : HttpResponse.json(task)
    ),
    communityHttp.patch("/tasks/:taskId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      const refused = await refuse?.(body);
      if (refused) return refused;
      for (const field of ["title", "description", "priority", "start_date", "due_date"]) {
        if (field in body) Object.assign(task, { [field]: body[field] });
      }
      const status = statuses.find((candidate) => candidate.id === body.task_status_id);
      if (status) Object.assign(task, { task_status_id: status.id, task_status: status });
      return HttpResponse.json(task);
    }),
    // The collection routes go first: `:projectId` would otherwise swallow
    // them and answer a list request with a single project.
    communityHttp.get("/projects/", ({ request }) => {
      const params = new URL(request.url).searchParams;
      listed.push(params);
      // The move dialog's destinations come a page at a time.
      return HttpResponse.json(
        params.get("writable") === "true" ? buildPage([project, ...destinations]) : [project]
      );
    }),
    communityHttp.get("/projects/writable", () => HttpResponse.json([project])),
    communityHttp.get("/initiatives/:id", () =>
      HttpResponse.json(
        buildInitiative({
          id: INITIATIVE_ID,
          keep_content_in: keepContentIn,
          can: initiativeCan({ moderate: moderates }),
        })
      )
    ),
    communityHttp.get("/projects/:projectId", () => HttpResponse.json(project)),
    communityHttp.get("/projects/:id/task-statuses/", () => HttpResponse.json(statuses)),
    communityHttp.delete("/tasks/:taskId", ({ request }) => {
      const scope = new URL(request.url).searchParams.get("scope");
      gone = scope !== "this" || lastOccurrence;
      deleted(scope);
      return new HttpResponse(null, { status: 204 });
    })
  );

  const { router, unmount, queryClient } = renderPage(TaskEditPage, {
    ...(userId ? { auth: { user: buildUser({ id: userId }) } } : {}),
    initialRoute: TASK_ROUTE,
    routeParams: {
      communityId: String(COMMUNITY_ID),
      initiativeId: String(INITIATIVE_ID),
      projectId: String(PROJECT_ID),
      taskId: String(TASK_ID),
    },
  });

  return { router, unmount, queryClient, deleted, task, sent };
};

/** A field on the page, by its label. */
/** A task page laid out by its project: a titled section of the description,
 *  and nothing at the side. */
const LAYOUT: DetailLayoutRead[] = [
  {
    kind: "task",
    task_type_id: 1,
    task_type_name: "Task",
    updated_at: "2026-10-01T12:00:00.000Z",
    definition: {
      main: [
        {
          type: "section",
          props: { title: "Work" },
          children: [{ type: "field", props: { field: "description" } }],
        },
      ],
      side: [],
    },
  },
];

const fieldNamed = (name: RegExp) => screen.findByRole("group", { name });

const choose = async (field: RegExp, option: RegExp) => {
  await userEvent.click(within(await fieldNamed(field)).getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: option }));
};

/** Wait for a field to say its save went through. */
const expectSaved = async (field: RegExp) => {
  const frame = await fieldNamed(field);
  await waitFor(() => expect(within(frame).getByRole("status")).toHaveTextContent(/saved/i));
};

/** The description opens on its preview; this turns to its field. */
const openDescription = async () =>
  userEvent.click(
    within(await fieldNamed(/^description$/i)).getByRole("tab", { name: /^write$/i })
  );

/** Text the page shows, not what the description's hidden field holds. */
const shown = (text: string) => screen.findByText(text, { selector: ":not(textarea)" });

const saveButton = () => screen.queryByRole("button", { name: /^save$/i });

describe("TaskEditPage", () => {
  beforeEach(() => {
    toasts.success.mockClear();
  });

  const openActionsMenu = async () =>
    userEvent.click(await screen.findByRole("button", { name: /more actions/i }));

  const deleteTheTask = async () => {
    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete task/i }));
    // The confirm dialog repeats the label; the last match is its button.
    const confirms = await screen.findAllByRole("button", { name: /delete/i });
    await userEvent.click(confirms[confirms.length - 1]);
  };

  it("has no save button, and keeps what else a task can do behind one menu", async () => {
    renderTaskPage();

    await openActionsMenu();

    for (const name of [/move to project/i, /duplicate task/i, /archive/i, /delete task/i]) {
      expect(await screen.findByRole("menuitem", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /^save/i })).not.toBeInTheDocument();
  });

  describe("what a new page requires", () => {
    const required = (taskTypeId: number, name: string, fields = ["tags"]) =>
      buildToolLayoutSet({
        layouts: [
          {
            kind: "task",
            task_type_id: taskTypeId,
            task_type_name: name,
            updated_at: "2026-10-01T12:00:00.000Z",
            definition: {
              side: fields.map((field) => ({ type: "field", props: { field, required: true } })),
            },
          },
        ],
      });
    /** A project whose second type is Idea, laid out as `layouts` says. */
    const withIdea = (layouts: ReturnType<typeof required>) =>
      server.use(
        communityHttp.get("/projects/:id/task-types/", () =>
          HttpResponse.json([
            buildTaskType({ id: 1, name: "Task", project_id: PROJECT_ID, is_default: true }),
            buildTaskType({ id: 9, name: "Idea", project_id: PROJECT_ID, position: 1 }),
          ])
        ),
        communityHttp.get("/layouts/", () => HttpResponse.json(layouts))
      );

    /** Picks the tag Wiring in the dialog asking for what is required, and
     *  goes on with the change. */
    const fillIn = async (title: string) => {
      const asking = await screen.findByRole("dialog", { name: title });
      const go = within(asking).getByRole("button", { name: "Continue" });
      expect(go).toBeDisabled();
      await userEvent.click(within(asking).getByRole("combobox"));
      await userEvent.click(await screen.findByRole("option", { name: "Wiring" }));
      await waitFor(() => expect(go).toBeEnabled());
      await userEvent.click(go);
    };

    beforeEach(() => {
      toasts.error.mockClear();
      server.use(
        communityHttp.get("/tags/", () => HttpResponse.json([buildTag({ id: 7, name: "Wiring" })]))
      );
    });

    it("asks before the task becomes a type whose page needs more, and sends it with the change", async () => {
      withIdea(required(9, "Idea"));
      const { sent } = renderTaskPage();

      await choose(/^type$/i, /idea/i);
      await fillIn("What the Idea page asks for");

      await waitFor(() =>
        expect(sent).toEqual([expect.objectContaining({ task_type_id: 9, tag_ids: [7] })])
      );
    });

    it("keeps what was filled in when the change fails, on a page without the type picker", async () => {
      // Idea's page holds the tags alone: the type picker is not on it.
      withIdea(required(9, "Idea"));
      const { sent } = renderTaskPage({
        refuse: () => HttpResponse.json({ detail: "SOMETHING_WENT_WRONG" }, { status: 500 }),
      });

      await choose(/^type$/i, /idea/i);
      await fillIn("What the Idea page asks for");

      await waitFor(() => expect(sent).toHaveLength(1));
      const asking = screen.getByRole("dialog", { name: "What the Idea page asks for" });
      await waitFor(() =>
        expect(within(asking).getByRole("button", { name: "Continue" })).toBeEnabled()
      );
      // The task is shown as the type it still is.
      expect(
        within(screen.getByRole("group", { name: /^type$/i, hidden: true })).getByRole("combobox", {
          hidden: true,
        })
      ).toHaveTextContent("Task");
    });

    it("names the description it was written over, so a change made meanwhile is not lost", async () => {
      withIdea(required(9, "Idea", ["description"]));
      const { sent } = renderTaskPage();

      await choose(/^type$/i, /idea/i);
      const asking = await screen.findByRole("dialog", { name: "What the Idea page asks for" });
      await userEvent.type(within(asking).getByRole("textbox"), "Two wires, one bell");
      await userEvent.click(within(asking).getByRole("button", { name: "Continue" }));

      await waitFor(() =>
        expect(sent).toEqual([
          expect.objectContaining({
            task_type_id: 9,
            description: "Two wires, one bell",
            description_base: null,
          }),
        ])
      );
    });

    it("starts the people a move asks for empty, as the move left them", async () => {
      server.use(
        communityHttp.post("/tasks/:taskId/move", () =>
          HttpResponse.json(
            {
              detail: "REQUIRED_FIELDS_MISSING",
              params: { fields: "assignees", keys: "assignees" },
            },
            { status: 400 }
          )
        )
      );
      renderTaskPage({
        assignees: [buildTaskAssignee({ id: 4, display_name: "Sam Vimes" })],
        destinations: [buildProject({ id: 8, initiative_id: INITIATIVE_ID, name: "Lighting" })],
      });

      await openActionsMenu();
      await userEvent.click(await screen.findByRole("menuitem", { name: /move to project/i }));
      const moving = await screen.findByRole("dialog", { name: "Move task to another project" });
      await userEvent.click(within(moving).getByRole("combobox"));
      await userEvent.click(await screen.findByRole("option", { name: "Lighting" }));
      await userEvent.click(within(moving).getByRole("button", { name: "Move task" }));

      const asking = await screen.findByRole("dialog", { name: "What Lighting asks for" });
      expect(within(asking).queryByText("Sam Vimes")).not.toBeInTheDocument();
      expect(within(asking).getByRole("button", { name: "Continue" })).toBeDisabled();
    });

    it("asks for what the destination requires when a move is refused for it, and moves with it", async () => {
      const moves: Record<string, unknown>[] = [];
      server.use(
        communityHttp.post("/tasks/:taskId/move", async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          moves.push(body);
          return body.changes
            ? HttpResponse.json(buildTask({ id: TASK_ID, project_id: 8 }))
            : HttpResponse.json(
                { detail: "REQUIRED_FIELDS_MISSING", params: { fields: "tags", keys: "tags" } },
                { status: 400 }
              );
        })
      );
      renderTaskPage({
        destinations: [buildProject({ id: 8, initiative_id: INITIATIVE_ID, name: "Lighting" })],
      });

      await openActionsMenu();
      await userEvent.click(await screen.findByRole("menuitem", { name: /move to project/i }));
      const moving = await screen.findByRole("dialog", { name: "Move task to another project" });
      await userEvent.click(within(moving).getByRole("combobox"));
      await userEvent.click(await screen.findByRole("option", { name: "Lighting" }));
      await userEvent.click(within(moving).getByRole("button", { name: "Move task" }));
      await fillIn("What Lighting asks for");

      await waitFor(() =>
        expect(moves).toEqual([
          { target_project_id: 8 },
          { target_project_id: 8, changes: { tag_ids: [7] } },
        ])
      );
      expect(toasts.error).not.toHaveBeenCalled();
    });
  });

  it("gives a moderator a shield on the task, even read-only", async () => {
    renderTaskPage({ moderates: true, canEdit: false });

    await userEvent.click(await screen.findByRole("button", { name: "Moderate" }));
    for (const name of ["Remove…", "Warn…", "Hold for the platform…"]) {
      expect(await screen.findByRole("menuitem", { name })).toBeInTheDocument();
    }
    // The lock is on the comment thread, where every kind of thread has one.
    expect(screen.queryByRole("menuitem", { name: /lock comments/i })).toBeNull();
  });

  it("gives nobody else a shield", async () => {
    renderTaskPage();
    await screen.findByRole("button", { name: /more actions/i });
    expect(screen.queryByRole("button", { name: "Moderate" })).toBeNull();
  });

  it("saves a status as it is chosen, and offers to undo the move", async () => {
    const { sent } = renderTaskPage();

    await choose(/^status$/i, /doing/i);

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ task_status_id: DOING.id });
    expect(sent[0]).not.toHaveProperty("title");
    await waitFor(() => expect(toasts.success).toHaveBeenCalled());
    const [message, options] = toasts.success.mock.calls[0];
    expect(message).toBe("Moved to Doing");

    options.action.onClick();

    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({ task_status_id: TODO.id });
  });

  it("saves the title on Enter and on leaving it, and Esc puts the saved one back", async () => {
    const { sent } = renderTaskPage();
    const title = await screen.findByDisplayValue("Wire the doorbell");

    await userEvent.type(title, " now");
    expect(sent).toHaveLength(0);
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ title: "Wire the doorbell now" });

    await userEvent.type(title, "!!");
    await userEvent.keyboard("{Escape}");
    expect(title).toHaveValue("Wire the doorbell now");

    await userEvent.type(title, " please");
    await userEvent.tab();
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({ title: "Wire the doorbell now please" });
  });

  it("wraps the title rather than cutting it off, and keeps it to one line", async () => {
    const { sent } = renderTaskPage();
    const title = await screen.findByDisplayValue("Wire the doorbell");
    expect(title.tagName).toBe("TEXTAREA");

    await userEvent.click(title);
    await userEvent.paste("\nand the\r\nchime");
    expect(title).toHaveValue("Wire the doorbell and the chime");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ title: "Wire the doorbell and the chime" });
  });

  it("opens the description on its preview, keeps what is typed, and saves it over what it read", async () => {
    const first = renderTaskPage({ description: "Old words", userId: 41 });
    const description = await fieldNamed(/^description$/i);
    expect(within(description).getByRole("tab", { name: /^preview$/i })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(await shown("Old words")).toBeInTheDocument();
    expect(saveButton()).not.toBeInTheDocument();

    await openDescription();
    const editor = await screen.findByRole("textbox", { name: /^description$/i });
    await userEvent.clear(editor);
    await userEvent.type(editor, "New words");
    expect(first.sent).toHaveLength(0);
    first.unmount();

    // The draft is the account's own, on its own server.
    const other = renderTaskPage({ description: "Old words", userId: 42 });
    expect(await shown("Old words")).toBeInTheDocument();
    expect(saveButton()).not.toBeInTheDocument();
    other.unmount();
    setStoredServerUrl("https://elsewhere.example/api/v1");
    const elsewhere = renderTaskPage({ description: "Old words", userId: 41 });
    expect(await shown("Old words")).toBeInTheDocument();
    expect(saveButton()).not.toBeInTheDocument();
    elsewhere.unmount();
    clearStoredServerUrl();

    // Coming back finds the draft where it was left.
    const { sent } = renderTaskPage({ description: "Old words", userId: 41 });
    expect(await shown("New words")).toBeInTheDocument();
    await openDescription();
    const restored = screen.getByRole("textbox", { name: /^description$/i });
    expect(restored).toHaveValue("New words");

    await userEvent.type(restored, "{Control>}{Enter}{/Control}");

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ description: "New words", description_base: "Old words" });
    await waitFor(() => expect(saveButton()).not.toBeInTheDocument());
    expect(restored).toHaveValue("New words");
  });

  it("keeps a draft but offers nothing that writes once the task is read-only", async () => {
    const first = renderTaskPage({ description: "Old words", userId: 43 });
    await openDescription();
    await userEvent.type(await screen.findByRole("textbox", { name: /^description$/i }), " more");
    first.unmount();

    const reader = renderTaskPage({ description: "Old words", userId: 43, canEdit: false });
    const description = await fieldNamed(/^description$/i);
    expect(await within(description).findByText("Old words")).toBeInTheDocument();
    expect(within(description).getByText(/draft .* is kept on this device/i)).toBeInTheDocument();
    expect(within(description).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(description).queryByRole("button")).not.toBeInTheDocument();
    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    expect(reader.sent).toHaveLength(0);
    reader.unmount();

    // Editing again finds it where it was left.
    renderTaskPage({ description: "Old words", userId: 43 });
    await openDescription();
    expect(screen.getByRole("textbox", { name: /^description$/i })).toHaveValue("Old words more");
  });

  it("keeps what is typed while the description saves, as a draft over the saved text", async () => {
    let release = () => {};
    const held = new Promise<undefined>((resolve) => {
      release = () => resolve(undefined);
    });
    const { sent } = renderTaskPage({
      description: "Old words",
      refuse: (body) => (sent.length === 1 ? held : undefined),
    });

    await openDescription();
    const editor = await screen.findByRole("textbox", { name: /^description$/i });
    await userEvent.type(editor, " one");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    await userEvent.type(editor, " two");
    release();

    await expectSaved(/^description$/i);
    expect(screen.getByRole("textbox", { name: /^description$/i })).toHaveValue(
      "Old words one two"
    );

    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({
      description: "Old words one two",
      description_base: "Old words one",
    });
  });

  it("closes the description's draft when Retry saves it", async () => {
    let failing = true;
    const { sent } = renderTaskPage({
      description: "Old words",
      refuse: () => (failing ? new HttpResponse(null, { status: 500 }) : undefined),
    });

    await openDescription();
    await userEvent.type(await screen.findByRole("textbox", { name: /^description$/i }), " more");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const description = await fieldNamed(/^description$/i);
    expect(await within(description).findByRole("alert")).toHaveTextContent(/couldn't save/i);

    failing = false;
    await userEvent.click(within(description).getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(sent).toHaveLength(2));
    await waitFor(() => expect(saveButton()).not.toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: /^description$/i })).toHaveValue("Old words more");
  });

  it("starts another task's page afresh, on its description's preview", async () => {
    const { router, queryClient } = renderTaskPage({ description: "Old words" });
    const other = {
      ...buildTask({ id: TASK_ID + 1, project_id: PROJECT_ID }),
      description: "Its words",
    };
    server.use(
      communityHttp.get("/tasks/:taskId", ({ params }) =>
        params.taskId === String(other.id) ? HttpResponse.json(other) : undefined
      )
    );
    // The other task is already read, so its page draws at once.
    const otherKey = getReadTaskQueryKey(COMMUNITY_ID, other.id);
    queryClient.setQueryDefaults(otherKey, { gcTime: Number.POSITIVE_INFINITY });
    queryClient.setQueryData(otherKey, other);

    await openDescription();
    expect(await screen.findByRole("textbox", { name: /^description$/i })).toHaveValue("Old words");

    await router.navigate({
      to: `/c/${COMMUNITY_ID}/i/${INITIATIVE_ID}/projects/${PROJECT_ID}/tasks/${other.id}`,
    });

    expect(await shown("Its words")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /^description$/i })).not.toBeInTheDocument();
  });

  it("shows the other version when the description changed meanwhile, and overwrites only when asked", async () => {
    const { sent, task } = renderTaskPage({
      description: "Old words",
      refuse: (body) =>
        body.description_base === task.description
          ? undefined
          : HttpResponse.json({ detail: "DESCRIPTION_CHANGED" }, { status: 409 }),
    });
    await shown("Old words");
    // Somebody else saves theirs first.
    task.description = "Their words";

    await openDescription();
    await userEvent.type(
      await screen.findByRole("textbox", { name: /^description$/i }),
      " and mine"
    );
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    const conflict = await screen.findByRole("alert");
    expect(conflict).toHaveTextContent(/this changed while you were editing/i);
    expect(await within(conflict).findByText("Their words")).toBeInTheDocument();
    expect(sent).toHaveLength(1);

    await userEvent.click(within(conflict).getByRole("button", { name: /overwrite/i }));

    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({
      description: "Old words and mine",
      description_base: "Their words",
    });
  });

  it("checks the dates as a pair, and saves neither while they are the wrong way round", async () => {
    const { sent } = renderTaskPage({ dueDate: "2026-08-01T12:00:00" });
    await userEvent.click(await screen.findByRole("button", { name: /start date/i }));
    const typed = await screen.findByRole("textbox", { name: /type or pick a date/i });

    await userEvent.type(typed, "2026-08-10{Enter}");

    expect(within(await fieldNamed(/schedule/i)).getByRole("alert")).toBeInTheDocument();
    expect(sent).toHaveLength(0);

    await userEvent.clear(typed);
    await userEvent.type(typed, "2026-07-20{Enter}");

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toHaveProperty("start_date");
    expect(sent[0]).not.toHaveProperty("due_date");
  });

  it("asks which tasks of a repeating series a change is for", async () => {
    const { sent } = renderTaskPage({ recurrence: "RRULE:FREQ=DAILY" });

    await choose(/^priority$/i, /^high$/i);
    expect(await screen.findByLabelText(/all tasks in the series \(3\)/i)).toBeInTheDocument();
    expect(sent).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ priority: "high", scope: "this" });
  });

  it("lays the page out as its project's layout says, leaving out what it doesn't place", async () => {
    // The task was moved: its new project lays its page out, while the path
    // still names the one it came from.
    const MOVED_TO = PROJECT_ID + 1;
    server.use(
      communityHttp.get("/layouts/", ({ request }) =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts:
              new URL(request.url).searchParams.get("tool_id") === String(MOVED_TO) ? LAYOUT : [],
          })
        )
      )
    );
    renderTaskPage({ taskProjectId: MOVED_TO });

    expect(await screen.findByRole("button", { name: "Work" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^status$/i })).not.toBeInTheDocument();
  });

  it("shows every field read-only to a reader", async () => {
    renderTaskPage({ canEdit: false, description: "Old words" });

    // The title is the page's heading, with no box to change it in.
    expect(
      await screen.findByRole("heading", { level: 1, name: "Wire the doorbell" })
    ).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Wire the doorbell")).not.toBeInTheDocument();
    expect(within(await fieldNamed(/^status$/i)).getByRole("combobox")).toBeDisabled();
    const description = await fieldNamed(/^description$/i);
    expect(within(description).getByText("Old words")).toBeInTheDocument();
    expect(within(description).queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /more actions/i })).not.toBeInTheDocument();
  });

  it("offers a reader the actions a plug-in puts in the task's menu, and only those", async () => {
    // Whether the reader may is the plug-in's to say, not the task's.
    const ran = vi.fn();
    const action = { id: "link", name: { en: "Link an issue" }, on: ["task"], menu: true };
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({
          items: [
            {
              id: 3,
              enabled: true,
              definition: { actions: [action, { ...action, id: "hidden", menu: false }] },
              item_initiatives: [INITIATIVE_ID],
              item_fields: [],
              item_parts: [],
              item_actions: ["link", "hidden"],
            },
          ],
        })
      ),
      communityHttp.post("/plugins/3/actions/link", async ({ request }) => {
        ran(await request.json());
        return HttpResponse.json({ values: {} });
      })
    );
    renderTaskPage({ canEdit: false });

    await userEvent.click(await screen.findByRole("button", { name: /more actions/i }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      "Link an issue",
    ]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Link an issue" }));

    await waitFor(() =>
      expect(ran).toHaveBeenCalledWith({ entity_type: "task", entity_id: TASK_ID })
    );
  });

  it("keeps a failed save's error on its field until Retry sends it again", async () => {
    let failing = true;
    const { sent } = renderTaskPage({
      refuse: () => (failing ? new HttpResponse(null, { status: 500 }) : undefined),
    });

    await choose(/^priority$/i, /^high$/i);

    const priority = await fieldNamed(/^priority$/i);
    expect(await within(priority).findByRole("alert")).toHaveTextContent(/couldn't save/i);
    expect(within(await fieldNamed(/^status$/i)).queryByRole("alert")).not.toBeInTheDocument();

    failing = false;
    await userEvent.click(within(priority).getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({ priority: "high" });
    await waitFor(() => expect(within(priority).queryByRole("alert")).not.toBeInTheDocument());
  });

  it("sends a task's saves one at a time, so the last change made is the one kept", async () => {
    let release = () => {};
    const held = new Promise<undefined>((resolve) => {
      release = () => resolve(undefined);
    });
    // The first answer would come back last, were the second not waiting for it.
    const { sent, task } = renderTaskPage({ refuse: () => (sent.length === 1 ? held : undefined) });

    await choose(/^priority$/i, /^high$/i);
    await waitFor(() => expect(sent).toHaveLength(1));
    await choose(/^priority$/i, /^low$/i);
    const priority = within(await fieldNamed(/^priority$/i)).getByRole("combobox");
    expect(priority).toHaveTextContent(/low/i);
    expect(sent).toHaveLength(1);

    release();

    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent.map((body) => body.priority)).toEqual(["high", "low"]);
    await expectSaved(/^priority$/i);
    expect(task.priority).toBe("low");
    expect(priority).toHaveTextContent(/low/i);
  });

  it("keeps showing the changes not yet saved when the task is read again", async () => {
    let release = () => {};
    const held = new Promise<undefined>((resolve) => {
      release = () => resolve(undefined);
    });
    const { sent, queryClient } = renderTaskPage({
      refuse: (body) => ("priority" in body ? held : undefined),
    });

    await choose(/^priority$/i, /^high$/i);
    await waitFor(() => expect(sent).toHaveLength(1));
    // The title's save waits behind the priority's.
    const title = await screen.findByDisplayValue("Wire the doorbell");
    await userEvent.type(title, " now{Enter}");
    // A read meanwhile has neither change yet.
    await queryClient.refetchQueries({ queryKey: getReadTaskQueryKey(COMMUNITY_ID, TASK_ID) });

    const priority = within(await fieldNamed(/^priority$/i)).getByRole("combobox");
    expect(priority).toHaveTextContent(/high/i);
    expect(title).toHaveValue("Wire the doorbell now");
    expect(sent).toHaveLength(1);

    release();
    await expectSaved(/^task$/i);
    expect(sent[1]).toMatchObject({ title: "Wire the doorbell now" });
    expect(priority).toHaveTextContent(/high/i);
    expect(title).toHaveValue("Wire the doorbell now");
  });

  it("lets no read begun before a save land over it", async () => {
    const hold = () => {
      let release = () => {};
      const held = new Promise<undefined>((resolve) => {
        release = () => resolve(undefined);
      });
      return { held, release };
    };
    const titleSave = hold();
    const prioritySave = hold();
    const { sent, queryClient } = renderTaskPage({
      refuse: (body) => ("priority" in body ? prioritySave.held : titleSave.held),
    });
    const title = await screen.findByDisplayValue("Wire the doorbell");
    // A read that takes the task as it is now and answers late.
    const read = hold();
    const key = getReadTaskQueryKey(COMMUNITY_ID, TASK_ID);
    const stale = { ...(queryClient.getQueryData(key) as object) };
    server.use(
      communityHttp.get("/tasks/:taskId", async () => {
        await read.held;
        return HttpResponse.json(stale);
      })
    );
    void queryClient.refetchQueries({ queryKey: key });

    // The title saves while the priority waits its turn behind it.
    await userEvent.type(title, " now{Enter}");
    await waitFor(() => expect(sent).toHaveLength(1));
    await choose(/^priority$/i, /^high$/i);
    titleSave.release();
    await waitFor(() => expect(sent).toHaveLength(2));
    // The old read answers while the priority is still being saved.
    read.release();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(queryClient.getQueryData<TaskRead>(key)?.title).toBe("Wire the doorbell now");
    prioritySave.release();
  });

  it("writes nothing into the next session when a save lands after it began", async () => {
    let release = () => {};
    const held = new Promise<undefined>((resolve) => {
      release = () => resolve(undefined);
    });
    const { sent, unmount, queryClient } = renderTaskPage({ refuse: () => held });

    await choose(/^status$/i, /doing/i);
    await waitFor(() => expect(sent).toHaveLength(1));
    // Signed out, and into another server whose task has the same ids.
    unmount();
    queryClient.clear();
    setStoredServerUrl("https://elsewhere.example/api/v1");
    const key = getReadTaskQueryKey(COMMUNITY_ID, TASK_ID);
    const theirs = { ...buildTask({ id: TASK_ID, project_id: PROJECT_ID }), title: "Theirs" };
    queryClient.setQueryData(key, theirs);
    const landed = new Promise<void>((resolve) =>
      queryClient.getMutationCache().subscribe((event) => {
        if (event.type === "updated" && event.action.type === "success") resolve();
      })
    );

    release();
    await landed;
    clearStoredServerUrl();

    expect(queryClient.getQueryData(key)).toEqual(theirs);
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);
    expect(toasts.success).not.toHaveBeenCalled();
  });

  it("keeps a failed property removal's error on the property, with Retry", async () => {
    let failing = true;
    let refuse = () => {};
    const refused = new Promise<void>((resolve) => {
      refuse = resolve;
    });
    const { task } = renderTaskPage({
      properties: [
        buildPropertySummary({
          property_id: 6,
          name: "Notes",
          type: MetadataType.text,
          value: "x",
        }),
      ],
    });
    const written: { removed?: number[] }[] = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request }) => {
        const body = (await request.json()) as { removed?: number[] };
        written.push(body);
        if (failing) {
          await refused;
          return new HttpResponse(null, { status: 500 });
        }
        task.properties = task.properties.filter((p) => !body.removed?.includes(p.property_id));
        return HttpResponse.json(task.properties);
      })
    );

    const notes = await fieldNamed(/^notes$/i);
    await userEvent.click(within(notes).getByRole("button", { name: /remove/i }));
    await waitFor(() => expect(written).toHaveLength(1));
    refuse();

    expect(await within(notes).findByRole("alert")).toHaveTextContent(/couldn't save/i);
    failing = false;
    await userEvent.click(within(notes).getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(written).toHaveLength(2));
    expect(written[1]).toMatchObject({ removed: [6] });
    await waitFor(() =>
      expect(screen.queryByRole("group", { name: /^notes$/i })).not.toBeInTheDocument()
    );
  });

  it("saves one property on its own, sending only that one", async () => {
    // Two people editing different properties both keep what they wrote.
    const { sent, task } = renderTaskPage({
      properties: [
        buildPropertySummary({
          property_id: 4,
          name: "Hours",
          type: MetadataType.number,
          value: 1,
        }),
        buildPropertySummary({
          property_id: 6,
          name: "Notes",
          type: MetadataType.text,
          value: "x",
        }),
      ],
    });
    const written: { values: { property_id: number; value: unknown }[]; removed?: number[] }[] = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request }) => {
        const body = (await request.json()) as (typeof written)[number];
        written.push(body);
        task.properties = task.properties
          .filter((p) => !body.removed?.includes(p.property_id))
          .map((p) => ({
            ...p,
            value: body.values.find((v) => v.property_id === p.property_id)?.value ?? p.value,
          }));
        return HttpResponse.json(task.properties);
      })
    );

    const hours = await screen.findByPlaceholderText("0");
    await userEvent.clear(hours);
    await userEvent.type(hours, "8");
    expect(written).toHaveLength(0);
    await userEvent.tab();

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({ values: [{ property_id: 4, value: 8 }], merge: true });
    expect(await within(await fieldNamed(/^hours$/i)).findByRole("status")).toHaveTextContent(
      /saved/i
    );

    await userEvent.click(
      within(await fieldNamed(/^notes$/i)).getByRole("button", { name: /remove/i })
    );

    await waitFor(() => expect(written).toHaveLength(2));
    expect(written[1]).toEqual({ values: [], removed: [6], merge: true });
    expect(sent).toHaveLength(0);
  });

  it("draws a task with its type's page, and redraws it when the type changes", async () => {
    const types = [
      buildTaskType({ id: 1, name: "Task", is_default: true }),
      buildTaskType({ id: 2, name: "Bug", icon: "bug", layout_preset: "fix" }),
    ];
    server.use(
      communityHttp.get("/projects/:id/task-types/", () => HttpResponse.json(types)),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "task",
                task_type_id: 2,
                task_type_name: "Bug",
                updated_at: "2026-10-01T12:00:00.000Z",
                definition: {
                  main: [
                    {
                      type: "section",
                      props: { title: "Steps" },
                      children: [{ type: "field", props: { field: "description" } }],
                    },
                  ],
                  side: [{ type: "field", props: { field: "type" } }],
                },
              },
            ],
          })
        )
      )
    );
    const { task } = renderTaskPage();
    const sent: Record<string, unknown>[] = [];
    server.use(
      communityHttp.patch("/tasks/:taskId", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        sent.push(body);
        const type = types.find((each) => each.id === body.task_type_id);
        if (type) Object.assign(task, { task_type_id: type.id, task_type: type });
        return HttpResponse.json(task);
      })
    );

    // A Task is drawn as the shipped page.
    await fieldNamed(/^type$/i);
    expect(screen.queryByRole("button", { name: "Steps" })).not.toBeInTheDocument();

    await choose(/^type$/i, /bug/i);

    await waitFor(() => expect(sent).toEqual([expect.objectContaining({ task_type_id: 2 })]));
    expect(await screen.findByRole("button", { name: "Steps" })).toBeInTheDocument();
    // Undo says what it takes back.
    await waitFor(() => expect(toasts.success).toHaveBeenCalled());
    expect(toasts.success.mock.calls[0][0]).toBe("Changed to Bug");
  });

  it("shows no type in a project with only one", async () => {
    server.use(
      communityHttp.get("/projects/:id/task-types/", () =>
        HttpResponse.json([buildTaskType({ id: 1, name: "Task", is_default: true })])
      )
    );
    renderTaskPage();

    await fieldNamed(/^priority$/i);
    expect(screen.queryByRole("group", { name: /^type$/i })).not.toBeInTheDocument();
  });

  it("draws a property the layout places on its own, saving it there", async () => {
    server.use(
      communityHttp.get("/property-definitions/", () =>
        HttpResponse.json([
          buildPropertyDefinition({ id: 9, name: "Risk", type: MetadataType.text }),
        ])
      ),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "task",
                task_type_id: 1,
                task_type_name: "Task",
                updated_at: "2026-10-01T12:00:00.000Z",
                definition: {
                  side: [{ type: "field", props: { field: "property:9" } }, { type: "properties" }],
                },
              },
            ],
          })
        )
      )
    );
    // The task has no value for it yet.
    const { task } = renderTaskPage();
    const written: { values: { property_id: number; value: unknown }[] }[] = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request }) => {
        const body = (await request.json()) as (typeof written)[number];
        written.push(body);
        task.properties = [
          buildPropertySummary({
            property_id: 9,
            name: "Risk",
            type: MetadataType.text,
            value: body.values[0]?.value,
          }),
        ];
        return HttpResponse.json(task.properties);
      })
    );

    const risk = await fieldNamed(/^risk$/i);
    // Placed, it stays when emptied, so it has nothing to take it off the task.
    expect(within(risk).queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
    await userEvent.type(within(risk).getByRole("textbox"), "High");
    await userEvent.tab();

    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toEqual({ values: [{ property_id: 9, value: "High" }], merge: true });
    // All properties leaves out the one placed on its own.
    await waitFor(() => expect(screen.getAllByRole("group", { name: /^risk$/i })).toHaveLength(1));

    // Held, it can be cleared, staying on the page.
    await userEvent.click(within(risk).getByRole("button", { name: /^clear$/i }));
    await waitFor(() => expect(written).toHaveLength(2));
    expect(written[1]).toEqual({ values: [{ property_id: 9, value: null }], merge: true });
  });

  it("says when a placed property could not be loaded, and loads it again", async () => {
    let fail = true;
    server.use(
      communityHttp.get("/property-definitions/", () =>
        fail
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json([
              buildPropertyDefinition({ id: 9, name: "Risk", type: MetadataType.text }),
            ])
      ),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "task",
                task_type_id: 1,
                task_type_name: "Task",
                updated_at: "2026-10-01T12:00:00.000Z",
                definition: { side: [{ type: "field", props: { field: "property:9" } }] },
              },
            ],
          })
        )
      )
    );
    renderTaskPage();

    expect(await screen.findByText(/couldn't load this value/i)).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await fieldNamed(/^risk$/i)).toBeInTheDocument();
  });

  it("reports duplicate progress on the trigger once the menu closes", async () => {
    renderTaskPage();
    server.use(
      communityHttp.post("/tasks/:taskId/duplicate", async () => {
        await delay("infinite");
        return new HttpResponse(null, { status: 204 });
      })
    );

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /duplicate task/i }));

    // Selecting the item dismisses the menu holding the "Duplicating…" label,
    // and duplicate opens no dialog — so the trigger has to carry the state.
    const trigger = await screen.findByRole("button", { name: /more actions/i });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-busy", "true"));
  });

  it("still names a status the project has since dropped", async () => {
    // The select is the only place the status is stated, so it has to resolve
    // a column the project no longer lists.
    renderTaskPage({ statuses: [] });

    // Radix echoes the trigger's value into a hidden native select, so the
    // name legitimately appears more than once; the placeholder is the tell.
    expect(await screen.findAllByText("To Do")).not.toHaveLength(0);
    expect(screen.queryByText(/select status/i)).not.toBeInTheDocument();
  });

  it("opens the move dialog from the actions menu, offering live projects", async () => {
    listed.length = 0;
    renderTaskPage();

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /move to project/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    // A template takes no tasks moved into it, so the destinations leave
    // templates out.
    const destinations = listed.find((params) => params.get("writable") === "true");
    expect(destinations?.get("is_template")).toBe("false");
  });

  it.each([
    [false, "Elsewhere"],
    [true, "Nearby"],
  ])(
    "offers other initiatives' projects only while content may leave (kept in: %s)",
    async (keepContentIn, offered) => {
      renderTaskPage({
        keepContentIn,
        destinations: [
          buildProject({ id: PROJECT_ID + 1, initiative_id: INITIATIVE_ID + 1, name: "Elsewhere" }),
          buildProject({ id: PROJECT_ID + 2, initiative_id: INITIATIVE_ID, name: "Nearby" }),
        ],
      });

      await openActionsMenu();
      await userEvent.click(await screen.findByRole("menuitem", { name: /move to project/i }));

      // The dialog picks the first destination it offers.
      expect(
        await within(await screen.findByRole("dialog")).findByText(offered)
      ).toBeInTheDocument();
    }
  );

  it("returns to the task's project after deleting it", async () => {
    const { router, deleted } = renderTaskPage();

    await deleteTheTask();

    await waitFor(() => expect(deleted).toHaveBeenCalled());
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/c/${COMMUNITY_ID}/i/${INITIATIVE_ID}/projects/${PROJECT_ID}`
      )
    );
  });

  it("asks which tasks of a repeating series a delete is for", async () => {
    const { router, deleted } = renderTaskPage({ recurrence: "RRULE:FREQ=DAILY" });

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete task/i }));
    expect(await screen.findByLabelText(/all tasks in the series \(3\)/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^delete$/i }));

    // Just this one skips it, so the series and the page stay.
    await waitFor(() => expect(deleted).toHaveBeenCalledWith("this"));
    expect(router.state.location.pathname).toContain(`/tasks/${TASK_ID}`);
  });

  it("leaves the page when just this task was the series' last", async () => {
    const { router, deleted } = renderTaskPage({
      recurrence: "RRULE:FREQ=DAILY;COUNT=2",
      lastOccurrence: true,
    });

    await openActionsMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: /delete task/i }));
    await userEvent.click(await screen.findByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleted).toHaveBeenCalledWith("this"));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/c/${COMMUNITY_ID}/i/${INITIATIVE_ID}/projects/${PROJECT_ID}`
      )
    );
  });

  it("follows the task's own project, not the one left in the path", async () => {
    // Moving the open task rewrites its project without touching the URL, so
    // the path still names the project it came from.
    const MOVED_TO = PROJECT_ID + 1;
    const { router, deleted } = renderTaskPage({ taskProjectId: MOVED_TO });

    await deleteTheTask();

    await waitFor(() => expect(deleted).toHaveBeenCalled());
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/c/${COMMUNITY_ID}/i/${INITIATIVE_ID}/projects/${MOVED_TO}`
      )
    );
  });
});

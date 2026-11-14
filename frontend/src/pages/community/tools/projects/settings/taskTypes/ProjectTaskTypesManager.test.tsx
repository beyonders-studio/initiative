/**
 * The task types settings: a project's kinds of task, each renamed, added from
 * another, deleted into another, and opened in the layout editor on its page.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildProject, buildTaskType } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { TaskTypeGalleryGroup, TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { ProjectTaskTypesManager } from "./ProjectTaskTypesManager";

const PROJECT_ID = 1;
const INITIATIVE_ID = 5;

/** The four a project starts with; Task is the default. */
const buildTypes = (): TaskTypeRead[] => [
  buildTaskType({ id: 1, project_id: PROJECT_ID, name: "Task", position: 0, is_default: true }),
  buildTaskType({ id: 2, project_id: PROJECT_ID, name: "Bug", position: 1, icon: "bug" }),
  buildTaskType({ id: 3, project_id: PROJECT_ID, name: "Idea", position: 2, icon: "lightbulb" }),
  buildTaskType({ id: 4, project_id: PROJECT_ID, name: "Milestone", position: 3, icon: "flag" }),
];

/** Records the body of every request one route of the types API receives. */
/** Two of the ready-made types: one that brings a field, and one that does not. */
const GALLERY: TaskTypeGalleryGroup[] = [
  {
    key: "planning",
    name: "Planning",
    entries: [
      {
        key: "event",
        name: "Event",
        hint: "A date and a place",
        icon: "calendar-days",
        color: "#60A5FA",
        layout_preset: "dates",
        fields: [{ name: "Location", type: "text" }],
        starting_values: null,
      },
    ],
  },
  {
    key: "home",
    name: "Around the house",
    entries: [
      {
        key: "chore",
        name: "Chore",
        hint: "Every week",
        icon: "repeat",
        color: "#34D399",
        layout_preset: "repeat",
        fields: [],
        starting_values: { recurrence: "RRULE:FREQ=WEEKLY" },
      },
    ],
  },
];

const capture = (
  method: "post" | "patch" | "delete" | "put",
  path: string,
  answer: () => Response
) => {
  const bodies: Array<{ typeId?: string; body: unknown }> = [];
  server.use(
    communityHttp[method](path, async ({ params, request }) => {
      bodies.push({
        typeId: params.typeId ? String(params.typeId) : undefined,
        body: await request.json().catch(() => null),
      });
      return answer();
    })
  );
  return bodies;
};

const renderManager = ({
  types = buildTypes(),
  canManage = true,
}: {
  types?: TaskTypeRead[];
  canManage?: boolean;
} = {}) => {
  server.use(
    communityHttp.get("/projects/:projectId/task-types/", () => HttpResponse.json(types)),
    communityHttp.get("/projects/:projectId/task-types/gallery", () => HttpResponse.json(GALLERY))
  );
  const Page = () => (
    <ProjectTaskTypesManager
      projectId={PROJECT_ID}
      initiativeId={INITIATIVE_ID}
      canManage={canManage}
    />
  );
  return renderPage(Page);
};

/** The table row whose name field holds `name`. */
const rowFor = async (name: string) => {
  const nameField = await screen.findByDisplayValue(name);
  const row = nameField.closest("tr");
  if (!row) {
    throw new Error(`no row for type ${name}`);
  }
  return row;
};

describe("ProjectTaskTypesManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists the project's types in order, with the default marked", async () => {
    renderManager();

    const names = await screen.findAllByRole("textbox", { name: /^name$/i });
    expect(names.map((field) => (field as HTMLInputElement).value)).toEqual([
      "Task",
      "Bug",
      "Idea",
      "Milestone",
    ]);
    expect(screen.getByRole("checkbox", { name: /make task the default/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /make bug the default/i })).not.toBeChecked();
  });

  it("adds a type started from another", async () => {
    const creates = capture("post", "/projects/:projectId/task-types/", () =>
      HttpResponse.json(buildTaskType({ id: 5, name: "Chore" }))
    );
    renderManager();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /add type/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^name$/i), "Chore");

    await user.click(within(dialog).getByRole("combobox", { name: /start from/i }));
    await user.click(await screen.findByRole("option", { name: "Bug" }));

    await user.click(within(dialog).getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(creates).toHaveLength(1));
    expect(creates[0].body).toEqual({ name: "Chore", start_from_type_id: 2 });
  });

  it("adds a ready-made type, and places its fields on its page", async () => {
    const creates = capture("post", "/projects/:projectId/task-types/", () =>
      HttpResponse.json({
        ...buildTaskType({ id: 9, name: "Gig", layout_preset: "dates" }),
        field_ids: [7],
      })
    );
    const pages = capture("put", "/layouts/", () =>
      HttpResponse.json({ layouts: [], can_configure: true })
    );
    renderManager();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /add type/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("button", { name: /event/i }));
    // Its name is a suggestion.
    const name = within(dialog).getByLabelText(/^name$/i);
    expect(name).toHaveValue("Event");
    await user.clear(name);
    await user.type(name, "Gig");
    await user.click(within(dialog).getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(creates).toHaveLength(1));
    expect(creates[0].body).toEqual({ name: "Gig", gallery_key: "event" });
    await waitFor(() => expect(pages).toHaveLength(1));
    const page = pages[0].body as {
      kind: string;
      task_type_id: number;
      definition: { side: { children?: { props?: { field?: string } }[] }[] };
    };
    expect([page.kind, page.task_type_id]).toEqual(["task", 9]);
    expect(page.definition.side[0].children?.at(-1)?.props?.field).toBe("property:7");
  });

  it("adds a blank type, with no page of its own", async () => {
    const creates = capture("post", "/projects/:projectId/task-types/", () =>
      HttpResponse.json({ ...buildTaskType({ id: 9, name: "Errand" }), field_ids: [] })
    );
    const pages = capture("put", "/layouts/", () => HttpResponse.json({ layouts: [] }));
    renderManager();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /add type/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^name$/i), "Errand");
    await user.click(within(dialog).getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(creates).toHaveLength(1));
    expect(creates[0].body).toEqual({ name: "Errand" });
    expect(pages).toHaveLength(0);
  });

  it("says what a new task of a type starts with", async () => {
    const updates = capture("patch", "/projects/:projectId/task-types/:typeId", () =>
      HttpResponse.json(buildTaskType({ id: 2, name: "Bug" }))
    );
    renderManager();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /what a new bug starts with/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^description$/i), "Steps to see it");
    await user.click(within(dialog).getByRole("button", { name: /add a line/i }));
    await user.type(within(dialog).getByLabelText(/checklist line 1/i), "Screenshot");
    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0]).toEqual({
      typeId: "2",
      body: {
        starting_values: {
          description: "Steps to see it",
          checklist: ["Screenshot"],
          priority: null,
          recurrence: null,
          recurrence_strategy: null,
        },
      },
    });
  });

  it("clears what a type starts with once nothing is left", async () => {
    const updates = capture("patch", "/projects/:projectId/task-types/:typeId", () =>
      HttpResponse.json(buildTaskType({ id: 2, name: "Bug" }))
    );
    const types = buildTypes();
    types[1] = { ...types[1], starting_values: { description: "Outline" } };
    renderManager({ types });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /what a new bug starts with/i }));
    const dialog = await screen.findByRole("dialog");
    await user.clear(within(dialog).getByLabelText(/^description$/i));
    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0].body).toEqual({ starting_values: null });
  });

  it("keeps an hourly repeat, which waits for a task with a due date", async () => {
    const updates = capture("patch", "/projects/:projectId/task-types/:typeId", () =>
      HttpResponse.json(buildTaskType({ id: 2, name: "Bug" }))
    );
    const types = buildTypes();
    types[1] = {
      ...types[1],
      starting_values: { recurrence: "RRULE:FREQ=HOURLY", recurrence_strategy: "rolling" },
    };
    renderManager({ types });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /what a new bug starts with/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0].body).toEqual({
      starting_values: expect.objectContaining({
        recurrence: "RRULE:FREQ=HOURLY",
        recurrence_strategy: "rolling",
      }),
    });
  });

  it("copies types from another project, leaving out the names it has", async () => {
    const garden = buildProject({ id: 7, name: "Garden", initiative_id: INITIATIVE_ID });
    const copies = capture("post", "/projects/:projectId/task-types/copy", () =>
      HttpResponse.json([buildTaskType({ id: 21, name: "Chore" })])
    );
    renderManager();
    server.use(
      communityHttp.get("/projects/", () =>
        HttpResponse.json({ items: [garden], total_count: 1, has_next: false })
      ),
      communityHttp.get("/projects/:projectId/task-types/", ({ params }) =>
        HttpResponse.json(
          params.projectId === "7"
            ? [
                buildTaskType({ id: 11, project_id: 7, name: "task", position: 0 }),
                buildTaskType({ id: 12, project_id: 7, name: "Chore", position: 1 }),
              ]
            : buildTypes()
        )
      )
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /copy from a project/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("combobox", { name: /project/i }));
    await user.click(await screen.findByRole("option", { name: "Garden" }));

    // Task is here already, whatever its case; Chore is chosen.
    expect(await within(dialog).findByRole("checkbox", { name: /chore/i })).toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: /task/i })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: /copy 1 type/i }));

    await waitFor(() => expect(copies).toHaveLength(1));
    expect(copies[0].body).toEqual({ source_project_id: 7, type_ids: [12] });
  });

  it("refuses a name the project already has, whatever its case", async () => {
    renderManager();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /add type/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^name$/i), "bug");

    expect(within(dialog).getByText(/already has a type with that name/i)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /^add$/i })).toBeDisabled();
  });

  it("renames a type when its changes are saved", async () => {
    const updates = capture("patch", "/projects/:projectId/task-types/:typeId", () =>
      HttpResponse.json(buildTaskType({ id: 3, name: "Proposal" }))
    );
    renderManager();
    const user = userEvent.setup();

    const field = await screen.findByDisplayValue("Idea");
    await user.clear(field);
    await user.type(field, "Proposal");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0]).toEqual({ typeId: "3", body: { name: "Proposal" } });
  });

  it("keeps a name not yet saved when the list refreshes", async () => {
    let types = buildTypes();
    server.use(
      communityHttp.patch("/projects/:projectId/task-types/:typeId", ({ params }) => {
        types = types.map((type) => ({ ...type, is_default: type.id === Number(params.typeId) }));
        return HttpResponse.json(types.find((type) => type.id === Number(params.typeId)));
      })
    );
    const { queryClient } = renderManager();
    server.use(
      communityHttp.get("/projects/:projectId/task-types/", () => HttpResponse.json(types))
    );
    const user = userEvent.setup();

    const field = await screen.findByDisplayValue("Idea");
    await user.clear(field);
    await user.type(field, "Proposal");
    await user.click(screen.getByRole("checkbox", { name: /make bug the default/i }));
    // The list reads anew once the change is saved, as the app's client does.
    await waitFor(() => expect(types[1].is_default).toBe(true));
    await queryClient.invalidateQueries();

    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: /make bug the default/i })).toBeChecked()
    );
    expect(screen.getByDisplayValue("Proposal")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Idea")).not.toBeInTheDocument();
  });

  it("moves a deleted type's tasks to the type the reader picks", async () => {
    const deletes = capture(
      "delete",
      "/projects/:projectId/task-types/:typeId",
      () => new HttpResponse(null, { status: 204 })
    );
    renderManager();
    const user = userEvent.setup();

    await user.click(within(await rowFor("Bug")).getByRole("button", { name: /delete bug/i }));
    const fallback = await screen.findByRole("combobox", { name: /move its tasks to/i });
    // The project's default catches them unless the reader says otherwise.
    expect(fallback).toHaveTextContent("Task");
    await user.click(fallback);
    expect(screen.queryByRole("option", { name: "Bug" })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: "Milestone" }));
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0]).toEqual({ typeId: "2", body: { fallback_type_id: 4 } });
  });

  it("offers the first other type when the default is the one deleted", async () => {
    const deletes = capture(
      "delete",
      "/projects/:projectId/task-types/:typeId",
      () => new HttpResponse(null, { status: 204 })
    );
    renderManager();
    const user = userEvent.setup();

    await user.click(within(await rowFor("Task")).getByRole("button", { name: /delete task/i }));
    expect(await screen.findByRole("combobox", { name: /move its tasks to/i })).toHaveTextContent(
      "Bug"
    );
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0].body).toEqual({ fallback_type_id: 2 });
  });

  it("refuses a project's only type, and says why", async () => {
    const deletes = capture(
      "delete",
      "/projects/:projectId/task-types/:typeId",
      () => new HttpResponse(null, { status: 204 })
    );
    renderManager({
      types: [buildTaskType({ id: 9, name: "Everything", position: 0, is_default: true })],
    });
    const user = userEvent.setup();

    await user.click(
      within(await rowFor("Everything")).getByRole("button", { name: /delete everything/i })
    );

    expect(await screen.findByText(/only type/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^delete$/i })).toBeDisabled();
    expect(deletes).toHaveLength(0);
  });

  it("opens the layout editor on a type's page", async () => {
    renderManager();

    const link = await screen.findByRole("link", { name: /edit the page for bug/i });
    const href = decodeURIComponent(link.getAttribute("href") ?? "");
    expect(href).toContain(`/i/${INITIATIVE_ID}/projects/${PROJECT_ID}/layouts?`);
    expect(new URLSearchParams(href.split("?")[1]).get("layout")).toBe("task:2");
  });

  it("is read-only for someone who cannot edit the project", async () => {
    renderManager({ canManage: false });

    expect(await screen.findByText(/only people who can edit this project/i)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Bug")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /add type/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete bug/i })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /make bug the default/i })).toBeDisabled();
  });
});

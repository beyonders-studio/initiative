/**
 * Taking a task without opening it: the table's assignees column offers it on
 * a task nobody is on, and a board's card offers it in the menu beside its
 * title.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildTask,
  buildTaskAssignee,
  buildTaskListResponse,
  buildToolLayoutSet,
  buildUser,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";

const STATUSES = buildDefaultTaskStatuses(1);
const ME = buildUser({ id: 7 });
const ALEX = buildTaskAssignee({ id: 3, display_name: "Alex" });

/** What each task PATCH asked for, less the zone every write carries. */
let patches: Array<Record<string, unknown>> = [];

const seed = (task: Partial<TaskListRead>) => {
  const seeded = buildTask({
    id: 51,
    project_id: 1,
    title: "Draw the map",
    task_status_id: STATUSES[0].id,
    task_status: STATUSES[0],
    ...task,
  });
  server.use(
    communityHttp.get("/tasks/", () => HttpResponse.json(buildTaskListResponse([seeded]))),
    communityHttp.patch("/tasks/:taskId", async ({ request }) => {
      const { tz: _tz, ...body } = (await request.json()) as Record<string, unknown>;
      patches.push(body);
      return HttpResponse.json({ ...seeded, ...body });
    })
  );
};

const project = ({ layout, canEdit = true }: { layout: "table" | "board"; canEdit?: boolean }) => {
  server.use(communityHttp.get("/layouts/", () => HttpResponse.json(buildToolLayoutSet())));
  return renderPage(
    () => (
      <ProjectTasksSection
        projectId={1}
        initiativeId={1}
        taskStatuses={STATUSES}
        canEditTaskDetails={canEdit}
        projectIsArchived={false}
        taskHref={(taskId) => `/tasks/${taskId}`}
      />
    ),
    { routerSearch: { layout }, auth: { user: ME } }
  );
};

const row = async (title: string) => {
  const cell = (await screen.findByText(title)).closest("tr");
  if (!cell) throw new Error(`no row for ${title}`);
  return within(cell);
};

beforeEach(() => {
  patches = [];
  localStorage.clear();
  // The table is virtualized, and jsdom gives every element a zero height,
  // which windows it down to no rows at all. The virtualizer sizes its
  // scroll element by its client box and each row by its offset box.
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1200);
});

describe("a table's assignees", () => {
  it("are a column of their own", async () => {
    seed({ assignees: [ALEX] });
    project({ layout: "table" });

    await waitFor(() =>
      expect(screen.queryAllByRole("columnheader").map((cell) => cell.textContent)).toContain(
        "Assignees"
      )
    );
    expect((await row("Draw the map")).getByText("Alex")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /assign .* to me/i })).not.toBeInTheDocument();
  });

  it("stack when there are several, each named on its own", async () => {
    seed({ assignees: [ALEX, buildTaskAssignee({ id: 4, display_name: "Sam" })] });
    project({ layout: "table" });

    const cell = await row("Draw the map");
    expect(cell.getByRole("list", { name: "Alex and Sam" })).toBeInTheDocument();
    expect(cell.getByRole("button", { name: "Alex" })).toBeInTheDocument();
    expect(cell.getByRole("button", { name: "Sam" })).toBeInTheDocument();
    // Only the avatars show; the names are what pointing at one says.
    expect(cell.queryByText("Alex")).not.toBeInTheDocument();
  });

  it("offer a task nobody is on to the reader", async () => {
    seed({ assignees: [] });
    project({ layout: "table" });
    const user = userEvent.setup();

    await user.click(
      (await row("Draw the map")).getByRole("button", { name: "Assign Draw the map to me" })
    );

    await waitFor(() => expect(patches).toEqual([{ add_assignee_ids: [7] }]));
  });

  it("offer nothing to a reader who cannot change the task", async () => {
    seed({ assignees: [] });
    project({ layout: "table", canEdit: false });

    await row("Draw the map");
    expect(screen.queryByRole("button", { name: /assign .* to me/i })).not.toBeInTheDocument();
  });
});

describe("a board card's menu", () => {
  const openMenu = async (user: ReturnType<typeof userEvent.setup>) =>
    user.click(await screen.findByRole("button", { name: "Actions for Draw the map" }));

  it("puts the reader on the task, leaving whoever is on it to the server", async () => {
    seed({ assignees: [ALEX] });
    project({ layout: "board" });
    const user = userEvent.setup();

    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Assign to me" }));

    await waitFor(() => expect(patches).toEqual([{ add_assignee_ids: [7] }]));
  });

  it("takes the reader off a task they are on", async () => {
    seed({ assignees: [ALEX, buildTaskAssignee({ id: 7, display_name: "Robin" })] });
    project({ layout: "board" });
    const user = userEvent.setup();

    await openMenu(user);
    await user.click(await screen.findByRole("menuitem", { name: "Unassign me" }));

    await waitFor(() => expect(patches).toEqual([{ remove_assignee_ids: [7] }]));
  });

  it("moves the task to another column from the fly-out", async () => {
    seed({ assignees: [] });
    project({ layout: "board" });
    const user = userEvent.setup();

    await openMenu(user);
    // The keyboard's way into a fly-out: a pointer would hover across to it.
    (await screen.findByRole("menuitem", { name: "Move to" })).focus();
    await user.keyboard("{ArrowRight}");
    expect(await screen.findByRole("menuitemradio", { name: "To Do" })).toBeChecked();
    screen.getByRole("menuitemradio", { name: "In Progress" }).focus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(patches).toEqual([{ task_status_id: STATUSES[1].id }]));
  });

  it("drills into the columns on a phone, and climbs back out", async () => {
    const wide = window.innerWidth;
    window.innerWidth = 500;
    try {
      seed({ assignees: [] });
      project({ layout: "board" });
      const user = userEvent.setup();

      await openMenu(user);
      await user.click(await screen.findByRole("menuitem", { name: "Move to" }));
      expect(await screen.findByRole("menuitemradio", { name: "To Do" })).toBeChecked();
      expect(screen.queryByRole("menuitem", { name: "Assign to me" })).not.toBeInTheDocument();

      await user.click(screen.getByRole("menuitem", { name: "Back" }));
      expect(await screen.findByRole("menuitem", { name: "Assign to me" })).toBeInTheDocument();

      await user.click(screen.getByRole("menuitem", { name: "Move to" }));
      await user.click(await screen.findByRole("menuitemradio", { name: "Done" }));

      await waitFor(() => expect(patches).toEqual([{ task_status_id: STATUSES[2].id }]));
    } finally {
      window.innerWidth = wide;
    }
  });

  it("is not there for a reader who cannot change the task", async () => {
    seed({ assignees: [] });
    project({ layout: "board", canEdit: false });

    expect(await screen.findByText("Draw the map")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /actions for/i })).not.toBeInTheDocument();
  });
});

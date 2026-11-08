/**
 * Deleting a status column. The fallback used to be compulsory and confined to
 * the target's own category, which is what made a retired Blocked column
 * undeletable — there was no second `todo` column to send its tasks to. These
 * cover what replaced that: any column may catch them, none need be chosen, and
 * the one thing still refused is a project's only status.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildProjectTaskStatus } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { ProjectTaskStatusesManager } from "./ProjectTaskStatusesManager";

const PROJECT_ID = 1;

/**
 * A project part-way through the migration: To Do is the default, and the
 * Blocked column it was seeded with years ago is the only other `todo`.
 */
const buildLegacyStatuses = (): TaskStatusRead[] => [
  buildProjectTaskStatus({
    id: 1,
    project_id: PROJECT_ID,
    name: "To Do",
    category: "todo",
    position: 0,
    is_default: true,
  }),
  buildProjectTaskStatus({
    id: 2,
    project_id: PROJECT_ID,
    name: "In Progress",
    category: "in_progress",
    position: 1,
    is_default: false,
  }),
  buildProjectTaskStatus({
    id: 3,
    project_id: PROJECT_ID,
    name: "Blocked",
    category: "todo",
    position: 2,
    is_default: false,
  }),
  buildProjectTaskStatus({
    id: 4,
    project_id: PROJECT_ID,
    name: "Done",
    category: "done",
    position: 3,
    is_default: false,
  }),
];

/** Records the body of every status DELETE the component sends. */
const captureDeletes = () => {
  const bodies: Array<{ statusId: string; body: unknown }> = [];
  server.use(
    communityHttp.delete(
      "/projects/:projectId/task-statuses/:statusId",
      async ({ params, request }) => {
        bodies.push({
          statusId: String(params.statusId),
          body: await request.json().catch(() => null),
        });
        return new HttpResponse(null, { status: 204 });
      }
    )
  );
  return bodies;
};

const renderManager = (statuses: TaskStatusRead[] = buildLegacyStatuses()) => {
  server.use(
    communityHttp.get("/projects/:projectId/task-statuses/", () => HttpResponse.json(statuses))
  );
  const Page = () => <ProjectTaskStatusesManager projectId={PROJECT_ID} canManage={true} />;
  return renderPage(Page);
};

/** Open the delete dialog for the named column. */
const openDeleteFor = async (name: string) => {
  const user = userEvent.setup();
  const nameField = await screen.findByDisplayValue(name);
  const row = nameField.closest("tr");
  if (!row) {
    throw new Error(`no row for status ${name}`);
  }
  await user.click(within(row).getByRole("button", { name: /delete/i }));
  return user;
};

describe("ProjectTaskStatusesManager delete dialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends no fallback when the reader leaves the choice to the project", async () => {
    const deletes = captureDeletes();
    renderManager();

    const user = await openDeleteFor("Blocked");
    await user.click(await screen.findByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0].statusId).toBe("3");
    expect(deletes[0].body).toEqual({ fallback_status_id: null });
  });

  it("offers every other column, not only the target's own category", async () => {
    renderManager();

    const user = await openDeleteFor("Blocked");
    await user.click(await screen.findByRole("combobox", { name: /move tasks to/i }));

    // Blocked is `todo` and has no `todo` sibling, which is exactly the case
    // the old same-category rule could not express.
    for (const name of ["In Progress", "Done", "To Do"]) {
      expect(await screen.findByRole("option", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("option", { name: "Blocked" })).not.toBeInTheDocument();
  });

  it("sends the column the reader picked, across categories", async () => {
    const deletes = captureDeletes();
    renderManager();

    const user = await openDeleteFor("Blocked");
    await user.click(await screen.findByRole("combobox", { name: /move tasks to/i }));
    await user.click(await screen.findByRole("option", { name: "In Progress" }));
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0].body).toEqual({ fallback_status_id: 2 });
  });

  it("refuses a project's only status, and says why", async () => {
    const deletes = captureDeletes();
    renderManager([
      buildProjectTaskStatus({
        id: 9,
        project_id: PROJECT_ID,
        name: "Everything",
        category: "todo",
        position: 0,
        is_default: true,
      }),
    ]);

    await openDeleteFor("Everything");

    expect(await screen.findByText(/only status/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /move tasks to/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^delete$/i })).toBeDisabled();
    expect(deletes).toHaveLength(0);
  });
});

describe("ProjectTaskStatusesManager table", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("saves a column moved to another category, with that category's look", async () => {
    const updates: unknown[] = [];
    server.use(
      communityHttp.patch("/projects/:projectId/task-statuses/:statusId", async ({ request }) => {
        updates.push(await request.json());
        return HttpResponse.json(buildProjectTaskStatus({ id: 3, project_id: PROJECT_ID }));
      })
    );
    const statuses = buildLegacyStatuses();
    // Blocked still wears the To Do look, so it takes In Progress's.
    statuses[2] = { ...statuses[2], color: "#94A3B8", icon: "circle" };
    renderManager(statuses);
    const user = userEvent.setup();

    const row = (await screen.findByDisplayValue("Blocked")).closest("tr");
    if (!row) {
      throw new Error("no row for status Blocked");
    }
    await user.click(within(row).getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "In Progress" }));
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0]).toEqual({ category: "in_progress", color: "#60A5FA", icon: "circle-play" });
  });
});

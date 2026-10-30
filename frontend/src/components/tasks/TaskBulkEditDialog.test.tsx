import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildTagSummary,
  buildTask,
  buildTaskType,
  buildToolLayoutSet,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { Dialog } from "@/components/ui/dialog";

import { TaskBulkEditDialog } from "./TaskBulkEditDialog";

const TASK_TYPE = buildTaskType({ id: 1, name: "Task", project_id: 1, is_default: true });
const IDEA = buildTaskType({ id: 9, name: "Idea", project_id: 1, position: 1 });

/** The dialog for `tasks`, in a project whose Idea page requires tags, or
 *  whose type pages can't be read (`unreadable`). */
const open = (tasks: TaskListRead[], types = [TASK_TYPE, IDEA], { unreadable = false } = {}) => {
  const layoutReads = { failed: 0 };
  server.use(
    communityHttp.get("/layouts/", () => {
      if (unreadable) {
        layoutReads.failed += 1;
        return new HttpResponse(null, { status: 500 });
      }
      return HttpResponse.json(
        buildToolLayoutSet({
          layouts: [
            {
              kind: "task",
              task_type_id: IDEA.id,
              task_type_name: IDEA.name,
              updated_at: "2026-10-01T12:00:00.000Z",
              definition: {
                side: [{ type: "field", props: { field: "tags", required: true } }],
              },
            },
          ],
        })
      );
    })
  );
  const onApply = vi.fn();
  renderWithProviders(
    <Dialog open>
      <TaskBulkEditDialog
        selectedTasks={tasks}
        taskStatuses={buildDefaultTaskStatuses(1)}
        taskTypes={types}
        projectId={1}
        initiativeId={1}
        isSubmitting={false}
        onApply={onApply}
        onCancel={() => {}}
      />
    </Dialog>
  );
  return { onApply, layoutReads, user: userEvent.setup() };
};

/** Opens Details and the type picker, once the type pages are read. */
const openTypes = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: "Details" }));
  const picker = screen.getByRole("combobox", { name: "Type" });
  await waitFor(() => expect(picker).toBeEnabled());
  await user.click(picker);
};

const tagged = () =>
  buildTask({ project_id: 1, task_type_id: TASK_TYPE.id, tags: [buildTagSummary()] });

describe("TaskBulkEditDialog's type", () => {
  it("gives every selected task the type picked", async () => {
    const { onApply, user } = open([tagged(), tagged()]);

    await openTypes(user);
    await user.click(await screen.findByRole("option", { name: "Idea" }));
    await user.click(screen.getByRole("button", { name: "Apply changes" }));

    expect(onApply).toHaveBeenCalledWith({ task_type_id: IDEA.id });
  });

  it("doesn't offer a type whose page requires what a selected task leaves empty", async () => {
    const bare = buildTask({ project_id: 1, task_type_id: TASK_TYPE.id, tags: [] });
    // One already an Idea is not changed, so it isn't counted.
    const idea = buildTask({ project_id: 1, task_type_id: IDEA.id, tags: [] });
    const { user } = open([tagged(), bare, idea]);

    await openTypes(user);

    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "Idea requires fields 1 task leaves empty" })
      ).toHaveAttribute("aria-disabled", "true")
    );
    expect(screen.getByRole("option", { name: "Task" })).not.toHaveAttribute(
      "aria-disabled",
      "true"
    );
  });

  it("can be left unchanged again once picked", async () => {
    const { onApply, user } = open([tagged()]);

    await openTypes(user);
    await user.click(await screen.findByRole("option", { name: "Idea" }));
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(await screen.findByRole("option", { name: "Leave unchanged" }));

    expect(screen.getByRole("combobox", { name: "Type" })).toHaveTextContent("Select type");
    expect(screen.getByRole("button", { name: "Apply changes" })).toBeDisabled();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("can't be picked while the type pages can't be read", async () => {
    const { layoutReads, user } = open([tagged()], undefined, { unreadable: true });

    await user.click(screen.getByRole("button", { name: "Details" }));
    await waitFor(() => expect(layoutReads.failed).toBeGreaterThan(0));

    expect(screen.getByRole("combobox", { name: "Type" })).toBeDisabled();
    // Everything else can still be changed.
    expect(screen.getByRole("combobox", { name: "Status" })).toBeEnabled();
  });

  it("isn't asked in a project of one type", async () => {
    const { user } = open([tagged()], [TASK_TYPE]);

    await user.click(screen.getByRole("button", { name: "Details" }));

    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Type" })).not.toBeInTheDocument();
  });
});

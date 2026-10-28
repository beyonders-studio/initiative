import type { DragEndEvent } from "@dnd-kit/core";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildTag,
  buildTask,
  buildTaskType,
  buildToolLayoutSet,
  TASK_GROUPINGS,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { ProjectTasksKanbanView } from "./ProjectTasksKanbanView";

const drag = vi.hoisted(() => ({
  finish: (event: DragEndEvent) => {
    void event;
  },
}));
vi.mock("@dnd-kit/core", async (importOriginal) => {
  const original = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...original,
    DndContext: ({ children, onDragEnd }: React.ComponentProps<typeof original.DndContext>) => {
      drag.finish = (event) => onDragEnd?.(event);
      return <div>{children}</div>;
    },
  };
});

const [TODO, DOING] = buildDefaultTaskStatuses(1);
const TASK = buildTask({ id: 51, project_id: 1, title: "Draw the map", task_status_id: TODO.id });

/** The card dropped into the Idea band of the Doing column. */
const dropIntoIdea = () =>
  act(() =>
    drag.finish({
      active: {
        id: "51",
        data: { current: { type: "task", taskId: 51, group: "1", statusId: TODO.id } },
        rect: { current: { initial: null, translated: null } },
      },
      over: {
        id: `column-${DOING.id}-9`,
        data: { current: { type: "column", statusId: DOING.id, group: "9" } },
        rect: { top: 0, left: 0, width: 100, height: 100, bottom: 100, right: 100 },
        disabled: false,
      },
      collisions: null,
      delta: { x: 0, y: 0 },
      activatorEvent: null,
    } as unknown as DragEndEvent)
  );

describe("a board grouped by type", () => {
  it("asks for what a type's page requires before a drop into it saves anything", async () => {
    const patched: Record<string, unknown>[] = [];
    server.use(
      http.get("/api/v1/fields/tasks", () =>
        HttpResponse.json({
          dataset: "tasks",
          fields: [],
          relations: [],
          default_filters: [],
          groupings: [
            ...TASK_GROUPINGS,
            { name: "task_type_id", kind: "task_type", bucket: false },
          ],
        })
      ),
      communityHttp.get("/projects/:id/task-types/", () =>
        HttpResponse.json([
          buildTaskType({ id: 1, name: "Task", project_id: 1, is_default: true }),
          buildTaskType({ id: 9, name: "Idea", project_id: 1, position: 1 }),
        ])
      ),
      communityHttp.get("/tasks/groups", () =>
        HttpResponse.json({
          groups: [
            { key: "1", label: "Task" },
            { key: "9", label: "Idea" },
          ],
          rows: { "51": ["1"] },
        })
      ),
      communityHttp.get("/tasks/:taskId", () => HttpResponse.json(TASK)),
      communityHttp.get("/tags/", () => HttpResponse.json([buildTag({ id: 7, name: "Maps" })])),
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            layouts: [
              {
                kind: "task",
                task_type_id: 9,
                task_type_name: "Idea",
                updated_at: "2026-10-01T12:00:00.000Z",
                definition: {
                  side: [{ type: "field", props: { field: "tags", required: true } }],
                },
              },
            ],
          })
        )
      ),
      communityHttp.patch("/tasks/:taskId", async ({ request }) => {
        patched.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(TASK);
      })
    );
    const onDragEnd = vi.fn();
    const onDragCancel = vi.fn();
    renderPage(() => (
      <ProjectTasksKanbanView
        projectId={1}
        initiativeId={1}
        taskStatuses={[TODO, DOING]}
        groupedTasks={{ [TODO.id]: [TASK] }}
        listParams={{ conditions: [] }}
        collapsedStatusIds={new Set()}
        canReorderTasks
        canEditTasks
        taskHref={(taskId) => `/tasks/${taskId}`}
        sensors={[]}
        activeTask={null}
        onDragStart={() => {}}
        onDragOver={() => {}}
        onDragEnd={onDragEnd}
        onDragCancel={onDragCancel}
        onToggleCollapse={() => {}}
        grouping={["task_type_id group"]}
      />
    ));
    const user = userEvent.setup();
    expect(await screen.findByText("Idea")).toBeInTheDocument();

    // Left unanswered, the drop changes nothing.
    dropIntoIdea();
    let asking = await screen.findByRole("dialog", { name: "What the Idea page asks for" });
    expect(onDragCancel).toHaveBeenCalled();
    await user.click(within(asking).getByRole("button", { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(patched).toEqual([]);
    expect(onDragEnd).not.toHaveBeenCalled();

    // Answered, the type, the column and the tag go together, then its place.
    dropIntoIdea();
    asking = await screen.findByRole("dialog", { name: "What the Idea page asks for" });
    await user.click(within(asking).getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Maps" }));
    await user.click(within(asking).getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(patched).toEqual([{ task_type_id: 9, task_status_id: DOING.id, tag_ids: [7] }])
    );
    await waitFor(() => expect(onDragEnd).toHaveBeenCalledTimes(1));
  });
});

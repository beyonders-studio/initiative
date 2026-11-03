import type { DragEndEvent, DragOverEvent } from "@dnd-kit/core";
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
  over: (event: DragOverEvent) => {
    void event;
  },
  finish: (event: DragEndEvent) => {
    void event;
  },
}));
vi.mock("@dnd-kit/core", async (importOriginal) => {
  const original = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...original,
    DndContext: ({
      children,
      onDragOver,
      onDragEnd,
    }: React.ComponentProps<typeof original.DndContext>) => {
      drag.over = (event) => onDragOver?.(event);
      drag.finish = (event) => onDragEnd?.(event);
      return <div>{children}</div>;
    },
  };
});

const [TODO, DOING] = buildDefaultTaskStatuses(1);
const TASK = buildTask({ id: 51, project_id: 1, title: "Draw the map", task_status_id: TODO.id });

const CARD = {
  id: "51",
  data: { current: { type: "task", taskId: 51, group: "1", statusId: TODO.id } },
  rect: { current: { initial: null, translated: null } },
};
/** The Idea band of the Doing column. */
const IDEA_DOING = {
  id: `column-${DOING.id}-9`,
  data: { current: { type: "column", statusId: DOING.id, group: "9" } },
  rect: { top: 0, left: 0, width: 100, height: 100, bottom: 100, right: 100 },
  disabled: false,
};

/** The card dropped into the Idea band of the Doing column: released over
 *  it, or `passing` over it and released over nothing. */
const dropIntoIdea = ({ passing = false } = {}) =>
  act(() => {
    const moving = { active: CARD, delta: { x: 0, y: 0 }, activatorEvent: null };
    if (passing) {
      drag.over({ ...moving, over: IDEA_DOING, collisions: null } as unknown as DragOverEvent);
    }
    drag.finish({
      ...moving,
      over: passing ? null : IDEA_DOING,
      collisions: null,
    } as unknown as DragEndEvent);
  });

describe("a board grouped by type", () => {
  /** The board, grouped by type, whose Idea page requires tags: what it
   *  saved, and what it told the page holding it. */
  const board = async () => {
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
    expect(await screen.findByText("Idea")).toBeInTheDocument();
    return { patched, onDragEnd, onDragCancel, user: userEvent.setup() };
  };

  /** Picks the tag Maps in the question, and goes on with the drop. */
  const answer = async (user: ReturnType<typeof userEvent.setup>) => {
    const asking = await screen.findByRole("dialog", { name: "What the Idea page asks for" });
    await user.click(within(asking).getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Maps" }));
    await user.click(within(asking).getByRole("button", { name: "Continue" }));
  };

  it("asks for what a type's page requires before a drop into it saves anything", async () => {
    const { patched, onDragEnd, onDragCancel, user } = await board();

    // Left unanswered, the drop changes nothing.
    dropIntoIdea();
    const asking = await screen.findByRole("dialog", { name: "What the Idea page asks for" });
    expect(onDragCancel).toHaveBeenCalled();
    await user.click(within(asking).getByRole("button", { name: /close/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(patched).toEqual([]);
    expect(onDragEnd).not.toHaveBeenCalled();

    // Answered, the type, the column and the tag go together, then its place.
    dropIntoIdea();
    await answer(user);

    await waitFor(() =>
      expect(patched).toEqual([{ task_type_id: 9, task_status_id: DOING.id, tag_ids: [7] }])
    );
    await waitFor(() => expect(onDragEnd).toHaveBeenCalledTimes(1));
  });

  it("places a card released over nothing where it was last over, once answered", async () => {
    const { patched, onDragEnd, onDragCancel, user } = await board();

    dropIntoIdea({ passing: true });
    await answer(user);

    await waitFor(() =>
      expect(patched).toEqual([{ task_type_id: 9, task_status_id: DOING.id, tag_ids: [7] }])
    );
    expect(onDragCancel).toHaveBeenCalled();
    await waitFor(() => expect(onDragEnd).toHaveBeenCalledTimes(1));
    // The page places it from the drop it is handed, which still says where.
    expect(onDragEnd.mock.calls[0][0].over?.id).toBe(IDEA_DOING.id);
  });
});

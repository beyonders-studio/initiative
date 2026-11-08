/**
 * A project's tasks on a time axis. What a drag writes, what a drag across an
 * empty track gives a task with no dates, which dependencies are drawn late,
 * the link a drag from one bar to another row makes, what the keyboard moves,
 * and that only the rows in view are drawn.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildDefaultTaskStatuses, buildTask } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { layOutVirtualList } from "@/__tests__/helpers/layOutVirtualList";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { LinkedTaskRead, TaskEdgeRead } from "@/api/generated/initiativeAPI.schemas";
import { DAY, PX_PER_DAY } from "@/lib/gantt";

import { ProjectTasksGanttView } from "./ProjectTasksGanttView";

layOutVirtualList((element) => element.dataset.testid === "gantt", {
  height: 600,
  rowHeight: 32,
});

const at = (iso: string) => new Date(`${iso}T09:00:00`).toISOString();

/** `source` waits on `target`. */
const waits = (source_id: number, target_id: number, id = source_id * 1000 + target_id) =>
  ({ id, source_id, target_id, relationship_type: "depends_on" }) as TaskEdgeRead;

const mount = (
  tasks: ReturnType<typeof buildTask>[],
  edges: TaskEdgeRead[] = [],
  onReschedule = vi.fn(async (_task: unknown, _dates: unknown) => true),
  others: LinkedTaskRead[] = []
) => {
  server.use(communityHttp.get("/relationships/tasks", () => HttpResponse.json({ edges, others })));
  const view = renderPage(
    () => (
      <ProjectTasksGanttView
        initiativeId={1}
        projectId={1}
        tasks={tasks}
        taskStatuses={buildDefaultTaskStatuses(1)}
        scale="week"
        grouping={[]}
        taskHref={(id) => `/tasks/${id}`}
        onReschedule={onReschedule}
      />
    ),
    { initialRoute: "/c/1" }
  );
  return { ...view, onReschedule };
};

describe("ProjectTasksGanttView", () => {
  it("moves a bar's dates by the days it is dragged", async () => {
    const task = buildTask({
      title: "Design",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const { onReschedule } = mount([task]);
    const bar = await screen.findByTitle(/^Design ·/);

    fireEvent.pointerDown(bar, { button: 0, clientX: 100 });
    fireEvent.pointerMove(bar, { clientX: 100 + 2 * PX_PER_DAY.week });
    fireEvent.pointerUp(bar);

    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(1));
    const [moved, dates] = onReschedule.mock.calls[0] as unknown as [
      typeof task,
      { start_date: string; due_date: string },
    ];
    expect(moved.id).toBe(task.id);
    expect(dates).toEqual({ start_date: at("2026-03-04"), due_date: at("2026-03-06") });
  });

  it("gives a task with no dates the days dragged across its track", async () => {
    const task = buildTask({ title: "Someday", start_date: null, due_date: null });
    const { onReschedule } = mount([task]);
    const track = await screen.findByTitle("Drag across the days to give this task dates");

    // A click alone picks nothing.
    fireEvent.pointerDown(track, { button: 0, clientX: 0 });
    fireEvent.pointerUp(track);
    expect(onReschedule).not.toHaveBeenCalled();

    fireEvent.pointerDown(track, { button: 0, clientX: 0 });
    fireEvent.pointerMove(track, { clientX: 3 * PX_PER_DAY.week });
    fireEvent.pointerUp(track);
    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(1));
    const [, dates] = onReschedule.mock.calls[0] as unknown as [
      unknown,
      { start_date: string; due_date: string },
    ];
    expect(Math.round((Date.parse(dates.due_date) - Date.parse(dates.start_date)) / DAY)).toBe(3);
  });

  it("draws a dependency late where the task starts before what it waits on ends", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const after = buildTask({
      title: "After",
      start_date: at("2026-03-06"),
      due_date: at("2026-03-07"),
    });
    const early = buildTask({
      title: "Early",
      start_date: at("2026-03-03"),
      due_date: at("2026-03-05"),
    });
    const { container } = mount(
      [first, after, early],
      [waits(after.id, first.id), waits(early.id, first.id)]
    );

    await waitFor(() => expect(container.querySelectorAll("path[marker-end]")).toHaveLength(2));
    const late = [...container.querySelectorAll("path[marker-end]")].map((path) =>
      path.classList.contains("stroke-destructive")
    );
    expect(late).toEqual([false, true]);
  });

  it("makes the task a link is dragged onto wait on, or part of, the one it starts from", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const next = buildTask({
      title: "Next",
      start_date: at("2026-03-05"),
      due_date: at("2026-03-06"),
    });
    const sent = vi.fn();
    server.use(
      communityHttp.post("/relationships/", async ({ request }) => {
        sent(await request.json());
        return HttpResponse.json({}, { status: 201 });
      })
    );
    mount([first, next]);
    await screen.findByTitle(/^First ·/);
    const [fromFirst] = screen.getAllByTestId("gantt-link");

    fireEvent.pointerDown(fromFirst, { button: 0, clientX: 0, clientY: 16 });
    // Onto the second row, which is a row's height down.
    fireEvent.pointerMove(fromFirst, { clientX: 40, clientY: 48 });
    fireEvent.pointerUp(fromFirst, { clientX: 40, clientY: 48 });

    expect(await screen.findByText("How is “Next” linked to “First”?")).toBeVisible();
    expect(screen.getByRole("menuitem", { name: /^Blocked by it/ })).toBeVisible();
    fireEvent.click(screen.getByRole("menuitem", { name: /^Part of it/ }));
    await waitFor(() =>
      expect(sent).toHaveBeenCalledWith({
        source: { type: "task", id: next.id },
        relationship_type: "part_of",
        target: { type: "task", id: first.id },
      })
    );
  });

  it("moves between rows with the arrows, and a task's dates with Alt", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const second = buildTask({
      title: "Second",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const { onReschedule } = mount([first, second]);
    const rows = await screen.findAllByRole("row");
    expect(rows.map((row) => row.tabIndex)).toEqual([0, -1]);

    rows[0].focus();
    fireEvent.keyDown(rows[0], { key: "ArrowDown" });
    await waitFor(() => expect(screen.getAllByRole("row")[1]).toHaveFocus());

    // Two presses are one move of two days, saved once they stop.
    const focused = screen.getAllByRole("row")[1];
    fireEvent.keyDown(focused, { key: "ArrowRight", altKey: true });
    fireEvent.keyDown(focused, { key: "ArrowRight", altKey: true });
    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(1));
    const [moved, dates] = onReschedule.mock.calls[0] as unknown as [
      typeof second,
      { start_date: string; due_date: string },
    ];
    expect(moved.id).toBe(second.id);
    expect(dates).toEqual({ start_date: at("2026-03-04"), due_date: at("2026-03-06") });

    // With Shift as well, only the due date.
    fireEvent.keyDown(focused, { key: "ArrowLeft", altKey: true, shiftKey: true });
    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(2));
    expect((onReschedule.mock.calls[1] as unknown as [unknown, unknown])[1]).toEqual({
      due_date: at("2026-03-03"),
    });

    // A move not yet saved is saved before Enter opens the task.
    fireEvent.keyDown(focused, { key: "ArrowRight", altKey: true });
    fireEvent.keyDown(focused, { key: "Enter" });
    expect(onReschedule).toHaveBeenCalledTimes(3);
    expect(onReschedule.mock.calls[2]).toEqual([
      expect.objectContaining({ id: second.id }),
      { start_date: at("2026-03-03"), due_date: at("2026-03-05") },
    ]);
  });

  it("draws only the rows in view", async () => {
    const tasks = Array.from({ length: 300 }, (_, index) =>
      buildTask({ title: `Task ${index}`, start_date: null, due_date: null })
    );
    mount(tasks);
    await screen.findByText("Task 0");
    expect(screen.getAllByRole("row").length).toBeLessThan(50);
    expect(screen.getByRole("treegrid")).toHaveAttribute("aria-rowcount", "300");
  });

  it("takes a link back from its arrow", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const after = buildTask({
      title: "After",
      start_date: at("2026-03-06"),
      due_date: at("2026-03-07"),
    });
    const removed = vi.fn();
    server.use(
      communityHttp.delete("/relationships/:id", ({ params }) => {
        removed(Number(params.id));
        return new HttpResponse(null, { status: 204 });
      })
    );
    mount([first, after], [waits(after.id, first.id, 7)]);

    fireEvent.click(await screen.findByTestId("gantt-arrow"));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Remove the link: After waits on First" })
    );
    await waitFor(() => expect(removed).toHaveBeenCalledWith(7));
  });

  it("moves what waits on a task by as many days, filtered out or not, when asked to", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const after = buildTask({
      title: "After",
      start_date: at("2026-03-06"),
      due_date: at("2026-03-07"),
    });
    const last = buildTask({
      title: "Last",
      start_date: at("2026-03-09"),
      due_date: at("2026-03-10"),
    });
    // The task in the middle of the chain is one the filters hide.
    server.use(communityHttp.get("/tasks/:id", () => HttpResponse.json(after)));
    const { onReschedule } = mount(
      [first, last],
      [waits(after.id, first.id), waits(last.id, after.id)]
    );
    const bar = await screen.findByTitle(/^First ·/);

    fireEvent.pointerDown(bar, { button: 0, clientX: 100 });
    fireEvent.pointerMove(bar, { clientX: 100 + 2 * PX_PER_DAY.week });
    fireEvent.pointerUp(bar);
    expect(
      await screen.findByText("2 tasks wait on “First”. Move them later by as many days?")
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Move as well" }));

    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(3));
    const moved = onReschedule.mock.calls.map((call) => {
      const [task, dates] = call as unknown as [{ id: number }, { start_date: string }];
      return [task.id, dates.start_date];
    });
    expect(moved).toEqual([
      [first.id, at("2026-03-04")],
      [after.id, at("2026-03-08")],
      [last.id, at("2026-03-11")],
    ]);
  });

  it("offers nothing to move when the task's own move is not saved", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const after = buildTask({
      title: "After",
      start_date: at("2026-03-06"),
      due_date: at("2026-03-07"),
    });
    const refused = vi.fn(async (_task: unknown, _dates: unknown) => false);
    mount([first, after], [waits(after.id, first.id)], refused);
    const bar = await screen.findByTitle(/^First ·/);

    fireEvent.pointerDown(bar, { button: 0, clientX: 100 });
    fireEvent.pointerMove(bar, { clientX: 100 + 2 * PX_PER_DAY.week });
    fireEvent.pointerUp(bar);
    await waitFor(() => expect(refused).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/wait on “First”/)).not.toBeInTheDocument();
  });

  it("picks out the critical path, and draws other projects' linked tasks apart", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const after = buildTask({
      title: "After",
      start_date: at("2026-03-06"),
      due_date: at("2026-03-09"),
    });
    const side = buildTask({
      title: "Side",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-03"),
    });
    const theirs: LinkedTaskRead = {
      id: 99,
      title: "Their task",
      start_date: at("2026-03-01"),
      due_date: at("2026-03-02"),
      project_id: 2,
      project_name: "Other project",
      initiative_id: 1,
      done: false,
    };
    mount([first, after, side], [waits(after.id, first.id), waits(first.id, 99)], undefined, [
      theirs,
    ]);

    expect(await screen.findByText("Linked from other projects")).toBeVisible();
    expect(screen.getByRole("row", { name: /^Their task, Other project/ })).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Critical path" }));
    const track = (title: RegExp) => screen.getByTitle(title).closest('[role="gridcell"]');
    await waitFor(() => expect(track(/^Side ·/)).toHaveClass("opacity-30"));
    expect(track(/^After ·/)).not.toHaveClass("opacity-30");
  });

  it("draws a repeating task's coming occurrences on its row", async () => {
    const weekly = buildTask({
      title: "Standup",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-02"),
      recurrence: "FREQ=WEEKLY",
    });
    server.use(
      communityHttp.get("/calendar-entries/", () =>
        HttpResponse.json({
          events: [],
          tasks: [],
          task_occurrences: [
            { ...weekly, start_date: at("2026-03-09"), due_date: at("2026-03-09") },
            { ...weekly, start_date: at("2026-03-16"), due_date: at("2026-03-16") },
          ],
        })
      )
    );
    mount([weekly]);
    await waitFor(() => expect(screen.getAllByTestId("gantt-next")).toHaveLength(2));
  });
});

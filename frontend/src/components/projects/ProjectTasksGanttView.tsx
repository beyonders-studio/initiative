import { Link, useNavigate } from "@tanstack/react-router";
import type { GroupingState } from "@tanstack/react-table";
import { ChevronRight } from "lucide-react";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { useListCalendarEntries } from "@/api/generated/calendar-entries/calendar-entries";
import {
  type LayoutGrouping,
  type LinkedTaskRead,
  type ListTasksParams,
  RelationshipType,
  SearchEntityType,
  type TaskEdgeRead,
  type TaskListRead,
  type TaskStatusRead,
  type TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { useListTaskEdges } from "@/api/generated/relationships/relationships";
import { readTask } from "@/api/generated/tasks/tasks";
import { TaskTypeMark } from "@/components/tasks/TaskTypeOption";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { GroupBySelect } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useProjectTaskTypes } from "@/hooks/useProjects";
import { useOwnedDefinitions } from "@/hooks/useProperties";
import { useRelate, useUnrelate } from "@/hooks/useRelationships";
import { useTaskGroupings } from "@/hooks/useTaskGroupings";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  criticalPath,
  DAY,
  type DragHold,
  draggedAcross,
  draggedDates,
  GANTT_SCALES,
  type GanttRow,
  type GanttScale,
  type GanttSpan,
  ganttWindow,
  heldDays,
  PX_PER_DAY,
  scheduledDates,
  spanOf,
  taskRows,
  waitingOn,
  wholesOf,
} from "@/lib/gantt";
import { dateTimeFormat } from "@/lib/intl";
import { LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import { boardBands } from "@/lib/layouts/grouping";
import { taskFields } from "@/lib/layouts/tasks";
import { browserTimezone } from "@/lib/timezones";
import { taskRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";
import {
  type AxisTick,
  addUnits,
  axisTicks,
  floorToUnit,
  majorSegments,
  weekendBands,
} from "@/lib/widgets/timelineAxis";
import type { TranslateFn } from "@/types/i18n";

const LABEL_WIDTH = 260;
const ROW_HEIGHT = 32;
const HEADER_HEIGHT = 40;
const INDENT = 14;
/** How far a pointer moves before a press on a bar is a drag, not a click. */
const DRAG_SLOP = 4;
/** Where the arrow from a blocker turns before it reaches what waits on it. */
const ELBOW = 8;
/** How far past today a repeating task's coming occurrences are drawn: the
 *  most a calendar's window asks for. */
const OCCURRENCE_DAYS = 399;
/** Rows drawn past each edge of the view, so a quick scroll shows no gap. */
const OVERSCAN = 10;
/** How long a run of arrow-key moves waits before it is saved, as one write. */
const KEY_SETTLE_MS = 600;

type Dates = Pick<TaskUpdate, "start_date" | "due_date">;

/** A drag in progress: what it holds, where it began, and how many days it
 *  has gone. A task with no dates is being given some from `from`. */
type Drag = {
  key: string;
  task: TaskListRead;
  hold: DragHold;
  originX: number;
  days: number;
  moved: boolean;
  from?: number;
};

/** A link being drawn from a task's bar to another task's row: where it
 *  starts and where the pointer is, on the chart. */
type Linking = {
  task: TaskListRead;
  /** The row it is drawn from, which stays drawn while it is. */
  index: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

/** What is being asked of a link: which way to make one dropped on a row, or
 *  whether to take back one an arrow was clicked on, at the point on the
 *  chart it was done. */
type LinkMenu =
  | { kind: "drop"; from: TaskListRead; to: TaskListRead; x: number; y: number }
  | { kind: "arrow"; edge: TaskEdgeRead; x: number; y: number };

/** A move that left tasks waiting on the moved one: whether to move them too. */
type Chain = { title: string; ids: number[]; days: number };

type ProjectTasksGanttViewProps = {
  initiativeId: number;
  projectId: number;
  tasks: TaskListRead[];
  taskStatuses: TaskStatusRead[];
  /** The list the tasks are, which their groups are worked out for. */
  listParams?: ListTasksParams;
  scale: GanttScale;
  onScaleChange?: (scale: GanttScale) => void;
  grouping: GroupingState;
  onGroupingChange?: (grouping: GroupingState) => void;
  viewGroupings?: LayoutGrouping[] | null;
  taskHref: (taskId: number) => string;
  /** Writes a task's new dates; left out, the bars stay where they are. */
  onReschedule?: (task: Pick<TaskListRead, "id" | "recurrence">, dates: Dates) => Promise<boolean>;
  /** Drawn in the layout editor: nothing opens or moves. */
  editing?: boolean;
};

/**
 * A project's tasks on a time axis, each a bar from its start to its due date.
 * A task with one date is a marker on that day, and a task with none has an
 * empty track, which a drag across gives dates. A bar is dragged to move it
 * and by an end to change that date; a task depending on another is joined to
 * it by an arrow, red where it starts before the other ends, and one is drawn
 * from the dot at a bar's end to the row of the task that waits on it; and a
 * task's parts are listed under it, folded with it, the span they cover drawn
 * over its row. Grouped, each group is a band with its heading.
 *
 * The rows are a tree grid: the arrow keys move between them and fold them,
 * Enter opens a task, and Alt with an arrow moves it a day (with Shift, its
 * due date). Only the rows in view are drawn.
 *
 * Moving a task later offers to move what waits on it by as many days, and the
 * critical path picks out the chain that decides when the work ends. A
 * repeating task's coming occurrences are faded bars on its row, and another
 * project's tasks the project's are linked to are a band of their own.
 */
export const ProjectTasksGanttView = ({
  initiativeId,
  projectId,
  tasks,
  taskStatuses,
  listParams,
  scale,
  onScaleChange,
  grouping,
  onGroupingChange,
  viewGroupings,
  taskHref,
  onReschedule,
  editing = false,
}: ProjectTasksGanttViewProps) => {
  const { t, i18n } = useTranslation(["projects", "common"]);
  const { t: layoutT } = useTranslation(LAYOUT_NAMESPACES);
  const locale = i18n.language;
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();

  const { data: definitions } = useOwnedDefinitions({
    initiativeId,
    owner: { kind: "project", id: projectId },
  });
  const fields = useMemo(() => taskFields(definitions ?? []), [definitions]);
  const { offered, active } = useTaskGroupings({
    fields,
    statuses: taskStatuses,
    tasks,
    groupings: viewGroupings,
    kind: "gantt",
    grouping,
    params: listParams,
    t: layoutT as TranslateFn,
  });
  // A project with one type shows none: it tells no task apart.
  const typed = (useProjectTaskTypes(projectId).data?.length ?? 0) > 1;
  const links = useListTaskEdges(communityId, { project_id: projectId }).data;
  const edges = links?.edges;
  const gp = useCommunityPath();

  // Dates written but not yet answered for, drawn where they were dropped.
  const [pending, setPending] = useState<ReadonlyMap<number, Dates>>(new Map());
  const shown = useMemo(
    () =>
      pending.size === 0
        ? tasks
        : tasks.map((task) => {
            const dates = pending.get(task.id);
            return dates ? { ...task, ...dates } : task;
          }),
    [tasks, pending]
  );

  const [folded, setFolded] = useState<ReadonlySet<string>>(new Set());
  const outsideLabel = t("tasks.ganttOutside");
  const rows = useMemo<GanttRow[]>(() => {
    const wholes = wholesOf(shown, edges ?? []);
    const byId = new Map(shown.map((task) => [task.id, task]));
    const own = active
      ? boardBands(active, tasks).flatMap((band): GanttRow[] => {
          const held = band.tasks.map((task) => byId.get(task.id) ?? task);
          return [
            { type: "group", key: band.key, count: held.length },
            ...taskRows(held, wholes, folded, `${band.key}:`),
          ];
        })
      : taskRows(shown, wholes, folded);
    const others = links?.others ?? [];
    if (others.length === 0) return own;
    return [
      ...own,
      { type: "group", key: "outside", count: others.length, label: outsideLabel },
      ...others.map((task): GanttRow => ({ type: "outside", key: `outside:${task.id}`, task })),
    ];
  }, [shown, tasks, edges, links, folded, active, outsideLabel]);

  const now = useMemo(() => Date.now(), []);
  const pxPerDay = PX_PER_DAY[scale];
  const range = useMemo(
    () =>
      ganttWindow(
        // Other projects' linked tasks are drawn on the same axis.
        [...shown, ...(links?.others ?? [])].flatMap((task) => spanOf(task) ?? []),
        scale,
        now
      ),
    [shown, links, scale, now]
  );
  const width = Math.round(((range.end - range.start) / DAY) * pxPerDay);
  const x = useCallback(
    (at: number) => ((at - range.start) / DAY) * pxPerDay,
    [range.start, pxPerDay]
  );
  const ticks = useMemo(() => axisTicks(range, scale, 0, Number.POSITIVE_INFINITY), [range, scale]);
  const major = useMemo(() => majorSegments(range, scale), [range, scale]);
  const weekends = useMemo(() => (scale === "month" ? [] : weekendBands(range)), [range, scale]);

  // A repeating task's coming occurrences, as the calendars draw them.
  const repeating = tasks.some((task) => task.recurrence && task.due_date);
  const upcoming = useMemo(() => {
    const from = Math.max(range.start, floorToUnit(now, "day"));
    const to = Math.min(range.end, addUnits(from, "day", OCCURRENCE_DAYS));
    return { start_after: new Date(from).toISOString(), start_before: new Date(to).toISOString() };
  }, [range, now]);
  const occurrences = useListCalendarEntries(
    communityId,
    {
      initiative_id: initiativeId,
      include_events: false,
      conditions: listParams?.conditions,
      tz: browserTimezone(),
      ...upcoming,
    },
    { query: { enabled: repeating && !editing } }
  ).data?.task_occurrences;
  const nextOf = useMemo(() => {
    const found = new Map<number, GanttSpan[]>();
    for (const occurrence of occurrences ?? []) {
      const span = spanOf(occurrence);
      if (span) found.set(occurrence.id, [...(found.get(occurrence.id) ?? []), span]);
    }
    return found;
  }, [occurrences]);

  // Opens on today, a third of the way in, and again on another scale. When
  // the window widens (tasks load, a filter changes) the dates in view stay.
  const scroller = useRef<HTMLDivElement>(null);
  const scrollToToday = useCallback(() => {
    const element = scroller.current;
    if (element) element.scrollLeft = Math.max(0, x(now) - (element.clientWidth - LABEL_WIDTH) / 3);
  }, [x, now]);
  const drawn = useRef<{ scale: GanttScale; start: number } | null>(null);
  useLayoutEffect(() => {
    const before = drawn.current;
    drawn.current = { scale, start: range.start };
    const element = scroller.current;
    if (!before || before.scale !== scale) scrollToToday();
    else if (element && before.start !== range.start) {
      element.scrollLeft += x(before.start);
    }
  }, [scale, range.start, x, scrollToToday]);

  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const settle = useRef<number | undefined>(undefined);
  const moveDrag = (next: Drag | null) => {
    dragRef.current = next;
    setDrag(next);
  };
  const canMove = Boolean(onReschedule) && !editing;

  /** Save `dates`, drawn where they were dropped until it answers: whether
   *  they were saved. */
  const write = async (task: Pick<TaskListRead, "id" | "recurrence">, dates: Dates) => {
    if (!onReschedule) return false;
    setPending((all) => new Map(all).set(task.id, dates));
    try {
      return await onReschedule(task, dates);
    } finally {
      setPending((all) => {
        const next = new Map(all);
        next.delete(task.id);
        return next;
      });
    }
  };

  // Moving a task later offers to move what waits on it, through the chain,
  // by as many days.
  const [chain, setChain] = useState<Chain | null>(null);
  const commit = async (task: TaskListRead, dates: Dates, later: number) => {
    // Only once its own move is saved: one asked about and kept back, or
    // refused, leaves what waits on it where it is.
    if (!(await write(task, dates)) || later <= 0 || !edges) return;
    // Through every task of the project, the ones a filter hides among them.
    const others = new Set((links?.others ?? []).map((each) => each.id));
    const project = new Set(
      [...tasks.map((each) => each.id), ...edges.flatMap((e) => [e.source_id, e.target_id])].filter(
        (id) => !others.has(id)
      )
    );
    const ids = waitingOn(task.id, edges, project);
    if (ids.length > 0) setChain({ title: task.title, ids, days: later });
  };
  const moveChain = async ({ ids, days }: Chain) => {
    setChain(null);
    const byId = new Map(tasks.map((each) => [each.id, each]));
    // One after another, so a repeating one's question is asked on its own; a
    // task the filters hide is read first.
    for (const id of ids) {
      const each = byId.get(id) ?? (await readTask(communityId, id).catch(() => null));
      if (each && spanOf(each)) await write(each, draggedDates(each, "move", days));
    }
  };

  const dayAt = (event: ReactPointerEvent<HTMLElement>) => {
    const track = event.currentTarget.getBoundingClientRect();
    return floorToUnit(range.start + ((event.clientX - track.left) / pxPerDay) * DAY, "day");
  };

  const press = (
    event: ReactPointerEvent<HTMLElement>,
    key: string,
    task: TaskListRead,
    hold: DragHold,
    from?: number
  ) => {
    if (event.button !== 0 || (!canMove && from !== undefined)) return;
    event.stopPropagation();
    // Arrow-key moves not yet saved are saved before another change starts.
    if (settle.current !== undefined) release();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    moveDrag({ key, task, hold, originX: event.clientX, days: 0, moved: false, from });
  };

  const follow = (event: ReactPointerEvent<HTMLElement>) => {
    const current = dragRef.current;
    if (!current) return;
    const dx = event.clientX - current.originX;
    const moved = current.moved || Math.abs(dx) > DRAG_SLOP;
    const days = canMove ? Math.round(dx / pxPerDay) : 0;
    if (moved !== current.moved || days !== current.days) moveDrag({ ...current, moved, days });
  };

  const release = () => {
    const current = dragRef.current;
    window.clearTimeout(settle.current);
    settle.current = undefined;
    moveDrag(null);
    if (!current) return;
    if (current.from !== undefined) {
      // A click on an empty track is not a choice of dates; a drag across it is.
      if (current.moved) {
        void write(current.task, scheduledDates(current.from, current.days));
      }
      return;
    }
    if (!current.moved) {
      if (!editing) void navigate({ to: taskHref(current.task.id) });
      return;
    }
    const span = spanOf(current.task);
    const days = span ? heldDays(span, current.hold, current.days) : 0;
    if (days !== 0) {
      const dates = draggedDates(current.task, current.hold, days);
      void commit(current.task, dates, current.hold === "start" ? 0 : days);
    }
  };

  /** Where a row's bar is drawn, the drag on it included. */
  const spanIn = (key: string, task: TaskListRead): GanttSpan | null => {
    const span = spanOf(task);
    if (!drag || drag.key !== key) return span;
    if (drag.from !== undefined) return { ...draggedAcross(drag.from, drag.days), kind: "bar" };
    if (!span) return null;
    const days = heldDays(span, drag.hold, drag.days);
    return {
      ...span,
      start: drag.hold === "end" ? span.start : addUnits(span.start, "day", days),
      end: drag.hold === "start" ? span.end : addUnits(span.end, "day", days),
    };
  };

  const toggleFold = (key: string) =>
    setFolded((all) => {
      const next = new Set(all);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  // Which rows are in view, from where the chart is scrolled to: only those,
  // and the one in the tab order, are drawn.
  const [view, setView] = useState({ top: 0, height: 0 });
  const measure = useCallback(() => {
    const element = scroller.current;
    if (element) setView({ top: element.scrollTop, height: element.clientHeight });
  }, []);
  useLayoutEffect(() => {
    measure();
    const element = scroller.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);
  const first = Math.max(0, Math.floor((view.top - HEADER_HEIGHT) / ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(rows.length, Math.ceil((view.top + view.height) / ROW_HEIGHT) + OVERSCAN);

  // One row is in the tab order, and the arrow keys move it.
  const body = useRef<HTMLDivElement>(null);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const focused = Math.min(focusedIndex, Math.max(0, rows.length - 1));
  const keyed = useRef(false);
  const focusRow = (index: number) => {
    const next = Math.max(0, Math.min(index, rows.length - 1));
    const element = scroller.current;
    if (element) {
      const top = next * ROW_HEIGHT;
      const room = element.clientHeight - HEADER_HEIGHT - ROW_HEIGHT;
      if (top < element.scrollTop) element.scrollTop = top;
      else if (top > element.scrollTop + room) element.scrollTop = top - room;
    }
    keyed.current = true;
    setFocusedIndex(next);
  };
  useEffect(() => {
    if (!keyed.current) return;
    keyed.current = false;
    body.current?.querySelector<HTMLElement>(`[data-row="${focused}"]`)?.focus();
  }, [focused]);
  // Arrow-key moves are saved, not dropped, when the chart goes away.
  const releaseOnLeave = useRef(release);
  releaseOnLeave.current = release;
  useEffect(
    () => () => {
      if (settle.current !== undefined) releaseOnLeave.current();
    },
    []
  );

  /** Alt and an arrow: the row's task a day along, saved once the presses
   *  stop. A task with no dates starts on today. */
  const nudge = (row: Extract<GanttRow, { type: "task" }>, hold: DragHold, step: number) => {
    const current = dragRef.current;
    if (current && (current.key !== row.key || current.hold !== hold)) release();
    const base = dragRef.current ?? {
      key: row.key,
      task: row.task,
      hold,
      originX: 0,
      days: 0,
      moved: true,
      from: spanOf(row.task) ? undefined : floorToUnit(now, "day"),
    };
    moveDrag({ ...base, days: base.days + step });
    window.clearTimeout(settle.current);
    settle.current = window.setTimeout(release, KEY_SETTLE_MS);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const row = rows[focused];
    if (!row) return;
    const sideways = event.key === "ArrowLeft" || event.key === "ArrowRight";
    if (event.altKey && sideways) {
      if (row.type !== "task" || !canMove) return;
      const hold = event.shiftKey && spanOf(row.task)?.kind === "bar" ? "end" : "move";
      nudge(row, hold, event.key === "ArrowRight" ? 1 : -1);
      event.preventDefault();
      return;
    }
    switch (event.key) {
      case "ArrowDown":
        focusRow(focused + 1);
        break;
      case "ArrowUp":
        focusRow(focused - 1);
        break;
      case "Home":
        focusRow(0);
        break;
      case "End":
        focusRow(rows.length - 1);
        break;
      case "ArrowRight":
        // Open a folded task, then step into its parts.
        if (row.type !== "task" || !row.hasParts) return;
        if (row.open) focusRow(focused + 1);
        else toggleFold(row.key);
        break;
      case "ArrowLeft": {
        if (row.type !== "task") return;
        if (row.hasParts && row.open) {
          toggleFold(row.key);
          break;
        }
        // Otherwise up to the task it is part of.
        let whole = focused - 1;
        while (whole >= 0) {
          const above = rows[whole];
          if (above.type === "task" && above.depth < row.depth) break;
          whole--;
        }
        if (row.depth === 0 || whole < 0) return;
        focusRow(whole);
        break;
      }
      case "Enter":
        if (row.type === "group" || editing) return;
        if (settle.current !== undefined) release();
        void navigate({ to: hrefOf(row) });
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  /** Where a row's task opens: this project's own, or another project's. */
  const hrefOf = (row: Extract<GanttRow, { type: "task" | "outside" }>) =>
    row.type === "task"
      ? taskHref(row.task.id)
      : gp(taskRoute(row.task.initiative_id, row.task.project_id, row.task.id));

  // A link drawn from the dot at a task's end to another task's row: the task
  // dropped on waits on the one it was drawn from, or is part of it.
  const relate = useRelate();
  const unrelate = useUnrelate();
  const [menu, setMenu] = useState<LinkMenu | null>(null);
  const [linking, setLinking] = useState<Linking | null>(null);
  const onChart = (event: ReactPointerEvent<HTMLElement>) => {
    const rect = body.current?.getBoundingClientRect();
    return {
      x: event.clientX - (rect?.left ?? 0) - LABEL_WIDTH,
      y: event.clientY - (rect?.top ?? 0),
    };
  };
  const startLink = (event: ReactPointerEvent<HTMLElement>, task: TaskListRead, index: number) => {
    const span = spanOf(task);
    if (event.button !== 0 || !canMove || !span) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const x1 = x(span.end);
    const y1 = index * ROW_HEIGHT + ROW_HEIGHT / 2;
    setLinking({ task, index, x1, y1, x2: x1, y2: y1 });
  };
  const followLink = (event: ReactPointerEvent<HTMLElement>) => {
    const { x: x2, y: y2 } = onChart(event);
    setLinking((current) => current && { ...current, x2, y2 });
  };
  const endLink = (event: ReactPointerEvent<HTMLElement>) => {
    const from = linking;
    setLinking(null);
    if (!from) return;
    const point = onChart(event);
    const target = rows[Math.floor(point.y / ROW_HEIGHT)];
    if (target?.type !== "task" || target.task.id === from.task.id) return;
    setMenu({ kind: "drop", from: from.task, to: target.task, x: point.x, y: point.y });
  };
  const link = (to: TaskListRead, kind: RelationshipType, from: TaskListRead) =>
    relate.mutate({
      source: { type: SearchEntityType.task, id: to.id },
      relationship_type: kind,
      target: { type: SearchEntityType.task, id: from.id },
    });
  const titleOf = (id: number) =>
    tasks.find((each) => each.id === id)?.title ??
    links?.others.find((each) => each.id === id)?.title ??
    "";
  const linkingOver = linking ? Math.floor(linking.y2 / ROW_HEIGHT) : -1;

  // The critical path: the chain of the project's tasks that ends last.
  const [critical, setCritical] = useState(false);
  const onPath = useMemo(() => {
    if (!critical) return new Set<number>();
    const spans = new Map(
      shown.flatMap((task) => {
        const span = spanOf(task);
        return span ? [[task.id, span] as const] : [];
      })
    );
    return criticalPath(spans, edges ?? []);
  }, [critical, shown, edges]);

  // A dependency's arrow runs from the end of what blocks to the start of
  // what waits, between the first rows each is drawn in.
  const arrows = useMemo(() => {
    const at = new Map<number, { index: number; span: GanttSpan }>();
    rows.forEach((row, index) => {
      if (row.type === "group" || at.has(row.task.id)) return;
      const span = spanOf(row.task);
      if (span) at.set(row.task.id, { index, span });
    });
    return (edges ?? []).flatMap((edge) => {
      if (edge.relationship_type !== "depends_on") return [];
      const waits = at.get(edge.source_id);
      const blocks = at.get(edge.target_id);
      if (!waits || !blocks) return [];
      if (Math.max(waits.index, blocks.index) < first) return [];
      if (Math.min(waits.index, blocks.index) >= last) return [];
      const x1 = x(blocks.span.end);
      const y1 = blocks.index * ROW_HEIGHT + ROW_HEIGHT / 2;
      const x2 = x(waits.span.start);
      const y2 = waits.index * ROW_HEIGHT + ROW_HEIGHT / 2;
      const path =
        x2 - x1 >= ELBOW * 2
          ? `M${x1},${y1} H${x1 + ELBOW} V${y2} H${x2}`
          : `M${x1},${y1} H${x1 + ELBOW} V${(y1 + y2) / 2} H${x2 - ELBOW} V${y2} H${x2}`;
      return [
        {
          edge,
          path,
          late: waits.span.start < blocks.span.end,
          faded: critical && !(onPath.has(edge.source_id) && onPath.has(edge.target_id)),
        },
      ];
    });
  }, [rows, edges, x, first, last, critical, onPath]);

  const tickLabel = (tick: AxisTick) =>
    dateTimeFormat(locale, scale === "month" ? { month: "short" } : { day: "numeric" }).format(
      new Date(tick.at)
    );
  const segmentLabel = (at: number) =>
    dateTimeFormat(
      locale,
      major.unit === "year" ? { year: "numeric" } : { month: "long", year: "numeric" }
    ).format(new Date(at));
  const dayLabel = (at: number) =>
    dateTimeFormat(locale, { month: "short", day: "numeric" }).format(new Date(at));

  const todayX = x(floorToUnit(now, "day"));
  const markerId = useId();

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-3">
        {onGroupingChange && offered.length > 0 && !editing ? (
          <GroupBySelect
            options={offered.map(({ grouping: each }) => ({ id: each.column, label: each.label }))}
            value={active?.grouping.column ?? null}
            onChange={(id) => onGroupingChange(id === null ? [] : [id])}
          />
        ) : null}
        {(edges ?? []).some((edge) => edge.relationship_type === "depends_on") ? (
          <Toggle variant="outline" size="sm" pressed={critical} onPressedChange={setCritical}>
            {t("tasks.ganttCriticalPath")}
          </Toggle>
        ) : null}
        <Button type="button" variant="outline" size="sm" onClick={scrollToToday}>
          {t("common:calendar.today")}
        </Button>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={scale}
          onValueChange={(next) => {
            if (next) onScaleChange?.(next as GanttScale);
          }}
          aria-label={t("common:calendar.viewMode")}
        >
          {GANTT_SCALES.map((each) => (
            <ToggleGroupItem key={each} value={each}>
              {t(`common:calendar.${each}` as never)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <div
        ref={scroller}
        onScroll={measure}
        className="scrollbar-thin max-h-[75vh] overflow-auto rounded-md border text-sm"
        data-testid="gantt"
      >
        <div className="relative" style={{ width: LABEL_WIDTH + width }}>
          {/* The axis: the coarser unit over its days, weeks or months. */}
          <div
            className="sticky top-0 z-20 flex border-b bg-background"
            style={{ height: HEADER_HEIGHT }}
          >
            <div
              className="sticky left-0 z-10 shrink-0 border-r bg-background"
              style={{ width: LABEL_WIDTH }}
            />
            <div className="relative" style={{ width }}>
              {major.segments.map((segment) => (
                <div
                  key={segment.at}
                  className="absolute top-0 h-5 truncate border-l px-1.5 font-medium text-muted-foreground text-xs leading-5"
                  style={{ left: x(segment.start), width: x(segment.end) - x(segment.start) }}
                >
                  {segmentLabel(segment.at)}
                </div>
              ))}
              {ticks.map((tick) => (
                <div
                  key={tick.at}
                  className="absolute bottom-0 h-5 truncate border-l px-1 text-2xs text-muted-foreground leading-5"
                  style={{ left: x(tick.at) }}
                >
                  {tickLabel(tick)}
                </div>
              ))}
            </div>
          </div>

          <p id={`${markerId}-keys`} className="sr-only">
            {t(canMove ? "tasks.ganttKeysMove" : "tasks.ganttKeys")}
          </p>
          <div
            ref={body}
            className="relative"
            style={{ height: Math.max(rows.length, 1) * ROW_HEIGHT }}
            role="treegrid"
            aria-label={t("tasks.viewGantt")}
            aria-describedby={`${markerId}-keys`}
            aria-rowcount={rows.length}
            onKeyDown={onKeyDown}
          >
            {/* Behind the bars: weekends, gridlines, today and the arrows. */}
            <div
              className="pointer-events-none absolute inset-y-0"
              style={{ left: LABEL_WIDTH, width }}
              aria-hidden
            >
              {weekends.map((band) => (
                <div
                  key={band.start}
                  className="absolute inset-y-0 bg-muted/40"
                  style={{ left: x(band.start), width: x(band.end) - x(band.start) }}
                />
              ))}
              {ticks.map((tick) => (
                <div
                  key={tick.at}
                  className="absolute inset-y-0 w-px bg-border/50"
                  style={{ left: x(tick.at) }}
                />
              ))}
              <div className="absolute inset-y-0 w-px bg-primary" style={{ left: todayX }} />
              <svg
                className="absolute inset-0 overflow-visible"
                width={width}
                height={rows.length * ROW_HEIGHT}
              >
                <defs>
                  {[false, true].map((late) => (
                    <marker
                      key={String(late)}
                      id={`${markerId}-${late}`}
                      viewBox="0 0 6 6"
                      refX="6"
                      refY="3"
                      markerWidth="6"
                      markerHeight="6"
                      orient="auto"
                    >
                      <path
                        d="M0,0 L6,3 L0,6 z"
                        className={late ? "fill-destructive" : "fill-muted-foreground"}
                      />
                    </marker>
                  ))}
                </defs>
                {arrows.map((arrow) => (
                  <g key={arrow.edge.id} className={cn(arrow.faded && "opacity-25")}>
                    <path
                      d={arrow.path}
                      fill="none"
                      strokeWidth={1.5}
                      markerEnd={`url(#${markerId}-${arrow.late})`}
                      className={arrow.late ? "stroke-destructive" : "stroke-muted-foreground"}
                    />
                  </g>
                ))}
                {linking ? (
                  <path
                    d={`M${linking.x1},${linking.y1} L${linking.x2},${linking.y2}`}
                    fill="none"
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                    markerEnd={`url(#${markerId}-false)`}
                    className="stroke-primary"
                  />
                ) : null}
              </svg>
            </div>

            <DropdownMenu
              open={menu !== null}
              onOpenChange={(open) => {
                if (!open) setMenu(null);
              }}
            >
              <DropdownMenuTrigger asChild>
                <span
                  className="pointer-events-none absolute h-0 w-0"
                  style={{ left: LABEL_WIDTH + (menu?.x ?? 0), top: menu?.y ?? 0 }}
                  aria-hidden
                />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                {menu?.kind === "drop" ? (
                  <>
                    <DropdownMenuLabel className="max-w-xs font-normal text-muted-foreground">
                      {t("tasks.ganttLinkQuestion", {
                        task: menu.to.title,
                        other: menu.from.title,
                      })}
                    </DropdownMenuLabel>
                    <DropdownMenuItem
                      onSelect={() => link(menu.to, RelationshipType.depends_on, menu.from)}
                    >
                      <span className="flex flex-col">
                        <span>{t("tasks.ganttBlockedBy")}</span>
                        <span className="text-muted-foreground text-xs">
                          {t("tasks.ganttBlockedByHint")}
                        </span>
                      </span>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => link(menu.to, RelationshipType.part_of, menu.from)}
                    >
                      <span className="flex flex-col">
                        <span>{t("tasks.ganttPartOf")}</span>
                        <span className="text-muted-foreground text-xs">
                          {t("tasks.ganttPartOfHint")}
                        </span>
                      </span>
                    </DropdownMenuItem>
                  </>
                ) : null}
                {menu?.kind === "arrow" ? (
                  <DropdownMenuItem onSelect={() => unrelate.mutate({ id: menu.edge.id })}>
                    {t("tasks.ganttRemoveLink", {
                      task: titleOf(menu.edge.source_id),
                      other: titleOf(menu.edge.target_id),
                    })}
                  </DropdownMenuItem>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>

            {rows.length === 0 ? (
              <p
                className="sticky left-0 p-6 text-muted-foreground"
                style={{ width: LABEL_WIDTH + 320 }}
              >
                {t("tasks.ganttEmpty")}
              </p>
            ) : null}
            {drawnIndexes(first, last, [
              focused,
              // The rows a drag or a link is drawn from, until it ends.
              rows.findIndex((row) => row.type === "task" && row.key === drag?.key),
              linking?.index ?? -1,
            ]).map((index) => {
              const row = rows[index];
              if (!row) return null;
              const rowProps = {
                "data-row": index,
                onFocus: () => setFocusedIndex(index),
                "aria-rowindex": index + 1,
                className: cn(
                  "group/row absolute inset-x-0 flex border-b outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
                  linkingOver === index && "bg-accent"
                ),
                style: { top: index * ROW_HEIGHT, height: ROW_HEIGHT },
              } as const;
              if (row.type === "group") {
                return (
                  // biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics
                  <div
                    key={`group:${row.key}`}
                    role="row"
                    tabIndex={index === focused ? 0 : -1}
                    {...rowProps}
                    aria-level={1}
                  >
                    {/* biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics */}
                    <div
                      role="gridcell"
                      tabIndex={-1}
                      className="sticky left-0 z-10 flex shrink-0 items-center gap-2 border-r bg-muted px-3"
                      style={{ width: LABEL_WIDTH }}
                    >
                      <span className="min-w-0 truncate">
                        {row.label ?? active?.grouping.header(row.key)}
                      </span>
                      <span className="text-muted-foreground text-xs tabular-nums">
                        {row.count}
                      </span>
                    </div>
                  </div>
                );
              }
              if (row.type === "outside") {
                return (
                  <OutsideRow
                    key={row.key}
                    row={row}
                    index={index}
                    tabIndex={index === focused ? 0 : -1}
                    rowProps={rowProps}
                    href={hrefOf(row)}
                    editing={editing}
                    width={width}
                    x={x}
                    dayLabel={dayLabel}
                  />
                );
              }
              const span = spanOf(row.task);
              return (
                // biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics
                <div
                  key={row.key}
                  role="row"
                  tabIndex={index === focused ? 0 : -1}
                  {...rowProps}
                  aria-level={row.depth + (active ? 2 : 1)}
                  aria-expanded={row.hasParts ? row.open : undefined}
                  aria-label={
                    span
                      ? `${row.task.title}, ${dayLabel(span.start)} – ${dayLabel(addUnits(span.end, "day", -1))}`
                      : row.task.title
                  }
                >
                  {/* biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics */}
                  <div
                    role="gridcell"
                    tabIndex={-1}
                    className="sticky left-0 z-10 flex shrink-0 items-center gap-1.5 border-r bg-background pr-2 group-hover/row:bg-muted"
                    style={{ width: LABEL_WIDTH, paddingLeft: 8 + row.depth * INDENT }}
                  >
                    {row.hasParts ? (
                      <button
                        type="button"
                        tabIndex={-1}
                        onClick={() => toggleFold(row.key)}
                        className="-m-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                        aria-expanded={row.open}
                        aria-label={t(row.open ? "tasks.ganttFold" : "tasks.ganttUnfold", {
                          title: row.task.title,
                        })}
                      >
                        <ChevronRight
                          className={cn(
                            "h-3.5 w-3.5 transition-transform",
                            row.open && "rotate-90"
                          )}
                          aria-hidden
                        />
                      </button>
                    ) : (
                      <span className="w-3.5 shrink-0" aria-hidden />
                    )}
                    {typed && row.task.task_type ? (
                      <TaskTypeMark type={row.task.task_type} />
                    ) : null}
                    {editing ? (
                      <span className="min-w-0 truncate">{row.task.title}</span>
                    ) : (
                      <Link
                        to={taskHref(row.task.id)}
                        tabIndex={-1}
                        className={cn(
                          "min-w-0 truncate hover:underline",
                          row.task.task_status.category === "done" && "text-muted-foreground"
                        )}
                      >
                        {row.task.title}
                      </Link>
                    )}
                  </div>
                  <TaskTrack
                    row={row}
                    width={width}
                    x={x}
                    span={spanIn(row.key, row.task)}
                    canMove={canMove}
                    dragging={drag?.key === row.key}
                    scheduleHint={t("tasks.ganttSchedule")}
                    linkHint={t("tasks.ganttLink")}
                    next={nextOf.get(row.task.id)}
                    faded={critical && !onPath.has(row.task.id)}
                    dayLabel={dayLabel}
                    onPress={(event, hold) => press(event, row.key, row.task, hold)}
                    onSchedule={(event) => press(event, row.key, row.task, "move", dayAt(event))}
                    onFollow={follow}
                    onRelease={release}
                    onCancel={() => moveDrag(null)}
                    onLinkStart={(event) => startLink(event, row.task, index)}
                    onLinkMove={followLink}
                    onLinkEnd={endLink}
                    onLinkCancel={() => setLinking(null)}
                  />
                </div>
              );
            })}
            {canMove && arrows.length > 0 ? (
              // Over the rows, so a click on an arrow reaches it: an unseen,
              // wider line on each, which takes its link back. The keyboard
              // does so from the task's Connections.
              <svg
                className="pointer-events-none absolute inset-y-0 z-[5] overflow-visible"
                style={{ left: LABEL_WIDTH }}
                width={width}
                height={rows.length * ROW_HEIGHT}
                aria-hidden
              >
                {arrows.map((arrow) => (
                  // biome-ignore lint/a11y/noStaticElementInteractions: a pointer shortcut beside the task page's own control
                  <path
                    key={arrow.edge.id}
                    d={arrow.path}
                    fill="none"
                    strokeWidth={8}
                    className="cursor-pointer stroke-transparent"
                    style={{ pointerEvents: "stroke" }}
                    data-testid="gantt-arrow"
                    onClick={(event) => {
                      const rect = body.current?.getBoundingClientRect();
                      setMenu({
                        kind: "arrow",
                        edge: arrow.edge,
                        x: event.clientX - (rect?.left ?? 0) - LABEL_WIDTH,
                        y: event.clientY - (rect?.top ?? 0),
                      });
                    }}
                  />
                ))}
              </svg>
            ) : null}
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={chain !== null}
        onOpenChange={(open) => {
          if (!open) setChain(null);
        }}
        title={t("tasks.ganttChainTitle")}
        description={
          chain
            ? t("tasks.ganttChain", {
                count: chain.ids.length,
                title: chain.title,
                days: chain.days,
              })
            : undefined
        }
        confirmLabel={t("tasks.ganttChainMove")}
        cancelLabel={t("tasks.ganttChainKeep")}
        onConfirm={() => {
          if (chain) void moveChain(chain);
        }}
      />
    </div>
  );
};

/** The rows from `first` up to `last`, and each of `kept` wherever it is:
 *  the row in the tab order, and any a drag or a link is drawn from. */
const drawnIndexes = (first: number, last: number, kept: number[]) => {
  const indexes: number[] = [];
  for (let index = first; index < last; index++) indexes.push(index);
  for (const index of new Set(kept)) {
    if (index >= 0 && (index < first || index >= last)) indexes.push(index);
  }
  return indexes;
};

type TrackProps = {
  row: Extract<GanttRow, { type: "task" }>;
  width: number;
  x: (at: number) => number;
  span: GanttSpan | null;
  canMove: boolean;
  dragging: boolean;
  scheduleHint: string;
  linkHint: string;
  /** The coming occurrences of a repeating task. */
  next?: GanttSpan[];
  /** Off the critical path, while it is shown. */
  faded: boolean;
  dayLabel: (at: number) => string;
  onPress: (event: ReactPointerEvent<HTMLElement>, hold: DragHold) => void;
  onSchedule: (event: ReactPointerEvent<HTMLElement>) => void;
  onFollow: (event: ReactPointerEvent<HTMLElement>) => void;
  onRelease: () => void;
  onCancel: () => void;
  onLinkStart: (event: ReactPointerEvent<HTMLElement>) => void;
  onLinkMove: (event: ReactPointerEvent<HTMLElement>) => void;
  onLinkEnd: (event: ReactPointerEvent<HTMLElement>) => void;
  onLinkCancel: () => void;
};

/** One task's stretch of the axis: its bar or marker, what its parts cover,
 *  or, with no dates, a track to drag dates onto. */
const TaskTrack = ({
  row,
  width,
  x,
  span,
  canMove,
  dragging,
  scheduleHint,
  linkHint,
  next,
  faded,
  dayLabel,
  onPress,
  onSchedule,
  onFollow,
  onRelease,
  onCancel,
  onLinkStart,
  onLinkMove,
  onLinkEnd,
  onLinkCancel,
}: TrackProps) => {
  const done = row.task.task_status.category === "done";
  const pointer = {
    onPointerMove: onFollow,
    onPointerUp: onRelease,
    onPointerCancel: onCancel,
  };
  const tooltip = span
    ? span.kind === "bar"
      ? `${row.task.title} · ${dayLabel(span.start)} → ${dayLabel(span.end - DAY)}`
      : `${row.task.title} · ${dayLabel(span.start)}`
    : undefined;
  const undated = spanOf(row.task) === null;

  return (
    // biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics
    <div
      role="gridcell"
      tabIndex={-1}
      className={cn(
        "relative",
        undated && canMove && "cursor-crosshair touch-pan-y",
        faded && "opacity-30"
      )}
      style={{ width }}
      title={undated && canMove && !dragging ? scheduleHint : undefined}
      onPointerDown={undated && canMove ? onSchedule : undefined}
      {...(undated ? pointer : {})}
    >
      {(next ?? []).map((occurrence) => (
        <div
          key={occurrence.start}
          className="pointer-events-none absolute top-1/2 h-4 -translate-y-1/2 rounded border border-primary/50 border-dashed"
          data-testid="gantt-next"
          style={{
            left: x(occurrence.start),
            width: Math.max(4, x(occurrence.end) - x(occurrence.start)),
          }}
          aria-hidden
        />
      ))}
      {row.parts ? (
        // What its parts cover, as a bracket over the row.
        <div
          className="pointer-events-none absolute top-1 h-1 rounded-sm bg-foreground/40"
          style={{
            left: x(row.parts.start),
            width: Math.max(2, x(row.parts.end) - x(row.parts.start)),
          }}
          aria-hidden
        />
      ) : null}
      {span && span.kind !== "bar" ? (
        <div
          className={cn(
            "absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px]",
            done ? "bg-muted-foreground/60" : "bg-primary",
            canMove ? "cursor-grab touch-none active:cursor-grabbing" : "cursor-pointer"
          )}
          style={{ left: x(span.start) + (x(span.end) - x(span.start)) / 2 }}
          title={tooltip}
          onPointerDown={(event) => onPress(event, "move")}
          {...pointer}
        />
      ) : null}
      {span && span.kind === "bar" ? (
        <div
          className={cn(
            "absolute top-1/2 h-4 -translate-y-1/2 rounded",
            done ? "bg-muted-foreground/40" : "bg-primary/80",
            dragging && "ring-2 ring-ring",
            canMove ? "cursor-grab touch-none active:cursor-grabbing" : "cursor-pointer"
          )}
          style={{ left: x(span.start), width: Math.max(4, x(span.end) - x(span.start)) }}
          title={tooltip}
          onPointerDown={(event) => onPress(event, "move")}
          {...pointer}
        >
          {canMove ? (
            <>
              <span
                className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize touch-none"
                onPointerDown={(event) => onPress(event, "start")}
                {...pointer}
              />
              <span
                className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize touch-none"
                onPointerDown={(event) => onPress(event, "end")}
                {...pointer}
              />
            </>
          ) : null}
        </div>
      ) : null}
      {span && canMove && !dragging ? (
        // Drawn from here to another task's row, it asks how the two are linked.
        // Above the arrows' hit lines, which leave the bar's end right here,
        // so a task with links can still start another.
        <span
          className="absolute top-1/2 z-[6] h-2.5 w-2.5 -translate-y-1/2 cursor-crosshair touch-none rounded-full border-2 border-primary bg-background opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100"
          style={{ left: x(span.end) + 3 }}
          title={linkHint}
          data-testid="gantt-link"
          onPointerDown={onLinkStart}
          onPointerMove={onLinkMove}
          onPointerUp={onLinkEnd}
          onPointerCancel={onLinkCancel}
        />
      ) : null}
    </div>
  );
};

/** Another project's task a task here is linked to: drawn, and opened, but
 *  not moved from here. */
const OutsideRow = ({
  row,
  index,
  tabIndex,
  rowProps,
  href,
  editing,
  width,
  x,
  dayLabel,
}: {
  row: Extract<GanttRow, { type: "outside" }>;
  index: number;
  tabIndex: number;
  rowProps: Record<string, unknown>;
  href: string;
  editing: boolean;
  width: number;
  x: (at: number) => number;
  dayLabel: (at: number) => string;
}) => {
  const span = spanOf(row.task);
  const task: LinkedTaskRead = row.task;
  return (
    // biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics
    <div
      role="row"
      tabIndex={tabIndex}
      {...rowProps}
      data-row={index}
      aria-level={2}
      aria-label={
        span
          ? `${task.title}, ${task.project_name}, ${dayLabel(span.start)} – ${dayLabel(addUnits(span.end, "day", -1))}`
          : `${task.title}, ${task.project_name}`
      }
    >
      {/* biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics */}
      <div
        role="gridcell"
        tabIndex={-1}
        className="sticky left-0 z-10 flex shrink-0 items-center gap-1.5 border-r bg-background pr-2 pl-[30px] group-hover/row:bg-muted"
        style={{ width: LABEL_WIDTH }}
      >
        {editing ? (
          <span className="min-w-0 truncate">{task.title}</span>
        ) : (
          <Link
            to={href}
            tabIndex={-1}
            className={cn("min-w-0 truncate hover:underline", task.done && "text-muted-foreground")}
          >
            {task.title}
          </Link>
        )}
        <span className="shrink-0 truncate text-muted-foreground text-xs">{task.project_name}</span>
      </div>
      {/* biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics */}
      <div role="gridcell" tabIndex={-1} className="relative" style={{ width }}>
        {span ? (
          <div
            className={cn(
              "absolute top-1/2 -translate-y-1/2",
              span.kind === "bar"
                ? "h-4 rounded border border-muted-foreground/60 bg-muted"
                : "h-3 w-3 -translate-x-1/2 rotate-45 rounded-[2px] bg-muted-foreground/60"
            )}
            style={
              span.kind === "bar"
                ? { left: x(span.start), width: Math.max(4, x(span.end) - x(span.start)) }
                : { left: x(span.start) + (x(span.end) - x(span.start)) / 2 }
            }
            title={`${task.title} · ${task.project_name}`}
          />
        ) : null}
      </div>
    </div>
  );
};

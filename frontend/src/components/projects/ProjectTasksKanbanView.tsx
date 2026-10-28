import {
  type CollisionDetection,
  closestCorners,
  DndContext,
  type DndContextProps,
  type DragEndEvent,
  type DragOverEvent,
  DragOverlay,
  type DragStartEvent,
  type DroppableContainer,
  pointerWithin,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import type { GroupingState } from "@tanstack/react-table";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import type {
  CardPartInput,
  LayoutGrouping,
  ListLayoutDefinitionInputDisplays,
  ListTasksParams,
  PropertyDefinitionRead,
  TaskListRead,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { KanbanBands } from "@/components/projects/KanbanBands";
import { type ColumnFill, KanbanColumn } from "@/components/projects/KanbanColumn";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { resolveKanbanDropTarget } from "@/components/projects/taskOrdering";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Badge } from "@/components/ui/badge";
import { GroupBySelect } from "@/components/ui/data-table";
import { MentionText } from "@/components/user/MentionText";
import { type ColumnLimits, NO_COLUMN_LIMITS } from "@/hooks/useColumnLimits";
import { useProjectTaskTypes } from "@/hooks/useProjects";
import { NO_DEFINITIONS, useOwnedDefinitions } from "@/hooks/useProperties";
import { useTaskGroupings } from "@/hooks/useTaskGroupings";
import { useMoveTaskToGroup } from "@/hooks/useTasks";
import { formatDateTime } from "@/lib/formatDate";
import { cardOf } from "@/lib/layouts/draft";
import { useProjectLayoutEnv, withDisplays } from "@/lib/layouts/fields";
import { boardBands } from "@/lib/layouts/grouping";
import { pluginFields, usePluginsOnItems } from "@/lib/layouts/plugins";
import { taskFields } from "@/lib/layouts/tasks";
import { type LayoutContext, type LayoutNode, namesField } from "@/lib/layouts/tree";
import { cn } from "@/lib/utils";

import { TaskAssigneeList } from "./TaskAssigneeList";
import { type BoardActions, BoardActionsContext, TaskCardActions } from "./TaskQuickActions";

type ProjectTasksKanbanViewProps = {
  projectId: number;
  initiativeId: number;
  taskStatuses: TaskStatusRead[];
  groupedTasks: Record<number, TaskListRead[]>;
  /** The list the board's tasks are, which its bands are worked out for. A
   *  board drawn from no list (a listing's preview) is never grouped. */
  listParams?: ListTasksParams;
  collapsedStatusIds: Set<number>;
  canReorderTasks: boolean;
  /** The reader may change the tasks: each card offers what can be done with
   *  it beside its title. */
  canEditTasks?: boolean;
  /** Moves a task to a column from its card's menu, as dropping it there would. */
  onStatusChange?: (taskId: number, taskStatusId: number) => void;
  taskHref: (taskId: number) => string;
  sensors: DndContextProps["sensors"];
  activeTask: TaskListRead | null;
  onDragStart: (event: DragStartEvent) => void;
  onDragOver: (event: DragOverEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onToggleCollapse: (statusId: number) => void;
  onArchiveDoneTasks?: (statusId: number) => void;
  isArchivingDoneTasks?: boolean;
  /** The properties the cards can show. When given, the board asks for none,
   *  nor for plug-ins: a listing's preview has no initiative to ask. */
  propertyDefinitions?: PropertyDefinitionRead[];
  /** The view's card, where it has its own. */
  /** The project's own card; none draws the shipped one. */
  card?: LayoutNode | null;
  /** How the card draws each scale, as the layout says. */
  displays?: ListLayoutDefinitionInputDisplays;
  /** What the board is grouped by, as its reader's view keeps it. */
  grouping?: GroupingState;
  /** Where the reader picks what it is grouped by; left out, nowhere. */
  onGroupingChange?: (grouping: GroupingState) => void;
  /** The groupings the board offers, in order, where its layout names them. */
  viewGroupings?: LayoutGrouping[] | null;
  /** How full its limited columns are. */
  columnLimits?: ColumnLimits;
  /** While the view is edited: the path of each part of its card. */
  editing?: WeakMap<LayoutNode, string>;
};

// One empty list while the definitions load, so the fields aren't rebuilt on
// every pass until they arrive.
const NOT_GROUPED: GroupingState = [];

export const ProjectTasksKanbanView = ({
  projectId,
  initiativeId,
  taskStatuses,
  groupedTasks,
  listParams,
  collapsedStatusIds,
  canReorderTasks,
  canEditTasks = false,
  onStatusChange,
  taskHref,
  sensors,
  activeTask,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDragCancel,
  onToggleCollapse,
  onArchiveDoneTasks,
  isArchivingDoneTasks,
  propertyDefinitions: givenDefinitions,
  card: ownCard,
  displays,
  grouping = NOT_GROUPED,
  onGroupingChange,
  viewGroupings,
  columnLimits = NO_COLUMN_LIMITS,
  editing,
}: ProjectTasksKanbanViewProps) => {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  useHorizontalDragScroll(scrollContainerRef);

  // The project's metadata and its initiative's properties, which the cards
  // can show. What a card shows is its view's card.
  const { data: fetchedDefinitions = NO_DEFINITIONS } = useOwnedDefinitions({
    initiativeId,
    owner: { kind: "project", id: projectId },
    enabled: !givenDefinitions,
  });
  const propertyDefinitions = givenDefinitions ?? fetchedDefinitions;
  // Built once per change rather than once per card, and stable in between so
  // the memoized cards skip re-rendering on an unrelated parent pass. What the
  // renderers share is held apart, so a change of fields redraws the cards but
  // not the values on them.
  const projectEnv = useProjectLayoutEnv(taskHref);
  const env = useMemo(
    () => (canEditTasks ? { ...projectEnv, itemActions: TaskCardActions } : projectEnv),
    [projectEnv, canEditTasks]
  );
  // The handler changes with every list of tasks; the cards' menus hold one
  // that doesn't, so a refetch neither redraws every card nor closes a menu.
  const moveRef = useRef(onStatusChange);
  useEffect(() => {
    moveRef.current = onStatusChange;
  });
  const canMove = onStatusChange !== undefined;
  const boardActions = useMemo<BoardActions | null>(
    () =>
      canMove
        ? {
            statuses: taskStatuses,
            moveTo: (taskId, statusId) => moveRef.current?.(taskId, statusId),
            isFull: columnLimits.isFull,
          }
        : null,
    [canMove, taskStatuses, columnLimits]
  );
  const fillOf = (statusId: number): ColumnFill | undefined => {
    const limit = columnLimits.limitOf(statusId);
    return limit === undefined ? undefined : { count: columnLimits.countOf(statusId), limit };
  };
  const { i18n } = useTranslation();
  const plugins = usePluginsOnItems(initiativeId, !givenDefinitions);
  // A project with one type shows none: it tells no task apart.
  const typed = (useProjectTaskTypes(projectId).data?.length ?? 0) > 1;
  const fields = useMemo(
    () =>
      withDisplays(
        taskFields(propertyDefinitions, pluginFields(plugins, i18n.language), { typed }),
        displays
      ),
    [propertyDefinitions, plugins, i18n.language, typed, displays]
  );
  const card = useMemo(
    () => cardOf({ card: ownCard as CardPartInput | null | undefined }, fields),
    [ownCard, fields]
  );
  const view = useMemo<LayoutContext>(
    () => ({
      fields,
      plugins,
      card,
      variant: "card",
      env,
      editing,
    }),
    [fields, plugins, card, env, editing]
  );

  // What the board offers to group by, and the bands of the one it is.
  const tasks = useMemo(
    () => taskStatuses.flatMap((status) => groupedTasks[status.id] ?? []),
    [taskStatuses, groupedTasks]
  );
  const { offered, active } = useTaskGroupings({
    fields,
    statuses: taskStatuses,
    tasks,
    groupings: viewGroupings,
    kind: "board",
    grouping,
    params: listParams,
    t: projectEnv.t,
  });
  const bands = useMemo(() => (active ? boardBands(active, tasks) : null), [active, tasks]);
  const counts = useMemo(
    () =>
      Object.fromEntries(
        taskStatuses.map((status) => [status.id, groupedTasks[status.id]?.length ?? 0])
      ),
    [taskStatuses, groupedTasks]
  );

  // A card dropped into another band changes the field the board is grouped
  // by, beside what the drop does to its column and its place in it. One
  // dropped on an empty part of a cell in its own column changes only that.
  const { mutate: moveTask } = useMoveTaskToGroup();
  const lastOver = useRef<DragOverEvent["over"] | null>(null);
  const handleDragOver = (event: DragOverEvent) => {
    if (event.over) lastOver.current = event.over;
    onDragOver(event);
  };
  const handleDragEnd = (event: DragEndEvent) => {
    const target = resolveKanbanDropTarget(event, lastOver.current);
    lastOver.current = null;
    const dragged = event.active.data.current;
    const from = dragged?.group;
    const to = target?.data?.group;
    const intoFull =
      target?.data?.statusId !== undefined &&
      target.data.statusId !== dragged?.statusId &&
      columnLimits.isFull(target.data.statusId);
    const intoBand =
      active?.grouping.move !== undefined &&
      canEditTasks &&
      !intoFull &&
      typeof from === "string" &&
      typeof to === "string" &&
      from !== to;
    if (intoBand && target?.data?.type === "column" && target.data.statusId === dragged?.statusId) {
      onDragCancel();
    } else {
      onDragEnd(event);
    }
    if (!intoBand || typeof dragged?.taskId !== "number") return;
    const move = active.grouping.move?.(from, to);
    if (move && !("status" in move)) moveTask({ taskId: dragged.taskId, move });
  };

  const taskStatusesLength = taskStatuses.length;
  // Basis rather than min-width: it is what the collapse animates.
  const columnBasis = cn(
    "grow-0 basis-70 sm:grow",
    taskStatusesLength > 4 ? "sm:basis-80" : "sm:basis-89"
  );

  return (
    <BoardActionsContext.Provider value={boardActions}>
      {onGroupingChange && offered.length > 0 && !editing ? (
        <div className="mb-3 flex justify-end">
          <GroupBySelect
            options={offered.map(({ grouping: each }) => ({ id: each.column, label: each.label }))}
            value={active?.grouping.column ?? null}
            onChange={(id) => onGroupingChange(id === null ? [] : [id])}
          />
        </div>
      ) : null}
      <DndContext
        sensors={sensors}
        collisionDetection={kanbanCollisionDetection}
        onDragStart={onDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
        onDragCancel={onDragCancel}
      >
        <div
          ref={scrollContainerRef}
          className={cn(
            "scrollbar-thin cursor-grab overflow-x-auto pb-4",
            bands && "max-h-[75vh] overflow-y-auto"
          )}
          data-kanban-scroll-container
        >
          {active && bands ? (
            <KanbanBands
              bands={bands}
              grouping={active.grouping}
              statuses={taskStatuses}
              counts={counts}
              fillOf={fillOf}
              collapsedStatusIds={collapsedStatusIds}
              onToggleCollapse={onToggleCollapse}
              canWrite={canReorderTasks}
              view={view}
              columnBasis={columnBasis}
              onArchiveDoneTasks={onArchiveDoneTasks}
              isArchiving={isArchivingDoneTasks}
            />
          ) : (
            <div className="flex gap-4">
              {taskStatuses.map((status) => {
                const isCollapsed = collapsedStatusIds.has(status.id);
                return (
                  <KanbanColumn
                    key={status.id}
                    status={status}
                    tasks={groupedTasks[status.id] ?? []}
                    canWrite={canReorderTasks}
                    view={view}
                    collapsed={isCollapsed}
                    onToggleCollapse={onToggleCollapse}
                    taskCount={groupedTasks[status.id]?.length ?? 0}
                    fill={fillOf(status.id)}
                    className={cn(
                      "max-h-[70vh] min-h-[70vh] shrink-0 transition-[flex-basis,flex-grow] duration-200",
                      isCollapsed ? "grow-0 basis-12" : columnBasis
                    )}
                    onArchiveDoneTasks={onArchiveDoneTasks}
                    isArchiving={isArchivingDoneTasks}
                  />
                );
              })}
            </div>
          )}
        </div>
        <DragOverlay>
          {activeTask ? <TaskDragOverlay task={activeTask} card={card} /> : null}
        </DragOverlay>
      </DndContext>
    </BoardActionsContext.Provider>
  );
};

// Prefer pointer-over targets to avoid snapping tasks into neighboring columns.
const kanbanCollisionDetection: CollisionDetection = (args) => {
  const pointerIntersections = pointerWithin(args);
  if (pointerIntersections.length > 0) {
    const prioritized = [...pointerIntersections].sort((a, b) => {
      const aType = getDroppableType(args.droppableContainers, a.id);
      const bType = getDroppableType(args.droppableContainers, b.id);

      if (aType === bType) {
        return 0;
      }
      if (aType === "task") {
        return -1;
      }
      if (bType === "task") {
        return 1;
      }
      return 0;
    });
    return prioritized;
  }
  return closestCorners(args);
};

const getDroppableType = (
  containers: DroppableContainer[],
  id: UniqueIdentifier
): string | undefined => containers.find((container) => container.id === id)?.data.current?.type;

const TaskDragOverlay = ({ task, card }: { task: TaskListRead; card: LayoutNode }) => {
  const { t } = useTranslation("projects");
  // The thing being dragged is the card, so it shows what the card names.
  const shows = (fieldId: string) => namesField(card, fieldId);
  return (
    <div className="w-64 space-y-3 rounded-lg border bg-card p-3 shadow-lg">
      <div className="space-y-1">
        <p className="font-medium">{task.title}</p>
        {shows("description") && task.description_excerpt ? (
          <p className="line-clamp-2 text-muted-foreground text-xs">
            <MentionText text={task.description_excerpt} disableLink />
          </p>
        ) : null}
      </div>
      <div className="space-y-1 text-muted-foreground text-xs">
        {shows("assignees") && task.assignees.length > 0 ? (
          <TaskAssigneeList assignees={task.assignees} className="text-xs" />
        ) : null}
        {shows("dueDate") && task.due_date ? (
          <p>{t("kanban.due", { date: formatDateTime(task.due_date) })}</p>
        ) : null}
      </div>
      {shows("checklist") ? <TaskChecklistProgress progress={task.checklist_progress} /> : null}
      {shows("subtasks") ? (
        <TaskChecklistProgress of="subtasks" progress={task.subtask_progress} />
      ) : null}
      {shows("priority") ? (
        <Badge variant={priorityVariant[task.priority]}>
          {t("kanban.priority", { priority: task.priority.replace("_", " ") })}
        </Badge>
      ) : null}
    </div>
  );
};

// Module-level so its identity is stable; the hook re-seeds defaults whenever
// this array's contents change.

const useHorizontalDragScroll = (ref: React.RefObject<HTMLDivElement | null>) => {
  useEffect(() => {
    const container = ref.current;
    if (!container) {
      return;
    }
    let isDragging = false;
    let startX = 0;
    let scrollStart = 0;
    let pointerId: number | null = null;

    // An icon inside a control is an SVG element, not an HTML one.
    const shouldIgnoreEvent = (target: EventTarget | null) => {
      if (!(target instanceof Element)) {
        return false;
      }
      return Boolean(target.closest('[data-kanban-scroll-lock="true"]'));
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) {
        return;
      }
      if (shouldIgnoreEvent(event.target)) {
        return;
      }
      isDragging = true;
      pointerId = event.pointerId;
      startX = event.clientX;
      scrollStart = container.scrollLeft;
      container.setPointerCapture(event.pointerId);
      container.style.cursor = "grabbing";
      // Suppress the browser's native text-selection drag while we're
      // pan-scrolling, otherwise the user smears a selection across every
      // card their pointer moves over.
      container.style.userSelect = "none";
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (!isDragging || pointerId !== event.pointerId) {
        return;
      }
      const delta = event.clientX - startX;
      container.scrollLeft = scrollStart - delta;
    };

    const stopDragging = () => {
      if (!isDragging) {
        return;
      }
      isDragging = false;
      if (pointerId !== null) {
        try {
          container.releasePointerCapture(pointerId);
        } catch {
          // ignore
        }
      }
      pointerId = null;
      container.style.cursor = "";
      container.style.userSelect = "";
    };

    container.addEventListener("pointerdown", handlePointerDown);
    container.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("pointerup", stopDragging);
    container.addEventListener("pointerleave", stopDragging);
    container.addEventListener("pointercancel", stopDragging);

    return () => {
      container.removeEventListener("pointerdown", handlePointerDown);
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerup", stopDragging);
      container.removeEventListener("pointerleave", stopDragging);
      container.removeEventListener("pointercancel", stopDragging);
    };
  }, [ref]);
};

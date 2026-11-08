import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Archive, ChevronLeft, ChevronRight, SquareCheckBig } from "lucide-react";
import type { IconName } from "lucide-react/dynamic";
import { memo, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { TASK_CARD } from "@/lib/layouts/tasks";
import { Button } from "@/ui/button";
import { Icon } from "@/ui/icon-picker";
import { type LayoutContext, LayoutTree } from "@/ui/layouts/tree";
import { cn } from "@/ui/lib/utils";

const VIRTUALIZE_THRESHOLD = 20;
const CARD_ESTIMATE_HEIGHT = 140;
const VIRTUALIZER_OVERSCAN = 3;

/** A limited column's open tasks, counted by the server, and its limit. */
export type ColumnFill = { count: number; limit: number };

interface KanbanColumnProps {
  status: TaskStatusRead;
  tasks: TaskListRead[];
  canWrite: boolean;
  /** What every card on the board shares, made once for the board. */
  view: LayoutContext;
  collapsed: boolean;
  onToggleCollapse: (statusId: number) => void;
  taskCount: number;
  /** Where the column is limited. */
  fill?: ColumnFill;
  className?: string;
  onArchiveDoneTasks?: (statusId: number) => void;
  isArchiving?: boolean;
}

export const KanbanColumn = ({
  status,
  tasks,
  canWrite,
  view,
  collapsed,
  onToggleCollapse,
  taskCount,
  fill,
  className,
  onArchiveDoneTasks,
  isArchiving,
}: KanbanColumnProps) => {
  return (
    <div
      className={cn(
        "flex h-full flex-col overflow-hidden rounded-lg border bg-card shadow-sm transition-colors",
        collapsed && "items-center text-center",
        className
      )}
    >
      <div
        aria-hidden="true"
        className="h-1 w-full shrink-0"
        style={{ backgroundColor: status.color }}
      />
      {collapsed ? (
        <CollapsedHeader
          status={status}
          taskCount={taskCount}
          fill={fill}
          onToggleCollapse={onToggleCollapse}
        />
      ) : (
        <ExpandedHeader
          status={status}
          taskCount={taskCount}
          fill={fill}
          onToggleCollapse={onToggleCollapse}
        />
      )}
      <KanbanCards
        statusId={status.id}
        tasks={tasks}
        canWrite={canWrite}
        view={view}
        collapsed={collapsed}
        className={cn(
          "h-full w-full transition-colors",
          collapsed
            ? "flex flex-1 items-center justify-center px-2"
            : "scrollbar-thin flex-1 space-y-3 overflow-y-auto p-3 pr-2"
        )}
      />
      {!collapsed && status.category === "done" && onArchiveDoneTasks && (
        <ArchiveDoneButton
          statusId={status.id}
          onArchiveDoneTasks={onArchiveDoneTasks}
          isArchiving={isArchiving}
        />
      )}
    </div>
  );
};

/** A card's sortable id: a task with a card in several bands has one each. */
const cardId = (task: TaskListRead, group?: string) =>
  group === undefined ? task.id.toString() : `${task.id}::${group}`;

/**
 * The cards of a column, or of one band's cell in it: where a card dropped
 * there goes, holding only the cards near the view once there are many.
 */
export const KanbanCards = ({
  statusId,
  group,
  tasks,
  canWrite,
  view,
  collapsed,
  className,
}: {
  statusId: number;
  /** The band they are in, on a grouped board. */
  group?: string;
  tasks: TaskListRead[];
  canWrite: boolean;
  view: LayoutContext;
  collapsed: boolean;
  className: string;
}) => {
  const { t } = useTranslation("projects");
  const { setNodeRef: setDroppableRef, isOver } = useDroppable({
    id: group === undefined ? `column-${statusId}` : `cell-${statusId}-${group}`,
    data: { type: "column", statusId, group },
  });

  const enableVirtualization = tasks.length > VIRTUALIZE_THRESHOLD;
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  const mergedRef = useCallback(
    (el: HTMLDivElement | null) => {
      setDroppableRef(el);
      scrollContainerRef.current = el;
    },
    [setDroppableRef]
  );

  const virtualizer = useVirtualizer({
    count: tasks.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => CARD_ESTIMATE_HEIGHT,
    overscan: VIRTUALIZER_OVERSCAN,
    enabled: enableVirtualization,
  });

  const virtualItems = enableVirtualization ? virtualizer.getVirtualItems() : [];
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const paddingBottom =
    virtualItems.length > 0
      ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
      : 0;

  const taskIds = tasks.map((task) => cardId(task, group));

  return (
    <div ref={mergedRef} className={cn(className, isOver ? "bg-muted/40" : null)}>
      {collapsed ? (
        // A band's cell of a folded column is only somewhere to drop.
        group === undefined ? (
          <span className="text-muted-foreground text-xs">{t("kanban.dropHere")}</span>
        ) : null
      ) : tasks.length === 0 ? (
        <p className={cn("text-muted-foreground text-sm", group !== undefined && "sr-only")}>
          {t("kanban.noTasks")}
        </p>
      ) : (
        <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
          {enableVirtualization ? (
            <>
              {paddingTop > 0 && <div style={{ height: paddingTop }} />}
              {virtualItems.map((virtualRow) => {
                const task = tasks[virtualRow.index];
                return canWrite ? (
                  <KanbanTaskCardSortable
                    key={task.id}
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    task={task}
                    view={view}
                    group={group}
                  />
                ) : (
                  <KanbanTaskCardPlain
                    key={task.id}
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    task={task}
                    view={view}
                  />
                );
              })}
              {paddingBottom > 0 && <div style={{ height: paddingBottom }} />}
            </>
          ) : (
            tasks.map((task) => (
              <KanbanTaskCard
                key={task.id}
                task={task}
                canWrite={canWrite}
                view={view}
                group={group}
              />
            ))
          )}
        </SortableContext>
      )}
    </div>
  );
};

/** Archiving a done column's tasks, at the foot of the column. */
export const ArchiveDoneButton = ({
  statusId,
  onArchiveDoneTasks,
  isArchiving,
}: {
  statusId: number;
  onArchiveDoneTasks: (statusId: number) => void;
  isArchiving?: boolean;
}) => {
  const { t } = useTranslation(["projects", "common"]);
  return (
    <div className="border-t p-2" data-kanban-scroll-lock="true">
      <Button
        variant="ghost"
        size="sm"
        className="w-full text-xs"
        onClick={() => onArchiveDoneTasks(statusId)}
        disabled={isArchiving}
      >
        <Archive className="h-3.5 w-3.5" />
        {isArchiving ? t("common:toolSettings.archive.archiving") : t("kanban.archiveDone")}
      </Button>
    </div>
  );
};

/** How many tasks a column header counts: a limited column's open tasks
 *  against its limit, marked once it is full; else what the board shows. */
const ColumnCount = ({
  taskCount,
  fill,
  compact = false,
}: {
  taskCount: number;
  fill?: ColumnFill;
  /** A folded column's, which has room for the numbers alone. */
  compact?: boolean;
}) => {
  const { t } = useTranslation("projects");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-muted-foreground text-xs",
        fill && fill.count >= fill.limit && "font-medium text-warning"
      )}
      title={fill ? t("kanban.limitTitle", { limit: fill.limit }) : undefined}
    >
      <SquareCheckBig className="h-3 w-3" />{" "}
      {fill
        ? t("kanban.limitCount", { count: fill.count, limit: fill.limit })
        : compact
          ? taskCount
          : t("kanban.taskCount", { count: taskCount })}
    </span>
  );
};

export const ExpandedHeader = ({
  status,
  taskCount,
  fill,
  onToggleCollapse,
}: {
  status: TaskStatusRead;
  taskCount: number;
  fill?: ColumnFill;
  onToggleCollapse: (statusId: number) => void;
}) => {
  const { t } = useTranslation("projects");
  return (
    <div
      className="sticky top-0 z-20 flex items-center justify-between gap-2 border-b bg-card px-3 py-2"
      data-kanban-scroll-lock="true"
    >
      <div className="flex min-w-0 items-center gap-2">
        <Icon
          name={status.icon as IconName}
          style={{ color: status.color }}
          className="h-6 w-6 shrink-0"
        />
        <div className="min-w-0">
          <p className="truncate font-semibold text-lg leading-none">{status.name}</p>
          <ColumnCount taskCount={taskCount} fill={fill} />
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0 text-muted-foreground"
        onClick={() => onToggleCollapse(status.id)}
        aria-label={t("kanban.collapse", { name: status.name })}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
    </div>
  );
};

export const CollapsedHeader = ({
  status,
  taskCount,
  fill,
  onToggleCollapse,
}: {
  status: TaskStatusRead;
  taskCount: number;
  fill?: ColumnFill;
  onToggleCollapse: (statusId: number) => void;
}) => {
  const { t } = useTranslation("projects");
  return (
    <div className="flex flex-col items-center gap-3 py-4" data-kanban-scroll-lock="true">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-7 w-7 text-muted-foreground"
        onClick={() => onToggleCollapse(status.id)}
        aria-label={t("kanban.expand", { name: status.name })}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      <Icon name={status.icon as IconName} style={{ color: status.color }} className="h-4 w-4" />
      <div className="flex h-16 items-center justify-center">
        <span className="rotate-90 whitespace-nowrap font-semibold text-muted-foreground text-xs tracking-wide">
          {status.name}
        </span>
      </div>
      <ColumnCount taskCount={taskCount} fill={fill} compact />
    </div>
  );
};

// --- Sortable card (with DnD, used in virtualized mode) ---

interface KanbanTaskCardVirtualProps {
  task: TaskListRead;
  view: LayoutContext;
  "data-index": number;
  group?: string;
}

const KanbanTaskCardSortable = memo(
  function KanbanTaskCardSortable({
    task,
    view,
    "data-index": dataIndex,
    group,
    ref,
  }: KanbanTaskCardVirtualProps & { ref?: React.Ref<HTMLDivElement> }) {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
      id: cardId(task, group),
      data: { type: "task", statusId: task.task_status_id, taskId: task.id, group },
    });

    const mergedRef = useCallback(
      (el: HTMLDivElement | null) => {
        setNodeRef(el);
        if (typeof ref === "function") {
          ref(el);
        } else if (ref && typeof ref === "object") {
          (ref as React.MutableRefObject<HTMLDivElement | null>).current = el;
        }
      },
      [setNodeRef, ref]
    );

    const style = {
      transform: CSS.Transform.toString(transform),
      transition,
      opacity: isDragging ? 0.25 : undefined,
    };

    return (
      <div
        ref={mergedRef}
        data-index={dataIndex}
        style={style}
        {...attributes}
        {...listeners}
        className={cn(
          "space-y-3 rounded-lg border bg-card p-3 shadow-sm",
          task.archived_at !== null && "opacity-50"
        )}
        data-kanban-scroll-lock="true"
      >
        <LayoutTree node={view.card ?? TASK_CARD} item={task} view={view} />
      </div>
    );
  },
  (prev, next) => prev.task === next.task && prev.view === next.view
);

// --- Plain card (no DnD hooks, used in virtualized mode when !canWrite) ---

const KanbanTaskCardPlain = memo(
  function KanbanTaskCardPlain({
    task,
    view,
    "data-index": dataIndex,
    ref,
  }: KanbanTaskCardVirtualProps & { ref?: React.Ref<HTMLDivElement> }) {
    return (
      <div
        ref={ref}
        data-index={dataIndex}
        className={cn(
          "space-y-3 rounded-lg border bg-card p-3 shadow-sm",
          task.archived_at !== null && "opacity-50"
        )}
        data-kanban-scroll-lock="true"
      >
        <LayoutTree node={view.card ?? TASK_CARD} item={task} view={view} />
      </div>
    );
  },
  (prev, next) => prev.task === next.task && prev.view === next.view
);

// --- Original non-virtualized card (used for small lists) ---

interface KanbanTaskCardProps {
  task: TaskListRead;
  canWrite: boolean;
  view: LayoutContext;
  /** The band the card is in, on a grouped board: a task in several bands
   *  has a card in each. */
  group?: string;
}

const KanbanTaskCard = ({ task, canWrite, view, group }: KanbanTaskCardProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: cardId(task, group),
    data: { type: "task", statusId: task.task_status_id, taskId: task.id, group },
    disabled: !canWrite,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.25 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={cn(
        "space-y-3 rounded-lg border bg-card p-3 shadow-sm",
        task.archived_at !== null && "opacity-50"
      )}
      data-kanban-scroll-lock="true"
    >
      <LayoutTree node={view.card ?? TASK_CARD} item={task} view={view} />
    </div>
  );
};

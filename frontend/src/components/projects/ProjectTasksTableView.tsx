import {
  closestCenter,
  DndContext,
  type DndContextProps,
  type DragEndEvent,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
  type DragStartEvent,
  useDraggable,
  useDroppable,
} from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronRight, GripVertical } from "lucide-react";
import type React from "react";
import { createContext, memo, useCallback, useContext, useMemo } from "react";
import { Trans, useTranslation } from "react-i18next";

import type {
  LayoutGrouping,
  ListLayoutDefinitionInputDisplays,
  ListTasksParams,
  TaskListRead,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskAssigneesCell } from "@/components/projects/TaskQuickActions";
import { SortHeader } from "@/components/SortIcon";
import { sharedTaskColumns } from "@/components/tasks/globalTaskColumns";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableRowWrapperProps } from "@/components/ui/data-table";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { TableRow } from "@/components/ui/table";
import { type ColumnLimits, NO_COLUMN_LIMITS } from "@/hooks/useColumnLimits";
import { useProjectTaskTypes } from "@/hooks/useProjects";
import type { useProjectTaskTableState } from "@/hooks/useProjectTaskView";
import { NO_DEFINITIONS, useOwnedDefinitions } from "@/hooks/useProperties";
import { useTaskGroupings } from "@/hooks/useTaskGroupings";
import { useMoveTaskToGroup } from "@/hooks/useTasks";
import { useTaskTypeChange } from "@/hooks/useTaskTypeChange";
import { fieldColumnId } from "@/lib/layouts/columns";
import { columnsOf } from "@/lib/layouts/draft";
import { useProjectLayoutEnv, withDisplays } from "@/lib/layouts/fields";
import { groupRowId, groupRows, NO_GROUP, uniqueTasksFromRows } from "@/lib/layouts/grouping";
import { pluginFields, usePluginsOnItems } from "@/lib/layouts/plugins";
import { taskFields } from "@/lib/layouts/tasks";
import type { AppColumnDef, AppRow } from "@/lib/table";
import { flattenTaskTree, nestTaskRows, type TaskTreeRow, treeParents } from "@/lib/taskTree";
import { cn } from "@/lib/utils";

type ProjectTasksListViewProps = {
  projectId: number;
  /**
   * Initiative the project belongs to. Scopes the property column list so
   * this table surfaces only the initiative's property definitions (global
   * views like My Tasks still use the unbound union).
   */
  initiativeId: number;
  tasks: TaskListRead[];
  /** The list `tasks` are, which its groups are worked out for. */
  listParams: ListTasksParams;
  taskStatuses: TaskStatusRead[];
  sensors: DndContextProps["sensors"];
  canReorderTasks: boolean;
  canEditTaskDetails: boolean;
  taskActionsDisabled: boolean;
  onDragStart: (event: DragStartEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onStatusChange: (taskId: number, taskStatusId: number) => void;
  taskHref: (taskId: number) => string;
  onTaskSelectionChange?: (selectedTasks: TaskListRead[]) => void;
  onExitSelection?: () => void;
  /** How the reader left the table: from {@link useProjectTaskTableState},
   *  held by the section so its export follows the same sort. It seeds the
   *  table once, at mount, so the section keys this component by it. */
  tableState: ReturnType<typeof useProjectTaskTableState>;
  /** The fields the view shows as columns, in order, where it names them. */
  viewColumns?: string[] | null;
  /** How its columns draw each rating, as the layout says. */
  displays?: ListLayoutDefinitionInputDisplays;
  /** The groupings the view offers, in order, where it names them. */
  viewGroupings?: LayoutGrouping[] | null;
  /** How full the board's limited columns are. */
  columnLimits?: ColumnLimits;
  /** The view is being edited. */
  editing?: boolean;
};

type SortableRowContextValue = {
  attributes?: DraggableAttributes;
  listeners?: DraggableSyntheticListeners;
  setActivatorNodeRef?: (element: HTMLElement | null) => void;
  dragDisabled: boolean;
};

const SortableRowContext = createContext<SortableRowContextValue | null>(null);

const useSortableRowContext = () => useContext(SortableRowContext);

/** How a row reads before anything happens to it: a subtask a shade darker
 *  than the task it is under, an archived task faded. */
const rowTone = (task: TaskTreeRow) =>
  cn(task.level > 0 && "bg-black/3 dark:bg-black/20", task.archived_at !== null && "opacity-50");

/**
 * Plain row wrapper — no useSortable hook overhead.
 * Used when no row drags: the table is sorted, grouped by what a drop can't
 * change, or the reader can't change it.
 */
const PlainRowWrapper = ({
  row,
  children,
  virtualStyle,
  virtualIndex,
  measureRef,
}: DataTableRowWrapperProps<TaskTreeRow>) => {
  return (
    <TableRow
      ref={measureRef}
      style={virtualStyle}
      className={rowTone(row.original)}
      data-state={row.getIsSelected() && "selected"}
      data-index={virtualIndex}
    >
      {children}
    </TableRow>
  );
};

/**
 * Sortable row wrapper — calls useSortable hook for DnD support.
 * Only used when DnD is actually possible (no sorting/grouping, has reorder permission).
 */
const SortableRowWrapperInner = ({
  row,
  children,
  virtualStyle,
  virtualIndex,
  measureRef,
}: DataTableRowWrapperProps<TaskTreeRow>) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: row.original.id.toString(),
    data: { type: "list-task" },
  });

  const style: React.CSSProperties = {
    ...virtualStyle,
    transform: CSS.Transform.toString(transform) || virtualStyle?.transform,
    transition,
  };

  const contextValue = useMemo(
    () => ({
      attributes,
      listeners,
      setActivatorNodeRef,
      dragDisabled: false,
    }),
    [attributes, listeners, setActivatorNodeRef]
  );

  const setRefs = useCallback(
    (el: HTMLElement | null) => {
      setNodeRef(el);
      measureRef?.(el);
    },
    [setNodeRef, measureRef]
  );

  return (
    <SortableRowContext.Provider value={contextValue}>
      <TableRow
        ref={setRefs}
        style={style}
        className={cn(rowTone(row.original), isDragging && "bg-muted/60")}
        data-state={row.getIsSelected() && "selected"}
        data-index={virtualIndex}
      >
        {children}
      </TableRow>
    </SortableRowContext.Provider>
  );
};

/**
 * A row of a grouped table that drags into another group: its handle drags it,
 * and the row takes a drop for its group, as the group's header does.
 */
const GroupDragRowWrapper = ({
  row,
  children,
  virtualStyle,
  virtualIndex,
  measureRef,
}: DataTableRowWrapperProps<TaskTreeRow>) => {
  const group = row.original.group ?? NO_GROUP;
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, isDragging } =
    useDraggable({ id: row.id, data: { taskId: row.original.id, group } });
  const drop = useDroppable({ id: `row:${row.id}`, data: { group } });

  const contextValue = useMemo(
    () => ({ attributes, listeners, setActivatorNodeRef, dragDisabled: false }),
    [attributes, listeners, setActivatorNodeRef]
  );
  const setRefs = useCallback(
    (el: HTMLElement | null) => {
      setNodeRef(el);
      drop.setNodeRef(el);
      measureRef?.(el);
    },
    [setNodeRef, drop.setNodeRef, measureRef]
  );

  return (
    <SortableRowContext.Provider value={contextValue}>
      <TableRow
        ref={setRefs}
        style={{
          ...virtualStyle,
          transform: CSS.Translate.toString(transform) || virtualStyle?.transform,
        }}
        className={cn(
          rowTone(row.original),
          isDragging && "relative z-10 bg-muted/60",
          drop.isOver && !isDragging && "bg-primary/10"
        )}
        data-state={row.getIsSelected() && "selected"}
        data-index={virtualIndex}
      >
        {children}
      </TableRow>
    </SortableRowContext.Provider>
  );
};

/** A group's header row, which takes a drop into its group. Its first row
 *  stands for the group, as every row under it is in the group. */
const GroupDropRowWrapper = ({
  row,
  children,
  virtualIndex,
  measureRef,
}: DataTableRowWrapperProps<TaskTreeRow>) => {
  const { setNodeRef, isOver } = useDroppable({
    id: `group:${row.id}`,
    data: { group: row.original.group ?? NO_GROUP },
  });
  const setRefs = useCallback(
    (el: HTMLElement | null) => {
      setNodeRef(el);
      measureRef?.(el);
    },
    [setNodeRef, measureRef]
  );
  return (
    <TableRow
      ref={setRefs}
      className={cn("bg-muted/30", isOver && "bg-primary/10")}
      data-state="grouped"
      data-index={virtualIndex}
    >
      {children}
    </TableRow>
  );
};

const NOT_GROUPED: string[] = [];

const subRowsOf = (row: TaskTreeRow) => row.subRows;

/** How far one level of a task tree sits in from the one above: its fold
 *  control and the gap after it, so a subtask's control is under its
 *  parent's title. */
const TREE_STEP = "1.75rem";

/**
 * A title cell in a task tree: indented by how deep the task is, with the
 * control that folds its parts on the title's line. In a table where any task
 * has parts, every row keeps the control's room, so titles line up.
 */
const TreeTitle = ({
  row,
  nested,
  children,
}: {
  row: AppRow<TaskTreeRow>;
  nested: boolean;
  children: React.ReactNode;
}) => {
  const { t } = useTranslation("tasks");
  const { level, subRows, title } = row.original;
  if (!nested) return children;
  const open = row.getIsExpanded();
  return (
    <div
      className="flex items-start gap-1"
      style={{ paddingInlineStart: `calc(${level} * ${TREE_STEP})` }}
    >
      {subRows?.length ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-6 shrink-0 text-muted-foreground"
          aria-expanded={open}
          aria-label={t(open ? "subtasks.fold" : "subtasks.unfold", { title })}
          onClick={row.getToggleExpandedHandler()}
        >
          <ChevronRight className={cn("transition-transform", open && "rotate-90")} />
        </Button>
      ) : (
        <span className="size-6 shrink-0" aria-hidden="true" />
      )}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
};

const groupDropRow = (props: DataTableRowWrapperProps<TaskTreeRow>) => (
  <GroupDropRowWrapper {...props} />
);

const ProjectTasksTableViewComponent = ({
  projectId,
  initiativeId,
  tasks,
  listParams,
  taskStatuses,
  sensors,
  canReorderTasks,
  canEditTaskDetails,
  taskActionsDisabled,
  onDragStart,
  onDragEnd,
  onDragCancel,
  onStatusChange,
  taskHref,
  onTaskSelectionChange,
  onExitSelection,
  tableState: [tableState, { setGrouping, setSorting }],
  viewColumns,
  displays,
  viewGroupings,
  columnLimits = NO_COLUMN_LIMITS,
  editing = false,
}: ProjectTasksListViewProps) => {
  const { t, i18n } = useTranslation(["projects", "comments", "tasks"]);
  const statusDisabled = !canEditTaskDetails || taskActionsDisabled;
  const env = useProjectLayoutEnv(taskHref);
  const { mutate: moveTask, mutateAsync: moveTaskNow } = useMoveTaskToGroup();
  // A drop into another type asks first for what that type's page requires.
  const typeChange = useTaskTypeChange(projectId, initiativeId);

  // The project's metadata and its initiative's properties, so the column
  // list stays focused.
  const { data: propertyDefinitions = NO_DEFINITIONS } = useOwnedDefinitions({
    initiativeId,
    owner: { kind: "project", id: projectId },
  });
  const plugins = usePluginsOnItems(initiativeId);
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
  const { grouping, sorting } = tableState;
  // What the view offers to group by, the groups each leaves out, and the
  // groups of the one it is grouped by.
  const { offered, active } = useTaskGroupings({
    fields,
    statuses: taskStatuses,
    tasks,
    groupings: viewGroupings,
    kind: "table",
    grouping,
    params: listParams,
    t: env.t,
  });
  const groupings = useMemo(() => offered.map((each) => each.grouping), [offered]);
  const grouped = active?.grouping;
  // What the table's headers group by: the grouping its rows are shaped for.
  const groupedColumn = grouped?.column;
  const tableGrouping = useMemo(
    () => (groupedColumn ? [groupedColumn] : NOT_GROUPED),
    [groupedColumn]
  );
  // The columns the view shows, in its order: its own, or the shipped ones.
  // What the view leaves out is hidden, as are the columns that only group.
  const shown = useMemo(
    () =>
      columnsOf({ columns: viewColumns }, fields)
        .filter((id) => fields.has(id))
        .map(fieldColumnId),
    [viewColumns, fields]
  );
  const columnVisibility = useMemo(
    () => ({
      ...Object.fromEntries(
        [...fields.values()]
          .filter((field) => field.hideable)
          .map(({ id }) => [fieldColumnId(id), shown.includes(fieldColumnId(id))])
      ),
      ...Object.fromEntries(groupings.map(({ column }) => [column, false])),
    }),
    [fields, shown, groupings]
  );

  // Memoize status lookups to avoid repeated array searches
  const statusLookup = useMemo(() => {
    const doneStatus = taskStatuses.find((status) => status.category === "done");
    const inProgressStatus =
      taskStatuses.find((status) => status.category === "in_progress") ??
      taskStatuses.find((status) => status.category === "todo") ??
      taskStatuses.find((status) => status.category === "backlog");
    return { doneStatus, inProgressStatus };
  }, [taskStatuses]);

  // Grouped, a task has a row in each group it is in (one per tag, say) that
  // the view shows; in each, a task's parts are listed under it.
  const rows = useMemo<TaskTreeRow[]>(
    () =>
      nestTaskRows(
        active
          ? groupRows(tasks, active.grouping).filter(
              (row) => !active.hidden.has(row.group ?? NO_GROUP)
            )
          : tasks
      ),
    [active, tasks]
  );
  // In the order the rows are drawn, which a drag shifts them by.
  const sortableItems = useMemo(
    () => flattenTaskTree(rows).map((row) => row.id.toString()),
    [rows]
  );
  // Whether any task is listed under another, which gives every title the
  // room of a fold control.
  const nested = useMemo(() => rows.some((row) => row.subRows !== undefined), [rows]);

  const columns = useMemo<AppColumnDef<TaskTreeRow>[]>(() => {
    const shared = sharedTaskColumns<TaskTreeRow>({
      fields,
      env,
      isPriorityDisabled: () => statusDisabled,
    });
    return [
      {
        id: "drag",
        header: () => <span className="sr-only">{t("table.reorder")}</span>,
        // A handle wherever the row can be dragged: to reorder it, or into
        // another group.
        cell: () => <DragHandleCell />,
        enableSorting: false,
        size: 40,
        enableHiding: false,
      },
      // One hidden column per grouping, which renders a group's header. The
      // table's rows are its groups' while it is the one grouped by.
      ...groupings.map(
        (each): AppColumnDef<TaskTreeRow> => ({
          id: each.column,
          accessorFn: (task) =>
            (each === grouped ? task.group : undefined) ?? each.keys(task)[0] ?? NO_GROUP,
          header: () => <span className="font-medium">{each.label}</span>,
          cell: ({ getValue }) => each.header(getValue<string>()),
          sortFn: (rowA, rowB, columnId) =>
            each.compare(rowA.getValue<string>(columnId), rowB.getValue<string>(columnId)),
          enableHiding: false,
        })
      ),
      {
        id: "completed",
        header: () => <span className="font-medium">{t("table.doneColumn")}</span>,
        cell: ({ row }) => {
          const task = row.original;
          const isDone = task.task_status.category === "done";
          // Checked or unchecked, a task moves into another column, which may
          // be full.
          const target = isDone ? statusLookup.inProgressStatus : statusLookup.doneStatus;
          const full =
            target !== undefined &&
            target.id !== task.task_status_id &&
            columnLimits.isFull(target.id);
          return (
            <Checkbox
              checked={isDone}
              onCheckedChange={(value) => {
                if (statusDisabled) {
                  return;
                }
                const targetStatusId = value
                  ? (statusLookup.doneStatus?.id ?? task.task_status_id)
                  : (statusLookup.inProgressStatus?.id ?? task.task_status_id);
                if (targetStatusId && targetStatusId !== task.task_status_id) {
                  onStatusChange(task.id, targetStatusId);
                }
              }}
              className="h-6 w-6"
              disabled={statusDisabled || full}
              title={full ? t("kanban.statusFull", { name: target.name }) : undefined}
              aria-label={isDone ? t("table.markInProgress") : t("table.markDone")}
            />
          );
        },
        enableSorting: false,
        size: 64,
        enableHiding: false,
      },
      {
        ...shared.title,
        // A task's parts are listed under it, indented, and fold with it.
        cell: (context) => (
          <TreeTitle row={context.row} nested={nested}>
            {typeof shared.title.cell === "function" ? shared.title.cell(context) : null}
          </TreeTitle>
        ),
        // The widest column, so it takes the largest share of whatever space
        // the others leave over.
        size: 360,
      },
      {
        ...shared.assignees,
        cell: ({ row }) => <TaskAssigneesCell task={row.original} canEdit={!statusDisabled} />,
      },
      shared.startDate,
      shared.dueDate,
      shared.priority,
      shared.tags,
      ...shared.properties,
      shared.comments,
      {
        id: "status",
        // Board order, read from the statuses this view holds so a column
        // moved on the board sorts where it now stands.
        accessorFn: (task) =>
          taskStatuses.find((status) => status.id === task.task_status_id)?.position ??
          task.task_status.position,
        header: ({ column }) => <SortHeader column={column} label={t("table.statusColumn")} />,
        sortFn: (rowA, rowB, columnId) =>
          rowA.getValue<number>(columnId) - rowB.getValue<number>(columnId),
        cell: ({ row }) => {
          const task = row.original;
          const activeStatus =
            taskStatuses.find((status) => status.id === task.task_status_id) ?? task.task_status;
          return (
            <Select
              value={String(task.task_status_id)}
              onValueChange={(value) => {
                if (statusDisabled) {
                  return;
                }
                const nextId = Number(value);
                if (Number.isFinite(nextId) && nextId !== task.task_status_id) {
                  onStatusChange(task.id, nextId);
                }
              }}
              disabled={statusDisabled}
            >
              <SelectTrigger
                className="w-40 border-2"
                style={statusTriggerStyle(activeStatus)}
                disabled={statusDisabled}
                aria-label={t("table.statusColumn")}
              >
                <TaskStatusOption status={activeStatus} />
              </SelectTrigger>
              <SelectContent>
                {taskStatuses.map((status) => {
                  const full = status.id !== task.task_status_id && columnLimits.isFull(status.id);
                  return (
                    <SelectItem key={status.id} value={String(status.id)} disabled={full}>
                      <TaskStatusOption status={status} />
                      {full ? (
                        <span className="text-muted-foreground text-xs">{t("kanban.full")}</span>
                      ) : null}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          );
        },
        enableHiding: false,
        // Wide enough for the w-40 status trigger plus cell padding.
        size: 190,
      },
    ];
  }, [
    fields,
    env,
    onStatusChange,
    statusDisabled,
    columnLimits,
    groupings,
    grouped,
    taskStatuses,
    statusLookup,
    nested,
    t,
  ]);
  // The view's columns take the places its columns held, in its order. While
  // the view is edited, each field's header is marked with the field, so the
  // editor finds the column that was clicked.
  const orderedColumns = useMemo(() => {
    const rank = new Map(shown.map((id, index) => [id, index]));
    const listed = columns
      .filter((column) => column.id !== undefined && rank.has(column.id))
      .sort((a, b) => (rank.get(a.id as string) ?? 0) - (rank.get(b.id as string) ?? 0));
    let next = 0;
    const ordered = columns.map((column) =>
      column.id !== undefined && rank.has(column.id) ? listed[next++] : column
    );
    if (!editing) return ordered;
    const fieldOf = new Map(
      [...fields.values()].map((field) => [fieldColumnId(field.id), field.id])
    );
    return ordered.map((column): AppColumnDef<TaskTreeRow> => {
      const fieldId = column.id === undefined ? undefined : fieldOf.get(column.id);
      const { header } = column;
      if (fieldId === undefined || typeof header !== "function") return column;
      return {
        ...column,
        header: (context: Parameters<typeof header>[0]) => (
          <span className="contents" data-layout-node={`column:${fieldId}`}>
            {header(context)}
          </span>
        ),
      } as AppColumnDef<TaskTreeRow>;
    });
  }, [columns, shown, editing, fields]);
  const groupingOptions = useMemo(
    () => groupings.map(({ column, label }) => ({ id: column, label })),
    [groupings]
  );

  // Grouping and sorting each disable drag-to-reorder: a manual order can only
  // be expressed by the table's own row order.
  const dndEnabled = canReorderTasks && sorting.length === 0 && grouping.length === 0;
  // A row moves among the rows listed under the same task, whose order is the
  // list's; dropped beside a row of another level, it stays where it was.
  const parents = useMemo(() => treeParents(rows), [rows]);
  const handleReorder = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (over && parents.get(Number(active.id)) !== parents.get(Number(over.id))) {
        onDragCancel();
        return;
      }
      onDragEnd(event);
    },
    [parents, onDragEnd, onDragCancel]
  );
  // Grouped, a row drags into another group instead, where the grouping can
  // change what puts it there and the reader may change the task.
  const moveEnabled = grouped?.move !== undefined && !statusDisabled;

  // Selection reports rows; a task in several groups holds one row in each,
  // so collapse them back to the tasks themselves.
  const tasksById = useMemo(() => new Map(tasks.map((task) => [task.id, task])), [tasks]);
  const handleSelectionChange = useCallback(
    (selectedRows: TaskTreeRow[]) =>
      onTaskSelectionChange?.(uniqueTasksFromRows(selectedRows, tasksById)),
    [onTaskSelectionChange, tasksById]
  );

  const rowWrapper = useCallback(
    (props: DataTableRowWrapperProps<TaskTreeRow>) => {
      if (dndEnabled) {
        return <SortableRowWrapperInner {...props} />;
      }
      if (moveEnabled) {
        return <GroupDragRowWrapper {...props} />;
      }
      return <PlainRowWrapper {...props} />;
    },
    [dndEnabled, moveEnabled]
  );

  // A row dropped into another group: the one it was dragged from is the one
  // it leaves, so a task in two groups moves out of only that one.
  const handleGroupDrop = useCallback(
    ({ active, over }: DragEndEvent) => {
      const task = tasksById.get(active.data.current?.taskId);
      const from = active.data.current?.group;
      const to = over?.data.current?.group;
      if (!grouped?.move || !task || typeof from !== "string" || typeof to !== "string") return;
      if (from === to) return;
      const move = grouped.move(from, to);
      if ("status" in move) {
        onStatusChange(task.id, move.status);
      } else if ("patch" in move && typeof move.patch.task_type_id === "number") {
        void typeChange.change(task.id, move.patch.task_type_id, (changes) =>
          moveTaskNow({ taskId: task.id, move: { patch: { ...move.patch, ...changes } } })
        );
      } else {
        moveTask({ taskId: task.id, move });
      }
    },
    [grouped, tasksById, onStatusChange, moveTask, moveTaskNow, typeChange]
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={onDragStart}
      onDragEnd={dndEnabled ? handleReorder : handleGroupDrop}
      onDragCancel={onDragCancel}
    >
      <SortableContext
        items={dndEnabled ? sortableItems : []}
        strategy={verticalListSortingStrategy}
      >
        <DataTable
          columns={orderedColumns}
          data={rows}
          enableVirtualization
          // The screen below the page's header, but never so short that a
          // landscape phone shows the column headings and no rows.
          virtualContainerHeight="h-[max(calc(100dvh-20rem),20rem)]"
          virtualRowHeight={52}
          groupingOptions={groupingOptions}
          // The layout editor offers it above the preview.
          groupingControl={!editing}
          columnVisibility={columnVisibility}
          onSortingChange={setSorting}
          grouping={tableGrouping}
          onGroupingChange={setGrouping}
          helpText={(table) => {
            const sorting = table.atoms.sorting?.get() ?? [];
            const grouping = table.atoms.grouping?.get() ?? [];
            const disableDnd = sorting.length > 0 || grouping.length > 0;
            return disableDnd ? (
              <div className="text-muted-foreground">
                <Trans
                  i18nKey="table.manualSortDisabled"
                  ns="projects"
                  components={{
                    1: (
                      <Button
                        variant="link"
                        className="px-0 text-base text-foreground"
                        onClick={() => {
                          table.resetSorting();
                          table.resetGrouping();
                        }}
                      />
                    ),
                  }}
                />
              </div>
            ) : null;
          }}
          initialSorting={sorting}
          initialState={{ expanded: true }}
          rowWrapper={rowWrapper}
          groupRowWrapper={moveEnabled ? groupDropRow : undefined}
          enableFilterInput
          filterInputColumnKey="title"
          filterInputPlaceholder={t("table.filterPlaceholder")}
          enableResetSorting
          enableRowSelection
          onRowSelectionChange={handleSelectionChange}
          getRowId={groupRowId}
          getSubRows={subRowsOf}
          onExitSelection={onExitSelection}
        />
      </SortableContext>
      {typeChange.dialog}
    </DndContext>
  );
};

// Memoize the entire table view to prevent re-renders when parent state changes (like composer input)
// Custom comparison focuses on data, not callback references
export const ProjectTasksTableView = memo(
  ProjectTasksTableViewComponent,
  (prevProps, nextProps) => {
    // Only re-render if the data or key flags actually change
    return (
      prevProps.tasks === nextProps.tasks &&
      prevProps.taskStatuses === nextProps.taskStatuses &&
      prevProps.sensors === nextProps.sensors &&
      prevProps.canReorderTasks === nextProps.canReorderTasks &&
      prevProps.canEditTaskDetails === nextProps.canEditTaskDetails &&
      prevProps.taskActionsDisabled === nextProps.taskActionsDisabled &&
      prevProps.initiativeId === nextProps.initiativeId &&
      prevProps.tableState[0] === nextProps.tableState[0] &&
      prevProps.viewColumns === nextProps.viewColumns &&
      prevProps.displays === nextProps.displays &&
      prevProps.viewGroupings === nextProps.viewGroupings &&
      prevProps.columnLimits === nextProps.columnLimits &&
      prevProps.editing === nextProps.editing
      // Note: Intentionally ignoring callback prop changes as they're functionally the same
    );
  }
);

const DragHandleCell = () => {
  const { t } = useTranslation(["projects", "comments", "tasks"]);
  const sortable = useSortableRowContext();
  if (!sortable) {
    return null;
  }
  const { dragDisabled, attributes, listeners, setActivatorNodeRef } = sortable;
  return (
    <button
      type="button"
      className="text-muted-foreground"
      ref={setActivatorNodeRef}
      {...(attributes ?? {})}
      {...(listeners ?? {})}
      disabled={dragDisabled}
      aria-label={t("table.reorderTask")}
    >
      <GripVertical className="h-4 w-4 cursor-grab" />
    </button>
  );
};

import {
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { arrayMove } from "@dnd-kit/sortable";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { AlertTriangle, Archive, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskCreate,
  TaskListRead,
  TaskRead,
  TaskReorderRequest,
  TaskStatusRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  buildTaskCalendarEntries,
  type CalendarEntry,
  type CalendarEntryReschedule,
  CalendarView,
  type CalendarViewMode,
  rescheduledDates,
  type TaskEntryMeta,
} from "@/components/calendar";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolLayoutSelect } from "@/components/initiativeTools/shared/ToolLayoutSelect";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { ToolPresetSelect } from "@/components/initiativeTools/shared/ToolPresetSelect";
import { AddItemDialog } from "@/components/layouts/AddItemDialog";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { ProjectTasksGanttView } from "@/components/projects/ProjectTasksGanttView";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import {
  computeMidpoint,
  isDraggingDown,
  reorderTaskList,
  resolveKanbanDropTarget,
  shouldInsertAfter,
} from "@/components/projects/taskOrdering";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { StatusMessage } from "@/components/StatusMessage";
import { BulkEditTaskTagsDialog } from "@/components/tasks/BulkEditTaskTagsDialog";
import { ExportTasksButton } from "@/components/tasks/ExportTasksButton";
import { TaskBulkEditDialog } from "@/components/tasks/TaskBulkEditDialog";
import { TaskBulkEditPanel } from "@/components/tasks/TaskBulkEditPanel";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useColumnLimits } from "@/hooks/useColumnLimits";
import { useFieldCatalog } from "@/hooks/useFieldCatalog";
import { useInitiative } from "@/hooks/useInitiatives";
import { useProjectTaskTypes } from "@/hooks/useProjects";
import {
  type ProjectViewSearch,
  taskViewSorting,
  useProjectTaskTableState,
  useProjectTaskView,
} from "@/hooks/useProjectTaskView";
import {
  type UpdateTaskVariables,
  useArchiveDoneTasks,
  useBulkArchiveTasks,
  useBulkDeleteTasks,
  useBulkUpdateTasks,
  useCreateTask,
  useReorderTasks,
  useTasks,
  useUpdateTask,
} from "@/hooks/useTasks";
import { instanceTarget } from "@/hooks/useToolLayouts";
import {
  buildTaskConditions,
  buildTaskListParams,
  matchesDueWindow,
  taskFilterCount,
} from "@/lib/filters/taskFilters";
import { isGanttScale } from "@/lib/gantt";
import { activeGrouping, catalogChoices } from "@/lib/layouts/grouping";
import { presetName } from "@/lib/layouts/presets";
import { blankTask, TASK_DETAIL } from "@/lib/layouts/taskLayout";
import type { LayoutNode } from "@/lib/layouts/tree";
import { toast } from "@/lib/mascotToast";
import { getProjectColor } from "@/lib/projectColor";
import { getItem, setItem } from "@/lib/storage";
import { taskReadToListRow } from "@/lib/taskUtils";
import { browserTimezone } from "@/lib/timezones";

/** A status change on screen whose request has not answered yet. */
type PendingStatus = { vars: UpdateTaskVariables; status: TaskStatusRead };

type ProjectTasksSectionProps = {
  projectId: number;
  /**
   * Initiative the project belongs to. Threaded down to the table view so
   * programmatic property columns stay scoped to this initiative's
   * definitions.
   */
  initiativeId: number;
  taskStatuses: TaskStatusRead[];
  canEditTaskDetails: boolean;
  projectIsArchived: boolean;
  taskHref: (taskId: number) => string;
  initialComposerOpen?: boolean;
  onComposerOpenChange?: (isOpen: boolean) => void;
};

export const ProjectTasksSection = ({
  projectId,
  initiativeId,
  taskStatuses,
  canEditTaskDetails,
  projectIsArchived,
  taskHref,
  initialComposerOpen,
  onComposerOpenChange,
}: ProjectTasksSectionProps) => {
  const { t } = useTranslation(["projects", "common", "errors"]);
  // Nothing is exported from an initiative that keeps its content in.
  const keepsContentIn = Boolean(useInitiative(initiativeId).data?.keep_content_in);
  const communityId = useActiveCommunityId();
  const sortedTaskStatuses = useMemo(() => {
    return [...taskStatuses].sort((a, b) => {
      if (a.position === b.position) {
        return a.id - b.id;
      }
      return a.position - b.position;
    });
  }, [taskStatuses]);
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as ProjectViewSearch;
  const {
    filtersLoaded,
    layoutsLoaded,
    layoutsFailed,
    retryLayouts,
    retryingLayouts,
    layouts,
    layout,
    kind,
    presets,
    preset,
    filtered,
    appliedSpec,
    sorting,
    setFilters,
    setSorting,
    pickPreset,
    rememberLayout,
    mode,
    setMode,
    grouping,
    setGrouping,
    exportFields,
  } = useProjectTaskView({ projectId, taskStatuses, search });

  /** Show the `next` list layout, and come back to it. The URL names it, so
   *  a link opens the same layout for whoever follows it. */
  const selectLayout = useCallback(
    (next: string) => {
      const chosen = layouts.find((each) => each.kind === next);
      if (!chosen) return;
      rememberLayout(chosen.kind);
      // replace: the back button is for moving between resources, not for
      // stepping back through layouts.
      // resetScroll: naming the layout in the URL is bookkeeping about the
      // list you are already looking at — the router's default would throw
      // you back to the top of it on every pick.
      void navigate({
        to: ".",
        // A preset is one layout's: another starts from this person's own.
        search: ((prev: Record<string, unknown>) => ({
          ...prev,
          layout: chosen.kind,
          preset: undefined,
        })) as never,
        replace: true,
        resetScroll: false,
      });
    },
    [layouts, rememberLayout, navigate]
  );

  const layoutOptions = useMemo(
    () =>
      layouts.map((each) => ({
        slug: each.kind,
        name: t(listLayoutLooks[each.kind].labelKey as never),
        icon: listLayoutLooks[each.kind].icon,
      })),
    [layouts, t]
  );

  const presetOptions = useMemo(
    () => presets.map((each) => ({ slug: each.slug, name: presetName(each, t as never) })),
    [presets, t]
  );

  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Badges the filter button while the panel is closed. Archived-included
  // counts: it widens what the list shows, which is as much a departure from
  // the default as narrowing it.
  const activeFilterCount = taskFilterCount(appliedSpec);

  const clearFilters = useCallback(() => setFilters(null), [setFilters]);

  const [localOverride, setLocalOverride] = useState<TaskListRead[] | null>(null);
  const [isComposerOpen, setIsComposerOpen] = useState(initialComposerOpen ?? false);
  // An archived project takes no new tasks until it is unarchived.
  const canAddTasks = canEditTaskDetails && !projectIsArchived;
  useEffect(() => {
    if (initialComposerOpen) {
      setIsComposerOpen(true);
    }
  }, [initialComposerOpen]);
  useEffect(() => {
    onComposerOpenChange?.(isComposerOpen);
  }, [isComposerOpen, onComposerOpenChange]);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canAddTasks ? { run: () => setIsComposerOpen(true), label: t("tasks.addTask") } : null
  );

  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [selectedTasks, setSelectedTasks] = useState<TaskListRead[]>([]);
  // A selection belongs to the list it was made in: switching project or
  // layout starts with none.
  const selectionList = `${projectId}:${kind}`;
  const [selectedIn, setSelectedIn] = useState(selectionList);
  if (selectedIn !== selectionList) {
    setSelectedIn(selectionList);
    setSelectedTasks([]);
  }

  // An export lists the tasks in the order the reader sees them: the table's
  // own sort while it is showing, and the project's order in every other
  // layout.
  const tableState = useProjectTaskTableState(grouping, setGrouping, sorting, setSorting);
  // What an export carries of this person's view: its order, what it is
  // grouped by less the groups the layout leaves out, the table's columns and
  // the task page's parts.
  const { groupings: groupingCatalog } = useFieldCatalog("tasks");
  const exportView = useMemo(() => {
    const fields = taskViewSorting(kind, sorting);
    const grouped = activeGrouping(
      layout?.definition.groupings,
      kind,
      grouping,
      catalogChoices(groupingCatalog)
    );
    return {
      ...(fields.length > 0 && { sorting: fields }),
      ...(grouped && {
        group_by: grouped.field,
        bucket: grouped.bucket,
        hidden_groups: grouped.hidden,
      }),
      columns: exportFields.columns,
      detail: exportFields.detail,
      tz: browserTimezone(),
    };
  }, [kind, sorting, grouping, layout, groupingCatalog, exportFields]);
  const [isBulkEditDialogOpen, setIsBulkEditDialogOpen] = useState(false);
  const [isBulkEditTagsDialogOpen, setIsBulkEditTagsDialogOpen] = useState(false);
  const [isArchiveDialogOpen, setIsArchiveDialogOpen] = useState(false);
  const [archiveDialogStatusId, setArchiveDialogStatusId] = useState<number | undefined>(undefined);
  const lastKanbanOverRef = useRef<DragOverEvent["over"] | null>(null);

  const { user } = useAuth();
  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;
  // How much of the calendar the Gantt or the calendar shows is one choice in
  // this person's view of the project.
  const ganttScale = isGanttScale(mode) ? mode : "week";
  const calendarViewMode = (mode ?? "month") as CalendarViewMode;
  const [calendarFocusDate, setCalendarFocusDate] = useState(() => new Date());

  // Fetch tasks with server-side filtering (page_size=0 fetches all for
  // drag-and-drop). buildTaskListParams is shared with the route loader's
  // prefetch and the CSV export, so all three ask the same question.
  const taskListParams = useMemo(
    () => buildTaskListParams(appliedSpec, { projectId }),
    [appliedSpec, projectId]
  );

  const tasksQuery = useTasks(taskListParams, {
    enabled: Number.isFinite(projectId) && filtersLoaded && layoutsLoaded,
  });

  const projectTasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const collapsedStorageKey = useMemo(
    () => (Number.isFinite(projectId) ? `project:${projectId}:kanban-collapsed` : null),
    [projectId]
  );
  const [collapsedStatuses, setCollapsedStatuses] = useState<Set<number>>(new Set());

  const statusLookup = useMemo(() => {
    const map = new Map<number, TaskStatusRead>();
    sortedTaskStatuses.forEach((status) => {
      map.set(status.id, status);
    });
    return map;
  }, [sortedTaskStatuses]);

  const defaultStatusId = useMemo(() => {
    if (sortedTaskStatuses.length === 0) {
      return null;
    }
    const explicit = sortedTaskStatuses.find((status) => status.is_default);
    return explicit?.id ?? sortedTaskStatuses[0]?.id ?? null;
  }, [sortedTaskStatuses]);

  useEffect(() => {
    setLocalOverride(null);
  }, [projectTasks]);

  useEffect(() => {
    if (!collapsedStorageKey) {
      return;
    }
    try {
      const raw = getItem(collapsedStorageKey);
      if (raw) {
        const parsed: number[] = JSON.parse(raw);
        setCollapsedStatuses(new Set(parsed));
      }
    } catch {
      setCollapsedStatuses(new Set());
    }
  }, [collapsedStorageKey]);

  const persistCollapsedStatuses = useCallback(
    (next: Set<number>) => {
      if (!collapsedStorageKey) {
        return;
      }
      setItem(collapsedStorageKey, JSON.stringify(Array.from(next)));
    },
    [collapsedStorageKey]
  );

  const toggleStatusCollapse = useCallback(
    (statusId: number) => {
      setCollapsedStatuses((prev) => {
        const next = new Set(prev);
        if (next.has(statusId)) {
          next.delete(statusId);
        } else {
          next.add(statusId);
        }
        persistCollapsedStatuses(next);
        return next;
      });
    },
    [persistCollapsedStatuses]
  );

  const createTask = useCreateTask({
    onSuccess: (newTask) => {
      setLocalOverride((prev) => [
        ...(prev ?? projectTasks),
        taskReadToListRow(newTask, communityId),
      ]);
      toast.success(t("tasks.taskCreated"));
    },
  });

  // How full the board's limited columns are, which every way a person puts
  // a task into a column here holds to.
  const columnLimits = useColumnLimits(projectId);
  const refuseFull = useCallback(
    (taskStatusId: number, entering = 1) => {
      if (!columnLimits.isFull(taskStatusId, entering)) return false;
      toast.error(t("errors:TASK_STATUS_AT_LIMIT"));
      return true;
    },
    [columnLimits, t]
  );

  // A task is added to the project's default status unless another is picked,
  // or that column is full and another isn't.
  const projectDefault = sortedTaskStatuses.find((status) => status.id === defaultStatusId);
  const defaultStatus =
    projectDefault && columnLimits.isFull(projectDefault.id)
      ? (sortedTaskStatuses.find((status) => !columnLimits.isFull(status.id)) ?? projectDefault)
      : projectDefault;
  // And of the project's default type unless another is picked.
  const taskTypes = useProjectTaskTypes(projectId).data;
  const defaultType = taskTypes?.find((type) => type.is_default) ?? taskTypes?.[0];
  const leaving = useRef(false);
  const neverAsks = useCallback(async () => null, []);

  /**
   * Whether an updated row still belongs in the filtered list.
   *
   * Covers the filters that can be decided from the row on its own — status,
   * its category, and the due window. Anything needing data the row does not
   * carry (tags, properties) is left to the refetch; the point is that an edit
   * which moves a task out of view does not leave it sitting there until the
   * round trip lands.
   */
  const stillMatchesFilters = useCallback(
    (task: Pick<TaskListRead, "task_status_id" | "task_status" | "due_date">) => {
      const { status_ids, status_categories, due } = appliedSpec;
      if (status_ids.length > 0 && !status_ids.includes(task.task_status_id)) return false;
      if (status_categories.length > 0 && !status_categories.includes(task.task_status.category)) {
        return false;
      }
      return matchesDueWindow(task.due_date, due);
    },
    [appliedSpec]
  );

  // Patch the locally-overridden task list with a server-confirmed update so
  // the board/calendar reflects it immediately, dropping the task when it no
  // longer belongs.
  const applyTaskUpdateToLocal = useCallback(
    (updatedTask: TaskRead) => {
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        if (!base.length) return prev;
        if (stillMatchesFilters(updatedTask)) {
          return base.map((task) =>
            task.id === updatedTask.id ? taskReadToListRow(updatedTask, communityId, task) : task
          );
        }
        return base.filter((task) => task.id !== updatedTask.id);
      });
    },
    [projectTasks, stillMatchesFilters, communityId]
  );

  // Status changes shown before the server confirms them, keyed by task. Each
  // entry keeps the request that made it, and only that request's reply
  // retires it: an older reply for the same task (ticked, then unticked) does
  // not overwrite the newer choice, and a failure drops the entry, which puts
  // the row back. The ref is what reply callbacks read, since an earlier
  // request keeps the callbacks of the render that sent it.
  const pendingStatusesRef = useRef<ReadonlyMap<number, PendingStatus>>(new Map());
  const [pendingStatuses, setPendingStatuses] = useState(pendingStatusesRef.current);
  const writePendingStatuses = useCallback((update: (next: Map<number, PendingStatus>) => void) => {
    const next = new Map(pendingStatusesRef.current);
    update(next);
    pendingStatusesRef.current = next;
    setPendingStatuses(next);
  }, []);

  // Silent like the reschedule below: ticking off a run of tasks should not
  // stack a toast per row. The checkbox and completion feedback confirm it.
  const { mutate: mutateTaskStatus } = useUpdateTask({
    onSuccess: (updatedTask, vars) => {
      const pending = pendingStatusesRef.current.get(vars.taskId);
      // A newer change to this task is still on its way and will settle it.
      if (pending && pending.vars !== vars) return;
      applyTaskUpdateToLocal(updatedTask);
    },
    onSettled: (_data, _error, vars) => {
      if (pendingStatusesRef.current.get(vars.taskId)?.vars !== vars) return;
      writePendingStatuses((next) => next.delete(vars.taskId));
    },
  });

  // A Gantt bar dragged: patches the local list so the bar stays where it was
  // dropped, and stays silent (no per-drag toast), as the calendars do.
  const rescheduleTaskDates = useUpdateTask({
    onSuccess: applyTaskUpdateToLocal,
  });

  const bulkUpdateTasks = useBulkUpdateTasks({
    onSuccess: (updatedTasks) => {
      const count = updatedTasks.length;
      toast.success(t("tasks.bulkUpdated", { count }));
      // setSelectedTasks([]);
      setIsBulkEditDialogOpen(false);
      setLocalOverride(null);
    },
  });

  const bulkDeleteTasks = useBulkDeleteTasks({
    onSuccess: (_data, taskIds) => {
      const count = taskIds.length;
      toast.success(t("tasks.bulkDeleted", { count }));
      setSelectedTasks([]);
      setLocalOverride(null);
    },
  });

  const bulkArchiveTasks = useBulkArchiveTasks({
    onSuccess: (updatedTasks) => {
      const count = updatedTasks.length;
      toast.success(t("tasks.archivedSuccess", { count }));
      setSelectedTasks([]);
      setLocalOverride(null);
    },
  });

  const archiveDoneTasks = useArchiveDoneTasks({
    onSuccess: (data) => {
      const count = data.archived_count;
      if (count === 0) {
        toast.info(t("tasks.noDoneTasksToArchive"));
      } else {
        toast.success(t("tasks.archivedSuccess", { count }));
      }
    },
  });

  const { mutate: persistTaskOrderMutate, isPending: isPersistingOrder } = useReorderTasks();

  // Status changes stay open while earlier ones are in flight, so a run of
  // tasks can be ticked off without waiting on each.
  const taskActionsDisabled = isPersistingOrder;
  const canReorderTasks = canEditTaskDetails && !isPersistingOrder;

  const tasks = useMemo(() => {
    const base = localOverride ?? projectTasks;
    if (pendingStatuses.size === 0) return base;
    return base.flatMap((task) => {
      const pending = pendingStatuses.get(task.id);
      if (!pending) return [task];
      const row = { ...task, task_status_id: pending.status.id, task_status: pending.status };
      return stillMatchesFilters(row) ? [row] : [];
    });
  }, [localOverride, projectTasks, pendingStatuses, stillMatchesFilters]);

  // Show the new status at once and send it; the completion feedback goes out
  // with the click rather than the reply.
  const changeTaskStatus = useCallback(
    (taskId: number, taskStatusId: number) => {
      const status = statusLookup.get(taskStatusId);
      const current = tasks.find((task) => task.id === taskId);
      if (current?.task_status_id !== taskStatusId && refuseFull(taskStatusId)) return;
      const vars: UpdateTaskVariables = {
        taskId,
        data: { task_status_id: taskStatusId },
        statusChange:
          status && current
            ? { from: current.task_status.category, to: status.category }
            : undefined,
      };
      if (status) {
        writePendingStatuses((next) => next.set(taskId, { vars, status }));
      }
      mutateTaskStatus(vars);
    },
    [statusLookup, tasks, writePendingStatuses, mutateTaskStatus, refuseFull]
  );
  const activeTask = useMemo(
    () => projectTasks.find((task) => task.id === activeTaskId) ?? null,
    [projectTasks, activeTaskId]
  );

  // Due-date windows are applied server-side now (see buildTaskConditions), so
  // the board, the archive count, and the CSV export all agree with the list.
  const groupedTasks = useMemo(() => {
    const groups: Record<number, TaskListRead[]> = {};
    sortedTaskStatuses.forEach((status) => {
      groups[status.id] = [];
    });
    tasks.forEach((task) => {
      if (!groups[task.task_status_id]) {
        groups[task.task_status_id] = [];
      }
      groups[task.task_status_id].push(task);
    });
    return groups;
  }, [tasks, sortedTaskStatuses]);

  // Filtering is entirely server-side now.
  const statusFilteredTasks = tasks;

  // New dates from the Gantt or the calendar. A repeating task asks whether
  // the tasks after it move too.
  const scopePrompt = useScopePrompt();
  const { mutateAsync: writeTaskDates } = rescheduleTaskDates;
  const rescheduleTask = useCallback(
    async (
      task: Pick<TaskListRead, "id" | "recurrence">,
      dates: Pick<TaskUpdate, "start_date" | "due_date">
    ) => {
      const scope = task.recurrence
        ? await scopePrompt.ask("edit", { tool: "tasks", scopes: ["this", "following"] })
        : undefined;
      if (scope === null) return false;
      return writeTaskDates({
        taskId: task.id,
        data: { ...dates, ...(scope ? { scope } : {}) },
      }).then(
        () => true,
        // The mutation says what went wrong; the bar goes back.
        () => false
      );
    },
    [writeTaskDates, scopePrompt.ask]
  );

  // The calendar draws tasks as every calendar does: start and due markers,
  // a same-day span, its tags and its type.
  const typed = (taskTypes?.length ?? 0) > 1;
  const calendarEntries = useMemo(
    () =>
      statusFilteredTasks.flatMap((task): CalendarEntry[] =>
        buildTaskCalendarEntries(task, getProjectColor(task.project_id), canEditTaskDetails, {
          typed,
        })
      ),
    [statusFilteredTasks, canEditTaskDetails, typed]
  );
  const handleCalendarReschedule = useCallback(
    ({ entry, startAt, endAt }: CalendarEntryReschedule) => {
      const meta = entry.meta as Partial<TaskEntryMeta> | undefined;
      const task = meta?.type === "task" ? tasks.find((each) => each.id === meta.taskId) : null;
      if (task) void rescheduleTask(task, rescheduledDates(meta?.kind, startAt, endAt));
    },
    [tasks, rescheduleTask]
  );

  // Count of archivable done tasks (non-archived tasks in done category)
  const archivableDoneTasksCount = useMemo(() => {
    return tasks.filter((task) => task.task_status.category === "done" && task.archived_at === null)
      .length;
  }, [tasks]);

  // Count of archivable tasks per done status
  const archivableCountByStatus = useMemo(() => {
    const counts: Record<number, number> = {};
    sortedTaskStatuses.forEach((status) => {
      if (status.category === "done") {
        counts[status.id] = (groupedTasks[status.id] ?? []).filter(
          (t) => t.archived_at === null
        ).length;
      }
    });
    return counts;
  }, [sortedTaskStatuses, groupedTasks]);

  // Persist a single moved task: compute its fractional midpoint from its new
  // neighbors in the global order and send only that task (not the whole list).
  const persistMove = useCallback(
    (movedTaskId: number, taskStatusId: number, orderedTasks: TaskListRead[]) => {
      if (!Number.isFinite(projectId) || isPersistingOrder) {
        return;
      }
      const insertIndex = orderedTasks.findIndex((task) => task.id === movedTaskId);
      if (insertIndex === -1) {
        return;
      }
      const withoutMoved = orderedTasks.filter((task) => task.id !== movedTaskId);
      const payload: TaskReorderRequest = {
        project_id: projectId,
        items: [
          {
            id: movedTaskId,
            task_status_id: taskStatusId,
            position: computeMidpoint(withoutMoved, insertIndex),
          },
        ],
      };
      persistTaskOrderMutate(payload);
    },
    [projectId, persistTaskOrderMutate, isPersistingOrder]
  );

  useEffect(() => {
    if (!canAddTasks) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || isComposerOpen) {
        return;
      }
      const target = event.target as HTMLElement | null;
      if (target) {
        const tagName = target.tagName;
        if (
          target.isContentEditable ||
          tagName === "INPUT" ||
          tagName === "TEXTAREA" ||
          tagName === "SELECT" ||
          tagName === "BUTTON"
        ) {
          return;
        }
      }
      event.preventDefault();
      setIsComposerOpen(true);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canAddTasks, isComposerOpen]);

  const moveTaskInOrder = useCallback(
    (taskId: number, targetStatusId: number, overTaskId: number | null, insertAfter: boolean) => {
      const targetStatus = statusLookup.get(targetStatusId);
      if (!targetStatus) {
        return;
      }
      let nextState: TaskListRead[] | null = null;
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        const currentTask = base.find((task) => task.id === taskId);
        if (!currentTask) {
          return prev;
        }
        const updatedTask: TaskListRead = {
          ...currentTask,
          task_status_id: targetStatus.id,
          task_status: targetStatus,
        };
        nextState = reorderTaskList(base, updatedTask, overTaskId, insertAfter, targetStatus.id);
        return nextState;
      });
      if (nextState) {
        persistMove(taskId, targetStatus.id, nextState);
      }
    },
    [persistMove, statusLookup, projectTasks]
  );

  const reorderListTasks = useCallback(
    (activeId: number, overId: number) => {
      let nextState: TaskListRead[] | null = null;
      let movedStatusId: number | null = null;
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        const oldIndex = base.findIndex((task) => task.id === activeId);
        const newIndex = base.findIndex((task) => task.id === overId);
        if (oldIndex === -1 || newIndex === -1) {
          return prev;
        }
        movedStatusId = base[oldIndex].task_status_id;
        nextState = arrayMove(base, oldIndex, newIndex);
        return nextState;
      });
      if (nextState && movedStatusId !== null) {
        persistMove(activeId, movedStatusId, nextState);
      }
    },
    [persistMove, projectTasks]
  );

  const mouseSensorConfig = useMemo(() => ({ activationConstraint: { distance: 4 } }), []);
  const touchSensorConfig = useMemo(
    () => ({ activationConstraint: { delay: 200, tolerance: 8 } }),
    []
  );

  const kanbanSensors = useSensors(
    useSensor(MouseSensor, mouseSensorConfig),
    useSensor(TouchSensor, touchSensorConfig)
  );
  const listSensors = useSensors(
    useSensor(MouseSensor, mouseSensorConfig),
    useSensor(TouchSensor, touchSensorConfig)
  );

  const handleTaskDragStart = (event: DragStartEvent) => {
    const taskType = event.active.data.current?.type;
    if (taskType !== "task" && taskType !== "list-task") {
      return;
    }
    // A card on a grouped board is one of the task's, one for each band.
    const id = event.active.data.current?.taskId ?? Number(event.active.id);
    if (Number.isFinite(id)) {
      setActiveTaskId(id);
    }
    lastKanbanOverRef.current = null;
  };

  const handleKanbanDragEnd = (event: DragEndEvent) => {
    if (!canReorderTasks) {
      setActiveTaskId(null);
      lastKanbanOverRef.current = null;
      return;
    }
    const { active } = event;
    const finalOver = resolveKanbanDropTarget(event, lastKanbanOverRef.current);
    const activeId = active.data.current?.taskId ?? Number(active.id);
    const currentTask = Number.isFinite(activeId)
      ? tasks.find((task) => task.id === activeId)
      : undefined;
    if (!finalOver || !currentTask) {
      setActiveTaskId(null);
      lastKanbanOverRef.current = null;
      return;
    }

    const overData = finalOver.data;
    let targetStatusId = currentTask.task_status_id;
    let overTaskId: number | null = null;
    let insertAfter = false;

    if (overData?.type === "task") {
      targetStatusId = overData.statusId ?? targetStatusId;
      const parsed = overData.taskId ?? Number(finalOver.id);
      overTaskId = Number.isFinite(parsed) ? parsed : null;
      if (
        targetStatusId === currentTask.task_status_id &&
        overData.group === active.data.current?.group
      ) {
        // Same column: derive before/after from the cards' current order. This
        // is the reliable arrayMove semantics the list view uses and reaches
        // both the top and bottom slots — the rect heuristic is unreliable here
        // because the sortable strategy shifts cards mid-drag (a drag to the top
        // would snap to the second slot).
        insertAfter = isDraggingDown(tasks, activeId, overTaskId);
      } else {
        // Another column, or another band of a grouped board: there's no
        // order the cards shifted by to compare against, so decide by which
        // half of the target card the dragged card released over. Without
        // this the first slot of the column would be unreachable.
        insertAfter = shouldInsertAfter(active.rect.current.translated, finalOver.rect);
      }
    } else if (overData?.type === "column") {
      targetStatusId = overData.statusId ?? targetStatusId;
    }

    // Released on itself: nothing to persist, but the overlay still has to go.
    const intoFull = targetStatusId !== currentTask.task_status_id && refuseFull(targetStatusId);
    if (
      !intoFull &&
      (targetStatusId !== currentTask.task_status_id || overTaskId !== currentTask.id)
    ) {
      moveTaskInOrder(activeId, targetStatusId, overTaskId, insertAfter);
    }
    setActiveTaskId(null);
    lastKanbanOverRef.current = null;
  };

  const handleKanbanDragOver = (event: DragOverEvent) => {
    if (event.over) {
      lastKanbanOverRef.current = event.over;
    }
  };

  const handleListDragEnd = (event: DragEndEvent) => {
    if (!canReorderTasks) {
      setActiveTaskId(null);
      return;
    }
    const { active, over } = event;
    if (!over) {
      setActiveTaskId(null);
      return;
    }
    const activeId = Number(active.id);
    const overId = Number(over.id);
    if (!Number.isFinite(activeId) || !Number.isFinite(overId) || activeId === overId) {
      return;
    }
    reorderListTasks(activeId, overId);
    setActiveTaskId(null);
  };

  const handleKanbanDragCancel = () => {
    setActiveTaskId(null);
    lastKanbanOverRef.current = null;
  };

  const handleListDragCancel = () => {
    setActiveTaskId(null);
  };

  if (layoutsFailed) {
    return (
      <div className="flex flex-col items-center">
        <StatusMessage
          icon={<AlertTriangle className="size-6" aria-hidden />}
          title={t("layouts.loadError")}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={retryingLayouts}
          onClick={retryLayouts}
        >
          {t("common:tryAgain")}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {scopePrompt.dialog}
      <div className="space-y-4">
        <ToolListToolbar
          heading={
            <h2 className="truncate font-semibold text-xl tracking-tight">
              {t("tasks.projectTasks")}
            </h2>
          }
          filters={{
            open: filtersOpen,
            onOpenChange: setFiltersOpen,
            activeCount: activeFilterCount,
          }}
          // The project's list layouts, this person's filters for each coming
          // with it.
          viewControl={
            <ToolLayoutSelect
              layouts={layoutOptions}
              activeSlug={layout?.kind ?? null}
              modified={filtered}
              onSelect={selectLayout}
              label={t("layouts.label")}
              modifiedLabel={t("filters.modified")}
            />
          }
          trailing={
            /* resumePending: this is the list's single adopter of a stored
               in-flight job (the selection button must not double-handle it). */
            keepsContentIn ? undefined : (
              <ExportTasksButton
                params={{
                  conditions: buildTaskConditions(appliedSpec, { projectId }),
                  include_archived: appliedSpec.include_archived,
                  ...exportView,
                }}
                resumePending
              />
            )
          }
          actions={
            canAddTasks ? (
              <TooltipProvider>
                <Tooltip delayDuration={400}>
                  <TooltipTrigger asChild>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-9"
                      onClick={() => setIsComposerOpen(true)}
                    >
                      <Plus className="h-4 w-4" />
                      {t("tasks.addTask")}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={12}>
                    {t("tasks.enterTooltip")}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : null
          }
        />

        <ToolFilterPanel
          open={filtersOpen}
          onOpenChange={setFiltersOpen}
          onClear={clearFilters}
          activeCount={activeFilterCount}
          // The presets the layout shown offers, which set the filters below.
          leading={
            presetOptions.length > 0 ? (
              <ToolPresetSelect
                presets={presetOptions}
                activeSlug={preset?.slug ?? null}
                onSelect={pickPreset}
                label={t("presets.label")}
                placeholder={t("presets.placeholder")}
              />
            ) : undefined
          }
        >
          <TaskFilters
            scope={{
              kind: "project",
              memberScope: { type: "canOpen", tool: Tool.project, id: projectId },
              statuses: sortedTaskStatuses,
              types: taskTypes,
            }}
            value={appliedSpec}
            onChange={setFilters}
          />
        </ToolFilterPanel>

        {kind === "board" ? (
          <ProjectTasksKanbanView
            projectId={projectId}
            initiativeId={initiativeId}
            taskStatuses={sortedTaskStatuses}
            groupedTasks={groupedTasks}
            listParams={taskListParams}
            collapsedStatusIds={collapsedStatuses}
            canReorderTasks={canReorderTasks}
            canEditTasks={canEditTaskDetails}
            onStatusChange={changeTaskStatus}
            taskHref={taskHref}
            sensors={kanbanSensors}
            activeTask={activeTask}
            onDragStart={handleTaskDragStart}
            onDragOver={handleKanbanDragOver}
            onDragEnd={handleKanbanDragEnd}
            onDragCancel={handleKanbanDragCancel}
            onToggleCollapse={toggleStatusCollapse}
            onArchiveDoneTasks={
              canEditTaskDetails
                ? (statusId) => {
                    setArchiveDialogStatusId(statusId);
                    setIsArchiveDialogOpen(true);
                  }
                : undefined
            }
            isArchivingDoneTasks={archiveDoneTasks.isPending}
            card={layout?.definition.card as LayoutNode | null | undefined}
            displays={layout?.definition.displays}
            columnLimits={columnLimits}
            grouping={grouping}
            onGroupingChange={setGrouping}
            viewGroupings={layout?.definition.groupings}
          />
        ) : null}

        {kind === "table" ? (
          <div className="space-y-4">
            {selectedTasks.length > 0 && canEditTaskDetails && (
              <TaskBulkEditPanel
                selectedTasks={selectedTasks}
                exportParams={
                  keepsContentIn
                    ? undefined
                    : {
                        conditions: [
                          { field: "id", op: "in_", value: selectedTasks.map((t) => t.id) },
                        ],
                        // Selection came from the visible list, which may include
                        // archived rows when the toggle is on.
                        include_archived: appliedSpec.include_archived,
                        ...exportView,
                      }
                }
                onEdit={() => setIsBulkEditDialogOpen(true)}
                onEditTags={() => setIsBulkEditTagsDialogOpen(true)}
                onArchive={() => bulkArchiveTasks.mutate(selectedTasks.map((t) => t.id))}
                onDelete={() => {
                  if (confirm(t("tasks.bulkDeleteConfirm", { count: selectedTasks.length }))) {
                    bulkDeleteTasks.mutate(selectedTasks.map((t) => t.id));
                  }
                }}
                isArchiving={bulkArchiveTasks.isPending}
              />
            )}
            {/* The table seeds its grouping and sorting once, at mount, so it
                waits for this person's view; and each layout keeps its own, so
                moving between projects or layouts is a fresh table. */}
            {filtersLoaded ? (
              <ProjectTasksTableView
                key={`${projectId}:${kind}`}
                projectId={projectId}
                initiativeId={initiativeId}
                tasks={statusFilteredTasks}
                listParams={taskListParams}
                taskStatuses={sortedTaskStatuses}
                sensors={listSensors}
                canReorderTasks={canReorderTasks}
                canEditTaskDetails={canEditTaskDetails}
                taskActionsDisabled={taskActionsDisabled}
                onDragStart={handleTaskDragStart}
                onDragEnd={handleListDragEnd}
                onDragCancel={handleListDragCancel}
                onStatusChange={changeTaskStatus}
                taskHref={taskHref}
                onTaskSelectionChange={setSelectedTasks}
                onExitSelection={() => setSelectedTasks([])}
                tableState={tableState}
                viewColumns={layout?.definition.columns}
                displays={layout?.definition.displays}
                viewGroupings={layout?.definition.groupings}
                columnLimits={columnLimits}
              />
            ) : null}
            {canEditTaskDetails && (
              <div className="flex justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setArchiveDialogStatusId(undefined);
                    setIsArchiveDialogOpen(true);
                  }}
                  disabled={archiveDoneTasks.isPending}
                >
                  <Archive className="h-4 w-4" />
                  {archiveDoneTasks.isPending
                    ? t("common:toolSettings.archive.archiving")
                    : t("tasks.archiveDoneTasks")}
                </Button>
              </div>
            )}
          </div>
        ) : null}
        {kind === "gantt" ? (
          <ProjectTasksGanttView
            initiativeId={initiativeId}
            projectId={projectId}
            tasks={statusFilteredTasks}
            taskStatuses={sortedTaskStatuses}
            listParams={taskListParams}
            scale={ganttScale}
            onScaleChange={setMode}
            grouping={grouping}
            onGroupingChange={setGrouping}
            viewGroupings={layout?.definition.groupings}
            taskHref={taskHref}
            onReschedule={canEditTaskDetails ? rescheduleTask : undefined}
          />
        ) : null}
        {kind === "calendar" ? (
          <CalendarView
            entries={calendarEntries}
            viewMode={calendarViewMode}
            onViewModeChange={setMode}
            focusDate={calendarFocusDate}
            onFocusDateChange={setCalendarFocusDate}
            onEntryClick={(entry) => {
              const meta = entry.meta as { taskId?: number } | undefined;
              if (meta?.taskId) void navigate({ to: taskHref(meta.taskId) });
            }}
            onEntryReschedule={canEditTaskDetails ? handleCalendarReschedule : undefined}
            weekStartsOn={weekStartsOn}
          />
        ) : null}
      </div>

      {canEditTaskDetails ? (
        <>
          {/* Mounted once the columns' counts are in, so a new task starts in
              a column that isn't full. */}
          {canAddTasks && defaultStatus && defaultType && columnLimits.ready ? (
            <AddItemDialog
              open={isComposerOpen}
              onOpenChange={setIsComposerOpen}
              detail={TASK_DETAIL}
              blank={blankTask(projectId, defaultStatus, defaultType)}
              context={{
                readOnly: false,
                readOnlyMessage: null,
                statuses: sortedTaskStatuses,
                types: taskTypes ?? [],
                isFull: columnLimits.isFull,
                initiativeId,
                currentUserId: user?.id,
                askScope: neverAsks,
                actions: null,
                leaving,
              }}
              layouts={() => instanceTarget(Tool.project, projectId)}
              title={t("taskComposer.createTask")}
              ready={(task) => task.title.trim() !== ""}
              create={({ item, fields, properties }) =>
                createTask.mutateAsync({
                  project_id: projectId,
                  task_status_id: item.task_status_id,
                  task_type_id: item.task_type_id,
                  priority: item.priority,
                  ...fields,
                  properties,
                } as TaskCreate)
              }
              onAdded={() => setIsComposerOpen(false)}
            />
          ) : null}
          <Dialog open={isBulkEditDialogOpen} onOpenChange={setIsBulkEditDialogOpen}>
            <TaskBulkEditDialog
              selectedTasks={selectedTasks}
              taskStatuses={sortedTaskStatuses}
              isFull={(statusId) =>
                columnLimits.isFull(
                  statusId,
                  selectedTasks.filter((task) => task.task_status_id !== statusId).length
                )
              }
              projectId={projectId}
              isSubmitting={bulkUpdateTasks.isPending}
              onApply={(changes) => {
                bulkUpdateTasks.mutate({
                  taskIds: selectedTasks.map((t) => t.id),
                  changes: changes as Parameters<typeof bulkUpdateTasks.mutate>[0]["changes"],
                });
              }}
              onCancel={() => setIsBulkEditDialogOpen(false)}
            />
          </Dialog>

          <BulkEditTaskTagsDialog
            open={isBulkEditTagsDialogOpen}
            onOpenChange={setIsBulkEditTagsDialogOpen}
            tasks={selectedTasks}
            onSuccess={() => {}}
          />
        </>
      ) : null}

      <ConfirmDialog
        open={isArchiveDialogOpen}
        onOpenChange={setIsArchiveDialogOpen}
        title={t("tasks.archiveDialogTitle")}
        description={(() => {
          const count =
            archiveDialogStatusId !== undefined
              ? (archivableCountByStatus[archiveDialogStatusId] ?? 0)
              : archivableDoneTasksCount;
          return t("tasks.archiveDialogDescription", { count });
        })()}
        confirmLabel={t("tasks.archiveConfirm")}
        onConfirm={() => {
          archiveDoneTasks.mutate({
            projectId,
            taskStatusId: archiveDialogStatusId,
          });
          setIsArchiveDialogOpen(false);
        }}
        isLoading={archiveDoneTasks.isPending}
      />
    </div>
  );
};

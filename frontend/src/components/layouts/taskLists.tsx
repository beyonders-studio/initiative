/**
 * A project's lists as the layout editor lays them out: its table, board,
 * Gantt and calendar of its tasks, drawn with the project's own, with what
 * each list is grouped by and the limits a board sets on its columns.
 */

import type { GroupingState } from "@tanstack/react-table";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  TaskListRead,
  TaskStatusRead,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksGanttView } from "@/components/projects/ProjectTasksGanttView";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { columnLimitsOf, MAX_COLUMN_LIMIT } from "@/hooks/useColumnLimits";
import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import type { ProjectTaskTableState } from "@/hooks/useProjectTaskView";
import { useGroupables, useTaskGroupings } from "@/hooks/useTaskGroupings";
import { useTasks } from "@/hooks/useTasks";
import { buildTaskListParams, EMPTY_TASK_FILTERS } from "@/lib/filters/taskFilters";
import { TASK_LIST_SHAPE, taskFields } from "@/lib/layouts/tasks";
import type { TranslateFn } from "@/types/i18n";
import { Label } from "@/ui/label";
import { cardOf, columnsOf, indexPaths, type ListLayout } from "@/ui/layouts/draft";
import { viewGrouping, withGroupShown } from "@/ui/layouts/grouping";

import type { EditableLists, LayoutEdits, ListPreview } from "./LayoutEditor";
import { CanvasGrouping, LayoutGroupings } from "./LayoutGroupings";
import { CommittedInput } from "./LayoutSettingsPanel";

/** The project whose layouts are open. */
export type LayoutProject = {
  id: number;
  initiativeId: number;
  /** Its own properties, which its tasks show beside the initiative's metadata. */
  properties: PropertyDefinitionRead[];
  /** Its statuses, its board's columns. */
  statuses: TaskStatusRead[];
  /** Its task types, each with a page of its own. */
  types: TaskTypeRead[];
};

const noop = () => {};
const NO_COLLAPSED = new Set<number>();
const NO_TASKS: TaskListRead[] = [];
const taskHref = () => "#";

/** The list layout being edited, with the project's own tasks. */
const TaskListPreview = ({
  project: { id: projectId, initiativeId, statuses },
  layout: open,
  fields,
  frame,
  edits,
  locked,
}: ListPreview & { project: LayoutProject }) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const { definition, kind: layout, shape } = open;
  // Every task, in the project's order: filters and sorts are each person's.
  const params = useMemo(() => buildTaskListParams(EMPTY_TASK_FILTERS, { projectId }), [projectId]);
  const tasks = useTasks(params).data?.items ?? NO_TASKS;

  const card = cardOf(definition, fields, shape);
  const paths = useMemo(() => indexPaths(card), [card]);
  const groupedTasks = useMemo(() => {
    const groups: Record<number, TaskListRead[]> = {};
    for (const status of statuses) groups[status.id] = [];
    for (const task of tasks) {
      groups[task.task_status_id] ??= [];
      groups[task.task_status_id].push(task);
    }
    return groups;
  }, [tasks, statuses]);
  // The limits being set, against the open tasks the preview holds.
  const columnLimits = useMemo(
    () =>
      columnLimitsOf(
        (definition.limits ?? []).map(({ status_id, limit }) => ({
          status_id,
          limit,
          count: groupedTasks[status_id]?.length ?? 0,
        }))
      ),
    [definition.limits, groupedTasks]
  );
  // Each list's preview is grouped as the list starts until a grouping is
  // picked here, as a person's list is, so the groups of it can be hidden.
  const [picks, setPicks] = useState<Partial<Record<string, GroupingState>>>({});
  const picked = picks[layout] ?? null;
  const setGrouping = useCallback(
    (next: GroupingState) => setPicks((all) => ({ ...all, [layout]: next })),
    [layout]
  );
  const all = useGroupables(fields, t as TranslateFn);
  const grouping = useMemo(
    () => viewGrouping(definition, layout, picked, all),
    [definition, layout, picked, all]
  );
  const { offered, active } = useTaskGroupings({
    fields,
    statuses,
    tasks,
    groupings: definition.groupings,
    kind: layout,
    grouping,
    params,
    t: t as TranslateFn,
  });
  const tableState = useMemo<ProjectTaskTableState>(
    () => [
      { grouping, sorting: [] },
      { setGrouping, setSorting: noop },
    ],
    [grouping, setGrouping]
  );

  return frame(
    <>
      {layout === "board" ? (
        <ProjectTasksKanbanView
          projectId={projectId}
          initiativeId={initiativeId}
          taskStatuses={statuses}
          groupedTasks={groupedTasks}
          listParams={params}
          collapsedStatusIds={NO_COLLAPSED}
          canReorderTasks={false}
          taskHref={taskHref}
          sensors={undefined}
          activeTask={null}
          onDragStart={noop}
          onDragOver={noop}
          onDragEnd={noop}
          onDragCancel={noop}
          onToggleCollapse={noop}
          card={card}
          displays={definition.displays}
          columnLimits={columnLimits}
          grouping={grouping}
          viewGroupings={definition.groupings}
          editing={paths}
        />
      ) : null}
      {layout === "table" ? (
        <ProjectTasksTableView
          projectId={projectId}
          initiativeId={initiativeId}
          tasks={tasks}
          listParams={params}
          taskStatuses={statuses}
          sensors={undefined}
          canReorderTasks={false}
          canEditTaskDetails={false}
          taskActionsDisabled
          onDragStart={noop}
          onDragEnd={noop}
          onDragCancel={noop}
          onStatusChange={noop}
          taskHref={taskHref}
          tableState={tableState}
          viewColumns={columnsOf(definition, fields, shape)}
          displays={definition.displays}
          viewGroupings={definition.groupings}
          editing
        />
      ) : null}
      {layout === "calendar" ? (
        <p className="text-muted-foreground text-sm">{t("layouts:calendarNote")}</p>
      ) : null}
      {layout === "gantt" ? (
        <ProjectTasksGanttView
          initiativeId={initiativeId}
          projectId={projectId}
          tasks={tasks}
          taskStatuses={statuses}
          listParams={params}
          scale="week"
          grouping={grouping}
          viewGroupings={definition.groupings}
          taskHref={taskHref}
          editing
        />
      ) : null}
    </>,
    layout !== "calendar" && offered.length > 0 ? (
      <CanvasGrouping
        offered={offered}
        active={active}
        grouping={grouping}
        onGroupingChange={setGrouping}
        disabled={locked}
        onToggle={(id, key, shown) =>
          edits.changeGroupings(
            withGroupShown(definition.groupings, layout, all, id, key, shown),
            definition.group_by ?? null
          )
        }
      />
    ) : undefined
  );
};

/** A limit as typed, as the layout keeps it: a whole number the server takes,
 *  or nothing for no limit; null for anything else, which puts back the
 *  stored one. */
const limitText = (text: string): string | null => {
  if (text === "") return "";
  const limit = Number(text);
  return Number.isInteger(limit) && limit >= 1 && limit <= MAX_COLUMN_LIMIT ? String(limit) : null;
};

/** How many open tasks each of a board's columns takes from a person; one
 *  left empty takes any number. Saved with the layout. */
const ColumnLimits = ({
  layout,
  statuses,
  edits,
}: {
  layout: ListLayout;
  statuses: TaskStatusRead[];
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const limits = new Map(
    (layout.definition.limits ?? []).map((each) => [each.status_id, each.limit])
  );
  const change = (statusId: number, text: string) => {
    const next = new Map(limits);
    if (text === "") next.delete(statusId);
    else next.set(statusId, Number(text));
    edits.changeLimits(
      statuses.flatMap((status) => {
        const kept = next.get(status.id);
        return kept === undefined ? [] : [{ status_id: status.id, limit: kept }];
      })
    );
  };
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">{translate("layouts:limits.heading")}</h3>
        <p className="text-muted-foreground text-xs">{translate("layouts:limits.help")}</p>
      </div>
      <ul className="space-y-2">
        {statuses.map((status) => (
          <li key={status.id} className="flex items-center gap-2">
            <Label htmlFor={`column-limit-${status.id}`} className="min-w-0 flex-1">
              <TaskStatusOption status={status} />
            </Label>
            <div className="w-20">
              <CommittedInput
                id={`column-limit-${status.id}`}
                value={String(limits.get(status.id) ?? "")}
                optional
                numeric
                normalize={limitText}
                onCommit={(text) => change(status.id, text)}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

/** A project's lists: of its tasks, with its own properties beside the
 *  initiative's metadata. */
export const taskLists = (project: LayoutProject): EditableLists => ({
  fields: (definitions, plugins) => taskFields([...project.properties, ...definitions], plugins),
  shape: TASK_LIST_SHAPE,
  owner: { kind: "project", id: project.id },
  help: (kind) => `layouts:listHelp.${kind}`,
  preview: (preview) => <TaskListPreview project={project} {...preview} />,
  // A calendar is not grouped, and only a board limits its columns.
  settings: (layout, fields, edits) => (
    <>
      {layout.kind !== "calendar" ? (
        <LayoutGroupings layout={layout} fields={fields} edits={edits} />
      ) : null}
      {layout.kind === "board" ? (
        <ColumnLimits layout={layout} statuses={project.statuses} edits={edits} />
      ) : null}
    </>
  ),
});

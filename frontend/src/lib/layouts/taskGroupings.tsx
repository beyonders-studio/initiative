/**
 * How a project's tasks are grouped by their own fields: a status, a type, a
 * person or a tag drawn as the task's own pickers draw it, a priority as its
 * badge and a date window by its name, and what a drop from one group into
 * another writes to the task.
 */

import type {
  TaskListRead,
  TaskPriority,
  TaskStatusRead,
  TaskTypeRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { TagBadge } from "@/components/tags/TagBadge";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { priorityVariant } from "@/components/tools/projects/projectTasksConfig";
import { TaskAssigneeList } from "@/components/tools/projects/TaskAssigneeList";
import { getTaskDateStatusLabel, TASK_DATE_STATUSES } from "@/lib/taskDateStatus";
import type { TranslateFn } from "@/types/i18n";
import { Badge } from "@/ui/badge";
import {
  type GroupRow,
  type ItemGrouping,
  NO_GROUP,
  type OwnGroups,
  type PropertyMove,
  swap,
} from "@/ui/layouts/grouping";

/** A board's columns are its statuses already, so its bands never are. */
export const BOARD_COLUMNS = "task_status_id";

/** What a task list calls a field the catalog says it groups by. */
export const groupingName = (field: string, t: TranslateFn): string =>
  t(`layouts:groupings.fields.${field}`, {
    defaultValue: t(`dashboards:filterField.${field}`, { defaultValue: field }),
  });

/** What a drop from one group into another writes. */
export type GroupMove =
  | { status: number }
  | { patch: TaskUpdate }
  | { tags: { add: number[]; remove: number[] } }
  | PropertyMove;

/** One way to split a project's tasks, as a list offers it. */
export type TaskGrouping = ItemGrouping<TaskListRead, GroupMove>;

/** A task as a row of a grouped table. */
export type TaskGroupRow = GroupRow<TaskListRead>;

const byId = <T extends { id: number }>(items: T[]) =>
  new Map(items.map((item) => [String(item.id), item]));

/** What a drop into another group writes, for the fields a drop can change. */
const move = (id: string): ((from: string, to: string) => GroupMove) | undefined => {
  switch (id) {
    case BOARD_COLUMNS:
      return (_from, to) => ({ status: Number(to) });
    case "priority":
      return (_from, to) => ({ patch: { priority: to as TaskPriority } });
    case "task_type_id":
      return (_from, to) => ({ patch: { task_type_id: Number(to) } });
    // A band is a task and its parts, so a task dropped into one becomes part
    // of that task, and dropped out of every band, part of none.
    case "parent_task_id":
      return (_from, to) => ({ patch: { parent_task_id: to === NO_GROUP ? null : Number(to) } });
    case "assignee_ids":
      return (from, to) => {
        const { add, remove } = swap(from, to);
        return {
          patch: { add_assignee_ids: add.map(Number), remove_assignee_ids: remove.map(Number) },
        };
      };
    case "tag_ids":
      return (from, to) => {
        const { add, remove } = swap(from, to);
        return { tags: { add: add.map(Number), remove: remove.map(Number) } };
      };
    default:
      return undefined;
  }
};

/** How a project's tasks' own fields group, drawn from the statuses it has
 *  and what its tasks hold. */
export const taskGroups = ({
  statuses,
  tasks,
  t,
}: {
  statuses: TaskStatusRead[];
  tasks: TaskListRead[];
  t: TranslateFn;
}): OwnGroups<GroupMove> => {
  const statusesById = byId<TaskStatusRead>([
    ...tasks.map((task) => task.task_status),
    ...statuses,
  ]);
  const types = byId<TaskTypeRead>(tasks.map((task) => task.task_type));
  const people = byId(tasks.flatMap((task) => task.assignees));
  const tags = byId(tasks.flatMap((task) => task.tags ?? []));
  return {
    header: (field, key) => {
      if (field.id === "date_group") {
        return getTaskDateStatusLabel(TASK_DATE_STATUSES[Number(key)], t);
      }
      if (key === NO_GROUP) {
        if (field.kind === "tag") return t("table.untagged");
        if (field.id === "assignee_ids") return t("filters.unassigned");
        if (field.id === "parent_task_id") return t("table.noParent");
        return null;
      }
      switch (field.kind) {
        case "task_status": {
          const status = statusesById.get(key);
          return status ? (
            <TaskStatusOption status={status} className="font-medium text-base" />
          ) : null;
        }
        case "task_type": {
          const type = types.get(key);
          return type ? <TaskTypeOption type={type} className="font-medium text-base" /> : null;
        }
        case "member": {
          const person = people.get(key);
          return person ? (
            <TaskAssigneeList assignees={[person]} size="md" className="text-foreground" />
          ) : null;
        }
        case "tag": {
          const tag = tags.get(key);
          return tag ? <TagBadge tag={tag} size="md" /> : null;
        }
        default:
          return field.id === "priority" ? (
            <Badge variant={priorityVariant[key as TaskPriority]}>
              {t(`tasks:priority.${key}`)}
            </Badge>
          ) : null;
      }
    },
    move,
  };
};

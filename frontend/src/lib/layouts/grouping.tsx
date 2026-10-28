/**
 * How a project's tasks are grouped: by any field whose values group, as the
 * server's field registry names it, or a custom property. The server works out
 * the groups (`GET /tasks/groups`): which a task is in, and their order. What
 * is left here is drawing them, which is decided by the kind of field rather
 * than by each field, and what a drop from one group into another writes. The
 * table draws a grouping as header rows, the board as bands across its status
 * columns.
 */

import type { GroupingState } from "@tanstack/react-table";
import type { ReactNode } from "react";

import {
  type DateBucket,
  type GroupingDescription,
  type GroupsResponse,
  type LayoutGrouping,
  type ListLayoutDefinitionOutput,
  type ListLayoutReadKind,
  MetadataType,
  type PropertyDefinitionRead,
  type PropertySummary,
  type PropertyValuesSetRequest,
  type TaskListRead,
  type TaskPriority,
  type TaskStatusRead,
  type TaskTypeRead,
  type TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { extractUser, PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { propertyStubFromDefinition } from "@/components/properties/propertyHelpers";
import { TagBadge } from "@/components/tags/TagBadge";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { Badge } from "@/components/ui/badge";
import { dateTimeFormat } from "@/lib/intl";
import type { FieldDef } from "@/lib/layouts/fields";
import { getTaskDateStatusLabel, TASK_DATE_STATUSES } from "@/lib/taskDateStatus";
import type { TranslateFn } from "@/types/i18n";

/** The key of the group a task with no value falls into. */
export const NO_GROUP = "";

/** What a drop from one group into another writes. */
export type GroupMove =
  | { status: number }
  | { patch: TaskUpdate }
  | { tags: { add: number[]; remove: number[] } }
  | { properties: PropertyValuesSetRequest };

/** A field a list can be grouped by, as what a layout offers is read from:
 *  one the field catalog offers, or a custom property whose values group. */
export type GroupingChoice = {
  /** What a layout names it by: the field's name, or `property:<id>`. */
  id: string;
  /** Whether it groups by a bucket of the calendar. */
  bucket: boolean;
  property?: PropertyDefinitionRead;
};

/** A grouping choice, as a list draws it. */
export type Groupable = GroupingChoice & {
  label: string;
  /** The registry's kind of field, or `property`. */
  kind: string;
};

/** The fields the catalog says group, as choices. */
export const catalogChoices = (catalog: GroupingDescription[]): GroupingChoice[] =>
  catalog.map((entry) => ({ id: entry.name, bucket: entry.bucket ?? false }));

/** One way to split a project's tasks, as a list offers it. */
export type TaskGrouping = {
  id: string;
  /** The table's hidden column for it, which is what a person's view keeps. */
  column: string;
  label: string;
  /** For a date, the bucket of the calendar it groups by. */
  bucket?: DateBucket | null;
  /** The groups a task is in: none puts it in {@link NO_GROUP}, several in each. */
  keys: (task: TaskListRead) => string[];
  /** Every group there is, in order, whether or not a task is in it. */
  values?: string[];
  /** The order of two groups. */
  compare: (a: string, b: string) => number;
  header: (key: string) => ReactNode;
  /** The write a drop from `from` into `to` makes; left out where a drop
   *  can't change anything (a date window isn't a date). */
  move?: (from: string, to: string) => GroupMove;
};

/** A grouping a list offers, and the groups it leaves out while grouped by it. */
export type OfferedGrouping = { grouping: TaskGrouping; hidden: ReadonlySet<string> };

/** The groups the server worked out for one grouping. */
export type ServedGroups = { field: string; data: GroupsResponse };

/** A grouping's table column, as a person's view keeps it. */
export const groupColumn = (id: string) => `${id} group`;

/** The most groupings a layout offers, and groups one leaves out, as the
 *  server holds a layout to. */
export const MAX_GROUPINGS = 50;
export const MAX_HIDDEN_GROUPS = 200;

/** The buckets a date groups by. */
export const DATE_BUCKETS: DateBucket[] = ["day", "week", "month", "quarter", "year"];

/** A board's columns are its statuses already, so its bands never are. */
const BOARD_COLUMNS = "task_status_id";
const groupsBy = (kind: ListLayoutReadKind, id: string) => kind !== "board" || id !== BOARD_COLUMNS;

const GROUPING_PROPERTIES: ReadonlySet<string> = new Set([
  MetadataType.select,
  MetadataType.multi_select,
  MetadataType.user_reference,
  MetadataType.checkbox,
]);
const DATE_PROPERTIES: ReadonlySet<string> = new Set([MetadataType.date, MetadataType.datetime]);

/**
 * What a project's tasks can be grouped by: the fields the catalog says group,
 * then the project's properties that do, in the fields' order.
 */
export const groupables = (
  catalog: GroupingDescription[],
  fields: ReadonlyMap<string, FieldDef>,
  t: TranslateFn
): Groupable[] => [
  ...catalog.map((entry) => ({
    id: entry.name,
    bucket: entry.bucket ?? false,
    kind: entry.kind,
    label: t(`layouts:groupings.fields.${entry.name}` as never, {
      defaultValue: t(`dashboards:filterField.${entry.name}` as never, {
        defaultValue: entry.name,
      }),
    }),
  })),
  ...[...fields.values()].flatMap((field): Groupable[] => {
    const type = field.property?.type;
    if (!type || !(GROUPING_PROPERTIES.has(type) || DATE_PROPERTIES.has(type))) return [];
    return [
      {
        id: field.id,
        kind: "property",
        bucket: DATE_PROPERTIES.has(type),
        label: field.label,
        property: field.property,
      },
    ];
  }),
];

/** A layout's groupings, or, where it names none, every field that groups
 *  without a bucket. */
export const groupingsOf = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind,
  all: GroupingChoice[]
): LayoutGrouping[] =>
  groupings ??
  all
    .filter((each) => !each.bucket && !each.property && groupsBy(kind, each.id))
    .map((each) => ({ field: each.id }));

/** The groupings `kind` can offer, of `all`. */
export const groupingsFor = <T extends GroupingChoice>(all: T[], kind: ListLayoutReadKind): T[] =>
  all.filter((each) => groupsBy(kind, each.id));

const byId = <T extends { id: number }>(items: T[]) =>
  new Map(items.map((item) => [String(item.id), item]));

const label = (content: ReactNode) => <span className="font-medium text-base">{content}</span>;

/** How a person, a tag or an option moves between groups: off the one it came
 *  from and onto the other, where the empty group has none to take or give. */
const swap = (from: string, to: string) => ({
  add: to === NO_GROUP ? [] : [to],
  remove: from === NO_GROUP ? [] : [from],
});

/** A bucket of the calendar, named by its first day. */
const bucketLabel = (key: string, bucket: DateBucket, t: TranslateFn): string => {
  const [year, month, day] = key.split("-").map(Number);
  const start = new Date(year, month - 1, day);
  const dayName = dateTimeFormat(undefined, { dateStyle: "medium" }).format(start);
  switch (bucket) {
    case "week":
      return t("layouts:groupings.weekOf", { date: dayName });
    case "month":
      return dateTimeFormat(undefined, { month: "long", year: "numeric" }).format(start);
    case "quarter":
      return t("layouts:groupings.quarter", { quarter: Math.floor((month - 1) / 3) + 1, year });
    case "year":
      return String(year);
    default:
      return dayName;
  }
};

/** What a drop into another group writes, for the fields a drop can change. */
const builtinMove = (id: string): TaskGrouping["move"] => {
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

const propertyMove = (definition: PropertyDefinitionRead): TaskGrouping["move"] => {
  const id = definition.id;
  const write = (to: string, value: unknown): GroupMove => ({
    properties:
      to === NO_GROUP
        ? { merge: true, removed: [id] }
        : { merge: true, values: [{ property_id: id, value }] },
  });
  switch (definition.type) {
    case MetadataType.select:
      return (_from, to) => write(to, to);
    case MetadataType.multi_select:
      return (from, to) => ({
        properties: { merge: true, options: [{ property_id: id, ...swap(from, to) }] },
      });
    case MetadataType.user_reference:
      return (_from, to) => write(to, Number(to));
    case MetadataType.checkbox:
      return (_from, to) => write(to, to === "true");
    default:
      return undefined;
  }
};

/**
 * The groupings a list offers, in its order: the layout's own, or every field
 * that groups without a bucket where it names none. The one the server has
 * worked out groups for (`served`) knows its tasks' groups; the rest only how
 * they are offered.
 */
export const offeredGroupings = ({
  all,
  groupings,
  kind,
  statuses,
  tasks,
  served,
  t,
}: {
  all: Groupable[];
  groupings: LayoutGrouping[] | null | undefined;
  kind: ListLayoutReadKind;
  statuses: TaskStatusRead[];
  tasks: TaskListRead[];
  served?: ServedGroups;
  t: TranslateFn;
}): OfferedGrouping[] => {
  const byField = new Map(groupingsFor(all, kind).map((each) => [each.id, each]));
  // What a header draws a group with, from what the list already holds.
  const statusesById = byId<TaskStatusRead>([
    ...tasks.map((task) => task.task_status),
    ...statuses,
  ]);
  const types = byId<TaskTypeRead>(tasks.map((task) => task.task_type));
  const people = byId(tasks.flatMap((task) => task.assignees));
  const tags = byId(tasks.flatMap((task) => task.tags ?? []));

  return groupingsOf(groupings, kind, all).flatMap((entry) => {
    const field = byField.get(entry.field);
    if (!field) return [];
    const data = served?.field === field.id ? served.data : undefined;
    const order = new Map((data?.groups ?? []).map((group, index) => [group.key, index]));
    const names = new Map((data?.groups ?? []).map((group) => [group.key, group.label]));
    const named = (key: string) => label(names.get(key) ?? key);
    const empty = () => {
      if (field.kind === "tag") return label(t("table.untagged"));
      if (field.id === "assignee_ids") return label(t("filters.unassigned"));
      if (field.id === "parent_task_id") return label(t("table.noParent"));
      return label(t("table.noValue", { name: field.label }));
    };
    const summary = (value: unknown): PropertySummary => ({
      ...propertyStubFromDefinition(field.property as PropertyDefinitionRead),
      value,
    });

    const propertyHeader = (definition: PropertyDefinitionRead, key: string): ReactNode => {
      switch (definition.type) {
        case MetadataType.checkbox:
          return label(
            t(key === "true" ? "table.checked" : "table.unchecked", { name: field.label })
          );
        case MetadataType.select:
        case MetadataType.multi_select:
          return (
            <PropertyValueCell
              summary={summary(definition.type === MetadataType.select ? key : [key])}
            />
          );
        case MetadataType.user_reference: {
          const person = tasks
            .map((task) =>
              extractUser(
                task.properties?.find((each) => each.property_id === definition.id)?.value
              )
            )
            .find((each) => each && String(each.id) === key);
          return person ? <PropertyValueCell summary={summary(person)} /> : named(key);
        }
        default:
          return named(key);
      }
    };

    const header = (key: string): ReactNode => {
      if (entry.bucket && key !== NO_GROUP) return label(bucketLabel(key, entry.bucket, t));
      if (field.id === "date_group") {
        return label(getTaskDateStatusLabel(TASK_DATE_STATUSES[Number(key)], t));
      }
      if (field.property?.type === MetadataType.checkbox) {
        return propertyHeader(field.property, key);
      }
      if (key === NO_GROUP) return empty();
      if (field.property) return propertyHeader(field.property, key);
      switch (field.kind) {
        case "task_status": {
          const status = statusesById.get(key);
          return status ? (
            <TaskStatusOption status={status} className="font-medium text-base" />
          ) : (
            named(key)
          );
        }
        case "task_type": {
          const type = types.get(key);
          return type ? (
            <TaskTypeOption type={type} className="font-medium text-base" />
          ) : (
            named(key)
          );
        }
        case "member": {
          const person = people.get(key);
          return person ? (
            <TaskAssigneeList assignees={[person]} size="md" className="text-foreground" />
          ) : (
            named(key)
          );
        }
        case "tag": {
          const tag = tags.get(key);
          return tag ? <TagBadge tag={tag} size="md" /> : named(key);
        }
        default:
          if (field.id === "priority") {
            return (
              <Badge variant={priorityVariant[key as TaskPriority]}>
                {t(`tasks:priority.${key}`)}
              </Badge>
            );
          }
          return named(key);
      }
    };

    const grouping: TaskGrouping = {
      id: field.id,
      column: groupColumn(field.id),
      label: field.label,
      bucket: entry.bucket,
      keys: (task) => data?.rows[String(task.id)] ?? [],
      values: data?.groups.map((group) => group.key),
      compare: (a, b) => (order.get(a) ?? order.size) - (order.get(b) ?? order.size),
      header,
      move: entry.bucket
        ? undefined
        : field.property
          ? propertyMove(field.property)
          : builtinMove(field.id),
    };
    return [{ grouping, hidden: new Set(entry.hidden ?? []) }];
  });
};

/**
 * What a person's list is grouped by: the pick they kept, None included,
 * while the list still offers it, and otherwise the grouping the list starts
 * on. `kept` is null where they never picked.
 */
export const viewGrouping = (
  definition: Pick<ListLayoutDefinitionOutput, "groupings" | "group_by"> | undefined,
  kind: ListLayoutReadKind,
  kept: GroupingState | null,
  all: GroupingChoice[]
): GroupingState => {
  const start = definition?.group_by ? [groupColumn(definition.group_by)] : [];
  if (kept === null) return start;
  const offered = groupingsOf(definition?.groupings, kind, all)
    .filter((entry) => groupsBy(kind, entry.field))
    .map((entry) => groupColumn(entry.field));
  return kept.every((column) => offered.includes(column)) ? kept : start;
};

/** The grouping a list is grouped by, as the layout offers it: its field and
 *  bucket, and the groups it leaves out. */
export const activeGrouping = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind,
  grouping: GroupingState,
  all: GroupingChoice[]
): LayoutGrouping | undefined =>
  groupingsOf(groupings, kind, all).find((entry) => grouping.includes(groupColumn(entry.field)));

/** `groupings` (the offered ones where null) with the group `key` of the one
 *  `id` names shown or left out. */
export const withGroupShown = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind,
  all: GroupingChoice[],
  id: string,
  key: string,
  shown: boolean
): LayoutGrouping[] =>
  groupingsOf(groupings, kind, all).map((entry) => {
    if (entry.field !== id) return entry;
    const others = (entry.hidden ?? []).filter((each) => each !== key);
    return { ...entry, hidden: shown ? others : [...others, key] };
  });

/** A band of a grouped board: one group, and its tasks in the board's order. */
export type Band = { key: string; tasks: TaskListRead[] };

/** A board's bands: one for each group there is (the ones `values` names,
 *  holding a task or not) and each its tasks are in, a task in several in
 *  each, less those `hidden` leaves out, in the grouping's order. */
export const boardBands = (
  { grouping, hidden }: OfferedGrouping,
  tasks: TaskListRead[]
): Band[] => {
  const bands = new Map<string, TaskListRead[]>((grouping.values ?? []).map((key) => [key, []]));
  for (const task of tasks) {
    const keys = grouping.keys(task);
    for (const key of keys.length > 0 ? keys : [NO_GROUP]) {
      const band = bands.get(key);
      if (band) band.push(task);
      else bands.set(key, [task]);
    }
  }
  return [...bands]
    .filter(([key]) => !hidden.has(key))
    .sort(([a], [b]) => grouping.compare(a, b))
    .map(([key, held]) => ({ key, tasks: held }));
};

/** A task as a row of a grouped table: the one group it is listed under, when
 *  the table is grouped, so a plain task list is a valid row list. */
export type TaskGroupRow = TaskListRead & { group?: string };

/** One row per group a task is in, so a task with two tags is listed under
 *  both rather than under whichever came first. */
export const groupRows = (tasks: TaskListRead[], grouping: TaskGrouping): TaskGroupRow[] =>
  tasks.flatMap((task) => {
    const keys = grouping.keys(task);
    return (keys.length > 0 ? keys : [NO_GROUP]).map((group) => ({ ...task, group }));
  });

/** A row's id: a task listed under several groups has a row in each. */
export const groupRowId = (row: TaskGroupRow): string =>
  row.group === undefined ? String(row.id) : `${row.id}::${row.group}`;

/** The tasks rows came from, each once, as the list holds them. */
export const uniqueTasksFromRows = (
  rows: TaskGroupRow[],
  tasksById: Map<number, TaskListRead>
): TaskListRead[] => {
  const seen = new Set<number>();
  const tasks: TaskListRead[] = [];
  for (const row of rows) {
    if (seen.has(row.id)) {
      continue;
    }
    seen.add(row.id);
    tasks.push(tasksById.get(row.id) ?? row);
  }
  return tasks;
};

/**
 * The task filter vocabulary: one spec type, one way to compile it.
 *
 * `buildTaskConditions` is THE place filter values become the endpoint's DSL.
 * The tasks section, the route loader's prefetch, and the CSV export all call
 * it, so the three cannot disagree about what the list is showing — they used
 * to, and the loader's prefetch key silently never matched the component's.
 *
 * A person's filters are their own: saved in their view of the list (a
 * per-user preference) in the stored shape below, never on a layout.
 */

import type { SortingState } from "@tanstack/react-table";

import type {
  FilterCondition,
  FilterGroup,
  ListTasksParams,
  SortField,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskPriority } from "@/api/generated/initiativeAPI.schemas";
import type { DueFilterOption } from "@/components/tools/projects/projectTasksConfig";
import type {
  PluginFilterCondition,
  PropertyFilterCondition,
} from "@/ui/properties/PropertyFilter";

/** The due-window tokens a view can hold. `null` is "any due date". */
export type DueToken = Exclude<DueFilterOption, "all">;

/** The tokens `assignees` may hold besides a numeric user id. `me` is resolved
 *  per-request by the endpoint, which is what keeps a shared link portable. */
export const ASSIGNEE_ME = "me";
export const ASSIGNEE_NONE = "none";

export interface TaskFilterSpec {
  status_ids: number[];
  status_categories: TaskStatusCategory[];
  /** The project's task types, by id. */
  type_ids: number[];
  priorities: TaskPriority[];
  /** Only a list that holds several communities' tasks (My Tasks) narrows by
   *  them. */
  community_ids: number[];
  assignees: string[];
  tag_ids: number[];
  properties: PropertyFilterCondition[];
  /** By a plug-in's field, where the reader is drawn it. */
  plugins: PluginFilterCondition[];
  due: DueToken | null;
  include_archived: boolean;
}

export const EMPTY_TASK_FILTERS: TaskFilterSpec = {
  status_ids: [],
  status_categories: [],
  type_ids: [],
  priorities: [],
  community_ids: [],
  assignees: [],
  tag_ids: [],
  properties: [],
  plugins: [],
  due: null,
  include_archived: false,
};

/** Each due window's label in `projects`, in the order the picker offers them. */
export const DUE_LABEL_KEYS = {
  overdue: "filters.overdue",
  today: "filters.dueToday",
  "7_days": "filters.dueNext7Days",
  "30_days": "filters.dueNext30Days",
} as const satisfies Record<DueToken, string>;

const DUE_TOKENS: readonly string[] = Object.keys(DUE_LABEL_KEYS);
const CATEGORIES: readonly string[] = ["backlog", "todo", "in_progress", "done"];
const PRIORITIES: readonly string[] = Object.values(TaskPriority);

const numbers = (raw: unknown): number[] =>
  Array.isArray(raw) ? raw.filter((v): v is number => typeof v === "number") : [];

/** A spec as a person's view stores it: every key optional, so what an older
 *  release stored still reads. */
export type StoredTaskFilters = Partial<Record<keyof TaskFilterSpec, unknown>>;

/** Coerce stored filters (every key optional) into a full spec. */
export function specFromStored(raw: StoredTaskFilters | null | undefined): TaskFilterSpec {
  if (!raw) return EMPTY_TASK_FILTERS;
  return {
    status_ids: numbers(raw.status_ids),
    type_ids: numbers(raw.type_ids),
    status_categories: Array.isArray(raw.status_categories)
      ? raw.status_categories.filter(
          (v): v is TaskStatusCategory => typeof v === "string" && CATEGORIES.includes(v)
        )
      : [],
    priorities: Array.isArray(raw.priorities)
      ? raw.priorities.filter(
          (v): v is TaskPriority => typeof v === "string" && PRIORITIES.includes(v)
        )
      : [],
    community_ids: numbers(raw.community_ids),
    assignees: Array.isArray(raw.assignees)
      ? raw.assignees.filter((v): v is string => typeof v === "string")
      : [],
    tag_ids: numbers(raw.tag_ids),
    properties: Array.isArray(raw.properties)
      ? (raw.properties as PropertyFilterCondition[]).filter(
          (entry) => typeof entry?.property_id === "number"
        )
      : [],
    plugins: Array.isArray(raw.plugins)
      ? (raw.plugins as PluginFilterCondition[]).filter(
          (entry) => typeof entry?.field === "string" && entry.field.startsWith("plugin:")
        )
      : [],
    due: typeof raw.due === "string" && DUE_TOKENS.includes(raw.due) ? (raw.due as DueToken) : null,
    include_archived: raw.include_archived === true,
  };
}

const sameIds = (a: readonly (number | string)[], b: readonly (number | string)[]) =>
  a.length === b.length && a.every((value, index) => value === b[index]);

export function taskFiltersEqual(a: TaskFilterSpec, b: TaskFilterSpec): boolean {
  return (
    sameIds(a.status_ids, b.status_ids) &&
    sameIds(a.status_categories, b.status_categories) &&
    sameIds(a.type_ids, b.type_ids) &&
    sameIds(a.priorities, b.priorities) &&
    sameIds(a.community_ids, b.community_ids) &&
    sameIds(a.assignees, b.assignees) &&
    sameIds(a.tag_ids, b.tag_ids) &&
    a.due === b.due &&
    a.include_archived === b.include_archived &&
    JSON.stringify(a.properties) === JSON.stringify(b.properties) &&
    JSON.stringify(a.plugins) === JSON.stringify(b.plugins)
  );
}

/** What the filter button badges. `include_archived` counts: widening what the
 *  list shows is as much a departure from the default as narrowing it. */
export function taskFilterCount(spec: TaskFilterSpec): number {
  return (
    spec.status_ids.length +
    spec.status_categories.length +
    spec.type_ids.length +
    spec.priorities.length +
    spec.community_ids.length +
    spec.assignees.length +
    spec.tag_ids.length +
    spec.properties.length +
    spec.plugins.length +
    (spec.due ? 1 : 0) +
    (spec.include_archived ? 1 : 0)
  );
}

// --- compiling to the wire DSL ---------------------------------------------

/** Today at local midnight, as an ISO instant.
 *
 *  Due windows are quantized to whole days rather than pinned to "now" so the
 *  compiled conditions are byte-identical for 24 hours. That is what lets the
 *  route loader's prefetch key match the component's query key — an
 *  instant-valued bound would change on every render and never hit. */
export function startOfLocalDay(offsetDays = 0): string {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString();
}

function dueConditions(due: DueToken): (FilterCondition | FilterGroup)[] {
  const between = (fromDays: number, toDays: number): FilterGroup => ({
    logic: "and",
    conditions: [
      { field: "due_date", op: "gte", value: startOfLocalDay(fromDays) },
      { field: "due_date", op: "lt", value: startOfLocalDay(toDays) },
    ],
  });
  switch (due) {
    case "overdue":
      return [{ field: "due_date", op: "lt", value: startOfLocalDay(0) }];
    case "today":
      return [between(0, 1)];
    case "7_days":
      return [between(0, 8)];
    case "30_days":
      return [between(0, 31)];
  }
}

/**
 * Whether a due date falls in the window a `due` token names.
 *
 * The same day boundaries {@link buildTaskConditions} sends to the server, so
 * an optimistic local update and the eventual refetch agree about whether an
 * edited task still belongs in the list.
 */
export function matchesDueWindow(
  dueDate: string | null | undefined,
  due: DueToken | null
): boolean {
  if (!due) return true;
  if (!dueDate) return false;
  const value = new Date(dueDate).getTime();
  if (Number.isNaN(value)) return false;
  const day = (offset: number) => new Date(startOfLocalDay(offset)).getTime();
  switch (due) {
    case "overdue":
      return value < day(0);
    case "today":
      return value >= day(0) && value < day(1);
    case "7_days":
      return value >= day(0) && value < day(8);
    case "30_days":
      return value >= day(0) && value < day(31);
  }
}

function assigneeConditions(assignees: string[]): (FilterCondition | FilterGroup)[] {
  if (assignees.length === 0) return [];
  const wantsUnassigned = assignees.includes(ASSIGNEE_NONE);
  const ids = assignees.filter((value) => value !== ASSIGNEE_NONE);
  // No list of ids can express "nobody is on this", so it is its own operator.
  const unassigned: FilterCondition = { field: "assignee_ids", op: "is_null", value: true };
  const someone: FilterCondition = { field: "assignee_ids", op: "in_", value: ids };
  if (wantsUnassigned && ids.length === 0) return [unassigned];
  if (!wantsUnassigned) return [someone];
  return [{ logic: "or", conditions: [unassigned, someone] }];
}

function statusConditions(spec: TaskFilterSpec): (FilterCondition | FilterGroup)[] {
  const byId: FilterCondition = {
    field: "task_status_id",
    op: "in_",
    value: spec.status_ids,
  };
  const byCategory: FilterCondition = {
    field: "status_category",
    op: "in_",
    value: spec.status_categories,
  };
  if (spec.status_ids.length === 0 && spec.status_categories.length === 0) return [];
  if (spec.status_categories.length === 0) return [byId];
  if (spec.status_ids.length === 0) return [byCategory];
  // One control, one question — "which statuses?" — answered either by naming
  // them or by naming a category. AND would make the two halves contradict
  // each other (a Blocked task is not in the Done category), so picking from
  // both sides has to widen the list, not empty it.
  return [{ logic: "or", conditions: [byId, byCategory] }];
}

/** The spec's conditions without the project they're scoped to: an export
 *  applies them to each project it carries. */
export function taskSpecConditions(spec: TaskFilterSpec): (FilterCondition | FilterGroup)[] {
  return [
    ...statusConditions(spec),
    ...(spec.type_ids.length > 0
      ? [{ field: "task_type_id", op: "in_" as const, value: spec.type_ids }]
      : []),
    ...(spec.priorities.length > 0
      ? [{ field: "priority", op: "in_" as const, value: spec.priorities }]
      : []),
    // The cross-community list reads this as ``community_ids`` (plural, like
    // ``initiative_ids``); the singular silently filters nothing.
    ...(spec.community_ids.length > 0
      ? [{ field: "community_ids", op: "in_" as const, value: spec.community_ids }]
      : []),
    ...assigneeConditions(spec.assignees),
    ...(spec.tag_ids.length > 0
      ? [{ field: "tag_ids", op: "in_" as const, value: spec.tag_ids }]
      : []),
    ...spec.properties.map((entry) => ({
      field: "property_values" as const,
      op: entry.op as FilterCondition["op"],
      value: { property_id: entry.property_id, value: entry.value },
    })),
    ...spec.plugins.map((entry) => ({
      field: "plugin_values" as const,
      op: entry.op as FilterCondition["op"],
      value: { field: entry.field, value: entry.value },
    })),
    ...(spec.due ? dueConditions(spec.due) : []),
  ];
}

/** Compile a spec into the endpoint's `conditions`. */
/** Where a task list reads from: one project, or every project in an
 *  initiative. */
export type TaskScope = { projectId: number } | { initiativeId: number };

const scopeCondition = (scope: TaskScope): FilterCondition =>
  "projectId" in scope
    ? { field: "project_id", op: "eq", value: scope.projectId }
    : { field: "initiative_ids", op: "in_", value: [scope.initiativeId] };

/** Compile a spec into the endpoint's `conditions`, inside its scope. */
export function buildTaskConditions(
  spec: TaskFilterSpec,
  scope: TaskScope
): (FilterCondition | FilterGroup)[] {
  return [scopeCondition(scope), ...taskSpecConditions(spec)];
}

/**
 * The full list params, including archived. `include_archived` is a query
 * param rather than a condition, so it can't live in `conditions`.
 *
 * Without a `page`, `page_size: 0` walks every page — the board and the
 * drag-reorder need the whole list, not a window.
 */
export function buildTaskListParams(
  spec: TaskFilterSpec,
  scope: TaskScope,
  page: { page: number; page_size: number } = { page: 1, page_size: 0 }
): ListTasksParams {
  return {
    conditions: buildTaskConditions(spec, scope),
    ...(page.page_size === 0 ? { page_size: 0 } : page),
    ...(spec.include_archived && { include_archived: true }),
  };
}

/** Task table columns the task list can order by, and the sort field each is. */
const SORT_FIELD_BY_COLUMN: Record<string, string> = {
  title: "title",
  "due date": "due_date",
  "start date": "start_date",
  "date group": "date_group",
  priority: "priority",
  status: "status_position",
  tags: "tag_name",
};

const COLUMN_BY_SORT_FIELD: Record<string, string> = Object.fromEntries(
  Object.entries(SORT_FIELD_BY_COLUMN).map(([columnId, field]) => [field, columnId])
);

/** The columns a table is sorted by, as the endpoint names them, and nothing
 *  else: what a preset keeps. */
export const tableSortFields = (sorting: SortingState): SortField[] =>
  sorting.flatMap((column): SortField[] => {
    const field = SORT_FIELD_BY_COLUMN[column.id];
    return field ? [{ field, dir: column.desc ? "desc" : "asc" }] : [];
  });

/** A task table's sort as the endpoint's `sorting`. Columns the list cannot
 *  order by are left out, and ties keep the project's own order, as they do
 *  in the table. */
export function taskSortFields(sorting: SortingState): SortField[] {
  const fields = tableSortFields(sorting);
  // A date group on its own orders nothing within a group.
  if (fields.length === 1 && fields[0].field === "date_group") {
    fields.push({ field: "due_date", dir: fields[0].dir });
  }
  return fields.length > 0 ? [...fields, { field: "position", dir: "asc" }] : fields;
}

/** The endpoint's `sorting` as the table's, to seed its headers. */
export function taskTableSorting(fields: SortField[]): SortingState {
  return fields.flatMap((entry) => {
    const id = COLUMN_BY_SORT_FIELD[entry.field];
    return id ? [{ id, desc: entry.dir === "desc" }] : [];
  });
}

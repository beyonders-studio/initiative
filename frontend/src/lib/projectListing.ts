/**
 * Reading a project listing.
 *
 * A project listing is the project's export envelope (backend
 * `ProjectExportEnvelope`), and so is its example. The API types both as an
 * open object, so this names the parts a listing page shows and checks the
 * shape it was given before anything reads it.
 *
 * A listing stores dates as offsets: its earliest one sits on a fixed day, and
 * installing moves that day to the start date the installer picks. The board
 * a listing previews on moves them to today, as installing today would.
 */

import type {
  CurrencyCode,
  PropertyDefinitionRead,
  PropertyOption,
  PropertySummary,
  PropertyType,
  RecurrenceStrategy,
  TaskListRead,
  TaskPriority,
  TaskStatusCategory,
  TaskStatusRead,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { defaultsForCategory } from "@/lib/taskStatusDefaults";

export interface ProjectListingStatus {
  name: string;
  category: TaskStatusCategory;
  position: number;
  color?: string | null;
  icon?: string | null;
  is_default?: boolean;
}

export interface ProjectListingPropertyValue {
  property_name: string;
  property_type: PropertyType;
  value_text?: string | null;
  value_number?: number | null;
  value_boolean?: boolean | null;
  value_json?: unknown;
}

export interface ProjectListingPropertyDefinition {
  name: string;
  type: PropertyType;
  position: number;
  color?: string | null;
  options?: PropertyOption[] | null;
  currency?: CurrencyCode | null;
}

export interface ProjectListingTask {
  title: string;
  description?: string | null;
  priority: TaskPriority;
  start_date?: string | null;
  due_date?: string | null;
  completed_at?: string | null;
  recurrence?: string | Record<string, unknown> | null;
  recurrence_strategy?: RecurrenceStrategy;
  recurrence_limit?: number | null;
  recurrence_shift?: number;
  recurrence_occurrence_count?: number;
  recurrence_anchor?: string | null;
  recurrence_anchor_count?: number;
  position?: number;
  status_name: string;
  type_name?: string | null;
  checklist: { text: string; done: boolean }[];
  properties: ProjectListingPropertyValue[];
}

export interface ProjectListingType {
  name: string;
  position: number;
  is_default?: boolean;
  color?: string | null;
  icon?: string | null;
  layout_preset?: string | null;
}

export interface ProjectListingEnvelope {
  project: {
    name: string;
    start_date?: string | null;
    end_date?: string | null;
    properties?: ProjectListingPropertyValue[];
  };
  task_statuses: ProjectListingStatus[];
  /** Absent from a listing published before task types existed. */
  task_types?: ProjectListingType[];
  property_definitions: ProjectListingPropertyDefinition[];
  tasks: ProjectListingTask[];
}

/** The envelope, or null when what was given is not one. */
export const readProjectEnvelope = (value: unknown): ProjectListingEnvelope | null => {
  if (!value || typeof value !== "object") return null;
  const envelope = value as Partial<ProjectListingEnvelope>;
  return envelope.project &&
    Array.isArray(envelope.task_statuses) &&
    Array.isArray(envelope.property_definitions) &&
    Array.isArray(envelope.tasks)
    ? (envelope as ProjectListingEnvelope)
    : null;
};

const DATE_PROPERTY_TYPES: ReadonlySet<string> = new Set(["date", "datetime"]);

/** Every date the envelope plans with, which are the ones installing moves:
 *  the project's span, each task's dates, and every date-typed property value. */
const datesOf = (envelope: ProjectListingEnvelope): string[] =>
  [
    envelope.project.start_date,
    envelope.project.end_date,
    ...envelope.tasks.flatMap((task) => [task.start_date, task.due_date, task.completed_at]),
    ...[envelope.project.properties ?? [], ...envelope.tasks.map((task) => task.properties)]
      .flat()
      .filter((value) => DATE_PROPERTY_TYPES.has(value.property_type))
      .map((value) => value.value_text),
  ].filter((date): date is string => Boolean(date));

/** Whether installing this envelope places anything on a calendar, and so
 *  whether a start date is worth asking for. */
export const projectEnvelopeHasDates = (envelope: ProjectListingEnvelope | null): boolean =>
  envelope ? datesOf(envelope).length > 0 : false;

const MS_PER_DAY = 86_400_000;

/** The calendar day a stored date names, as a day count. Read from the date
 *  part alone, so a task's time of day and the viewer's zone do not move it. */
const dayNumber = (date: string): number => {
  const [year, month, day] = date.slice(0, 10).split("-").map(Number);
  return Date.UTC(year, month - 1, day) / MS_PER_DAY;
};

/** `value` moved by `days`: a date stays a date, a timestamp keeps its time. */
const shifted = (value: string | null | undefined, days: number): string | null => {
  if (!value) return null;
  if (value.length === 10) {
    return new Date((dayNumber(value) + days) * MS_PER_DAY).toISOString().slice(0, 10);
  }
  return new Date(new Date(value).getTime() + days * MS_PER_DAY).toISOString();
};

export interface ProjectListingBoard {
  taskStatuses: TaskStatusRead[];
  taskTypes: TaskTypeRead[];
  groupedTasks: Record<number, TaskListRead[]>;
  propertyDefinitions: PropertyDefinitionRead[];
}

/**
 * What the project board draws, built from the envelope alone.
 *
 * The ids follow the envelope's own order, starting at 1. Nothing here exists
 * in a community, so nothing carries a community, an initiative or a person.
 * The dates move so the earliest falls on `today` (`YYYY-MM-DD`), which is
 * where installing today puts them.
 */
export const projectListingBoard = (
  envelope: ProjectListingEnvelope,
  today: string
): ProjectListingBoard => {
  const days = datesOf(envelope).map(dayNumber);
  const shift = days.length ? dayNumber(today) - Math.min(...days) : 0;

  const taskStatuses: TaskStatusRead[] = [...envelope.task_statuses]
    .sort((a, b) => a.position - b.position)
    .map((status, index) => {
      // A status without its own look takes its category's, as installing does.
      const look = defaultsForCategory(status.category);
      return {
        id: index + 1,
        project_id: 0,
        name: status.name,
        category: status.category,
        position: status.position,
        is_default: status.is_default ?? false,
        color: status.color ?? look.color,
        icon: status.icon ?? look.icon,
      };
    });

  // A listing without types is drawn as one type, which shows nothing.
  const taskTypes: TaskTypeRead[] = [
    ...(envelope.task_types?.length
      ? envelope.task_types
      : [{ name: "", position: 0, is_default: true }]),
  ]
    .sort((a, b) => a.position - b.position)
    .map((type, index) => ({
      id: index + 1,
      project_id: 0,
      name: type.name,
      position: type.position,
      is_default: type.is_default ?? false,
      color: type.color ?? "#94A3B8",
      icon: type.icon ?? "square-check",
      layout_preset: type.layout_preset ?? "plain",
      // A preview starts no tasks.
      starting_values: null,
    }));
  const defaultType = taskTypes.find((type) => type.is_default) ?? taskTypes[0];
  const typeOf = (name: string | null | undefined) =>
    taskTypes.find((type) => type.name.toLowerCase() === (name ?? "").toLowerCase()) ?? defaultType;

  const propertyDefinitions: PropertyDefinitionRead[] = envelope.property_definitions.map(
    (definition, index) => ({
      id: index + 1,
      initiative_id: 0,
      name: definition.name,
      type: definition.type,
      position: definition.position,
      color: definition.color ?? null,
      options: definition.options ?? null,
      currency: definition.currency ?? null,
      collection_id: null,
      created_at: "",
      updated_at: "",
    })
  );

  const summaryOf = (value: ProjectListingPropertyValue): PropertySummary[] => {
    const definition = propertyDefinitions.find((d) => d.name === value.property_name);
    if (!definition) return [];
    return [
      {
        property_id: definition.id,
        name: definition.name,
        type: definition.type,
        options: definition.options,
        currency: definition.currency,
        value: DATE_PROPERTY_TYPES.has(value.property_type)
          ? shifted(value.value_text, shift)
          : (value.value_text ?? value.value_number ?? value.value_boolean ?? value.value_json),
      },
    ];
  };

  const groupedTasks: Record<number, TaskListRead[]> = {};
  envelope.tasks.forEach((task, index) => {
    const status = taskStatuses.find((s) => s.name === task.status_name);
    if (!status) return;
    groupedTasks[status.id] ??= [];
    const type = typeOf(task.type_name);
    groupedTasks[status.id].push({
      id: index + 1,
      project_id: 0,
      task_type_id: type.id,
      task_type: type,
      project_name: envelope.project.name,
      title: task.title,
      priority: task.priority,
      start_date: shifted(task.start_date, shift),
      due_date: shifted(task.due_date, shift),
      completed_at: shifted(task.completed_at, shift),
      // A repeat published before RRULE keeps a shape the board does not read.
      recurrence: typeof task.recurrence === "string" ? task.recurrence : null,
      recurrence_strategy: task.recurrence_strategy ?? "fixed",
      recurrence_limit: task.recurrence_limit ?? null,
      recurrence_shift: task.recurrence_shift ?? 0,
      recurrence_occurrence_count: task.recurrence_occurrence_count ?? 0,
      recurrence_anchor: shifted(task.recurrence_anchor, shift),
      recurrence_anchor_count: task.recurrence_anchor_count ?? 0,
      recurrence_until: null,
      // A list row's excerpt is the server's, and a listing has none.
      description_excerpt: null,
      has_description: Boolean(task.description),
      task_status_id: status.id,
      task_status: status,
      position: task.position ?? index,
      created_at: "",
      updated_at: "",
      archived_at: null,
      created_by: null,
      assignees: [],
      comment_count: 0,
      blocked_by_open_count: 0,
      community_id: null,
      community_name: null,
      initiative_id: null,
      initiative_name: null,
      initiative_color: null,
      checklist_progress: {
        completed: task.checklist.filter((item) => item.done).length,
        total: task.checklist.length,
      },
      parent: null,
      subtask_progress: null,
      // A tag chip opens the community's own tag, and a listing's has none yet.
      tags: [],
      properties: task.properties.flatMap(summaryOf),
      plugin_values: [],
    });
  });
  for (const tasks of Object.values(groupedTasks)) tasks.sort((a, b) => a.position - b.position);

  return { taskStatuses, taskTypes, groupedTasks, propertyDefinitions };
};

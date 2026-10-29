/**
 * What a read title ({@link readTitle}) does to a task: the fields it sets on
 * one being added, as the add dialog takes each change, and the fields it
 * adds to one made in a single step.
 */

import type {
  TaskAssigneeSummary,
  TaskCreate,
  TaskPriority,
  TaskRead,
  TaskTypeRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { rulePayload, shiftFor, toRRule } from "@/lib/recurrence";
import type { TitlePerson, TitleReading } from "@/lib/smartTitle";
import { startedFrom } from "@/lib/taskTypeStart";

/** What a title last set on a task being added, and what each field held
 *  before it did, which it goes back to when the words are taken out. */
export interface Applied {
  title: string | null;
  /** The task type's id. */
  type: number | null;
  due: string | null;
  priority: TaskPriority | null;
  repeat: string | null;
  tags: number[];
  people: number[];
  before: {
    task_type: TaskTypeRead | null;
    due_date: string | null;
    priority: TaskPriority | null;
  };
}

export const NOTHING_APPLIED: Applied = {
  title: null,
  type: null,
  due: null,
  priority: null,
  repeat: null,
  tags: [],
  people: [],
  before: { task_type: null, due_date: null, priority: null },
};

const sameIds = (a: number[], b: number[]) =>
  a.length === b.length && a.every((id, index) => id === b[index]);

const assignee = (person: TitlePerson): TaskAssigneeSummary => ({
  id: person.id,
  username: person.username,
  discriminator: person.discriminator,
  display_name: person.display_name,
  avatar_url: person.avatar_url,
  status: person.status as TaskAssigneeSummary["status"],
});

/**
 * The edit that takes a task being added from what its title last set to
 * what it sets now, or null when nothing moved. Only a field the reading
 * changed is touched, and only while it still holds what the title last set
 * there: one picked by hand since stays as picked, even once its words go.
 * The tags and people picked by hand stay beside the ones the title names.
 * A type the title names brings what that type starts with, as picking it
 * would; a priority the title also names is set over it.
 */
export const readingEdit = (
  task: TaskRead,
  reading: TitleReading,
  applied: Applied
): { edit: { patch: TaskUpdate; shows: Partial<TaskRead> } | null; applied: Applied } => {
  const patch: TaskUpdate = {};
  const shows: Partial<TaskRead> = {};
  const next: Applied = { ...applied, before: { ...applied.before } };

  if (reading.title !== applied.title) {
    patch.title = reading.title;
    next.title = reading.title;
  }

  // The task as the type leaves it, which the priority below is measured on.
  let current = task;
  const type = reading.type?.id ?? null;
  if (type !== applied.type) {
    if (applied.type === null) next.before.task_type = task.task_type;
    const value = reading.type ?? next.before.task_type;
    if (
      value &&
      value.id !== task.task_type_id &&
      (applied.type === null || task.task_type_id === applied.type)
    ) {
      // A priority the title set is not what the type started with: the type
      // moves the one it would go back to instead.
      const titled = applied.priority !== null && task.priority === applied.priority;
      const started = startedFrom(
        { ...task, priority: titled ? (applied.before.priority ?? task.priority) : task.priority },
        task.task_type,
        value
      );
      patch.task_type_id = value.id;
      shows.task_type_id = value.id;
      shows.task_type = value;
      if ("description" in started) {
        patch.description = started.description;
        shows.description = started.description;
      }
      if (started.priority) {
        if (titled) next.before.priority = started.priority;
        else {
          patch.priority = started.priority;
          shows.priority = started.priority;
        }
      }
      current = { ...task, ...shows };
    }
    next.type = type;
  }

  const due = reading.due?.toISOString() ?? null;
  if (due !== applied.due) {
    if (applied.due === null) next.before.due_date = task.due_date;
    if (applied.due === null || task.due_date === applied.due) {
      const value = due ?? next.before.due_date;
      patch.due_date = value;
      shows.due_date = value;
    }
    next.due = due;
  }

  if (reading.priority !== applied.priority) {
    if (applied.priority === null) next.before.priority = current.priority;
    const value = reading.priority ?? next.before.priority;
    if (value && (applied.priority === null || current.priority === applied.priority)) {
      patch.priority = value;
      shows.priority = value;
    }
    next.priority = reading.priority;
  }

  // The strategy is part of what was said: "every 2 hours" counts from completion.
  const repeat = reading.repeat ? `${toRRule(reading.repeat)}|${reading.repeatStrategy}` : null;
  if (repeat !== applied.repeat) {
    if (reading.repeat) {
      Object.assign(patch, rulePayload(reading.repeat), {
        recurrence_strategy: reading.repeatStrategy,
        recurrence_limit: null,
      });
      Object.assign(shows, {
        recurrence: toRRule(reading.repeat),
        recurrence_strategy: reading.repeatStrategy,
        recurrence_limit: null,
      });
    } else {
      patch.recurrence = null;
      shows.recurrence = null;
    }
    next.repeat = repeat;
  }
  // The title's repeat is shown with the shift the server will keep for the
  // due date the task ends up with: the title's, or one picked by hand, which
  // stays. Worked out again whenever either moves, so the repeat editor reads
  // the rule as picked.
  if (reading.repeat && (repeat !== applied.repeat || "due_date" in patch)) {
    const kept = "due_date" in patch ? patch.due_date : task.due_date;
    shows.recurrence_shift = kept ? shiftFor(reading.repeat, new Date(kept)) : 0;
  }

  const tags = reading.tags.map((tag) => tag.id);
  if (!sameIds(tags, applied.tags)) {
    const picked = task.tags.filter((tag) => !applied.tags.includes(tag.id));
    const all = [...picked, ...reading.tags.filter((tag) => !picked.some((p) => p.id === tag.id))];
    patch.tag_ids = all.map((tag) => tag.id);
    shows.tags = all;
    next.tags = tags;
  }

  const people = reading.people.map((person) => person.id);
  if (!sameIds(people, applied.people)) {
    const picked = task.assignees.filter((person) => !applied.people.includes(person.id));
    const all = [
      ...picked,
      ...reading.people.filter((person) => !picked.some((p) => p.id === person.id)).map(assignee),
    ];
    patch.assignee_ids = all.map((person) => person.id);
    shows.assignees = all;
    next.people = people;
  }

  // What the title says now is kept even where nothing moved, so its next
  // change is measured from it.
  return { edit: Object.keys(patch).length ? { patch, shows } : null, applied: next };
};

/** The fields a read title adds to a task made in one step, beside the people
 *  it already goes to. */
export const readingCreate = (
  reading: TitleReading,
  assigneeIds: number[] = []
): Partial<TaskCreate> => {
  const people = [...new Set([...assigneeIds, ...reading.people.map((person) => person.id)])];
  return {
    title: reading.title,
    ...(reading.type ? { task_type_id: reading.type.id } : {}),
    ...(reading.due ? { due_date: reading.due.toISOString() } : {}),
    ...(reading.priority ? { priority: reading.priority } : {}),
    ...(reading.repeat
      ? { ...rulePayload(reading.repeat), recurrence_strategy: reading.repeatStrategy }
      : {}),
    ...(reading.tags.length ? { tag_ids: reading.tags.map((tag) => tag.id) } : {}),
    ...(people.length ? { assignee_ids: people } : {}),
  };
};

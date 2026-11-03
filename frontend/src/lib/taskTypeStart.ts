/**
 * What a new task takes from its type: the starting values it is drawn with
 * while it is being added, which follow the type until the person changes them.
 */

import type { TaskRead, TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";

/** What a new task of `type` starts with where it is drawn: its description
 *  outline and its priority. (Its checklist lines and repeat are added by the
 *  server when it is made.) */
export const startsWith = (type: TaskTypeRead) => ({
  description: type.starting_values?.description ?? null,
  priority: type.starting_values?.priority ?? "medium",
});

/** What a task being added takes from `type` in place of what it took from
 *  `was`: each of the fields above the person has left as it started. */
export const startedFrom = (
  task: Pick<TaskRead, "description" | "priority">,
  was: TaskTypeRead,
  type: TaskTypeRead
): Partial<Pick<TaskRead, "description" | "priority">> => {
  const before = startsWith(was);
  const after = startsWith(type);
  return {
    ...((task.description ?? "") === (before.description ?? "")
      ? { description: after.description }
      : {}),
    ...(task.priority === before.priority ? { priority: after.priority } : {}),
  };
};

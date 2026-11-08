import { useMemo } from "react";

import type { ListMyTasksParams } from "@/api/generated/initiativeAPI.schemas";
import { useListMyTasks } from "@/api/generated/tasks/tasks";
import { browserTimezone } from "@/lib/timezones";

const OPEN = ["backlog", "todo", "in_progress"];

/**
 * How many of the reader's open tasks, across communities, fall due in a
 * window: `/me/tasks`' total, asking for one row. Not zero — a page size of
 * zero is the endpoint's "every row" window, not "no rows".
 *
 * `dueAfter` is inclusive and may be left open; `dueBefore` is exclusive.
 */
export const useOpenTaskCount = (dueAfter: string | null, dueBefore: string) => {
  const params = useMemo<ListMyTasksParams>(
    () => ({
      conditions: [
        { field: "status_category", op: "in_", value: OPEN },
        ...(dueAfter ? [{ field: "due_date", op: "gte" as const, value: dueAfter }] : []),
        { field: "due_date", op: "lt", value: dueBefore },
      ],
      page: 1,
      page_size: 1,
      tz: browserTimezone(),
    }),
    [dueAfter, dueBefore]
  );
  return useListMyTasks(params, {
    query: { staleTime: 60_000, select: (data) => data.total_count },
  });
};

/** How many tasks the reader has made, in any state, across communities. */
export const useCreatedTaskCount = () => {
  const params = useMemo<ListMyTasksParams>(
    () => ({ created: true, include_archived: true, page: 1, page_size: 1 }),
    []
  );
  return useListMyTasks(params, {
    query: { staleTime: 60_000, select: (data) => data.total_count },
  });
};

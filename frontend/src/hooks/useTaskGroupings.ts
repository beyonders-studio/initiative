/**
 * What a project's task list offers to group by, and the grouping it is
 * grouped by with the groups the server worked out for it.
 *
 * One hook for every surface that groups the list (the table, the board, the
 * layout editor's preview) so they ask the same question: the groups of the
 * tasks `params` lists, by the field and bucket the layout offers.
 */

import { keepPreviousData } from "@tanstack/react-query";
import type { GroupingState } from "@tanstack/react-table";
import { useMemo } from "react";

import type {
  LayoutGrouping,
  ListLayoutReadKind,
  ListTaskGroupsParams,
  ListTasksParams,
  TaskListRead,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useListTaskGroups } from "@/api/generated/tasks/tasks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useFieldCatalog } from "@/hooks/useFieldCatalog";
import { BOARD_COLUMNS, groupingName, taskGroups } from "@/lib/layouts/taskGroupings";
import type { TranslateFn } from "@/types/i18n";
import type { FieldDef } from "@/ui/layouts/fields";
import { activeGrouping, groupables, offeredGroupings } from "@/ui/layouts/grouping";
import { browserTimezone } from "@/ui/lib/timezones";

/** What a project's tasks can be grouped by: the catalog's fields that group,
 *  and the project's properties that do. */
export function useGroupables(fields: ReadonlyMap<string, FieldDef>, t: TranslateFn) {
  const { groupings: catalog } = useFieldCatalog("tasks");
  return useMemo(
    () => groupables(catalog, fields, (field) => groupingName(field, t), BOARD_COLUMNS),
    [catalog, fields, t]
  );
}

export function useTaskGroupings({
  fields,
  statuses,
  tasks,
  groupings,
  kind,
  grouping,
  params,
  t,
}: {
  fields: ReadonlyMap<string, FieldDef>;
  statuses: TaskStatusRead[];
  tasks: TaskListRead[];
  /** The layout's own groupings; none offers every field that groups. */
  groupings: LayoutGrouping[] | null | undefined;
  kind: ListLayoutReadKind;
  /** The table column the list is grouped by, as a person's view keeps it. */
  grouping: GroupingState;
  /** The list the groups are of; none, for tasks that are not one. */
  params?: ListTasksParams;
  t: TranslateFn;
}) {
  const communityId = useActiveCommunityId();
  const all = useGroupables(fields, t);
  const entry = useMemo(
    () => activeGrouping(groupings, kind, grouping, all),
    [groupings, kind, grouping, all]
  );
  const groupParams = useMemo<ListTaskGroupsParams | undefined>(
    () =>
      entry && params
        ? {
            group_by: entry.field,
            bucket: entry.bucket,
            conditions: params.conditions,
            include_archived: params.include_archived,
            tz: browserTimezone(),
          }
        : undefined,
    [entry, params]
  );
  const served = useListTaskGroups(communityId, groupParams as ListTaskGroupsParams, {
    query: {
      enabled: groupParams !== undefined,
      // A task moved between groups, or a filter changed, keeps the list grouped
      // by the same field while it refreshes; another field waits for its own.
      placeholderData: (previous, query) => {
        const was = query?.queryKey[1] as ListTaskGroupsParams | undefined;
        return was?.group_by === groupParams?.group_by && was?.bucket === groupParams?.bucket
          ? keepPreviousData(previous)
          : undefined;
      },
    },
  });
  const data = groupParams && served.data ? served.data : undefined;
  const offered = useMemo(
    () =>
      offeredGroupings({
        all,
        groupings,
        kind,
        items: tasks,
        own: taskGroups({ statuses, tasks, t }),
        served: data && entry ? { field: entry.field, data } : undefined,
        t,
      }),
    [all, groupings, kind, statuses, tasks, data, entry, t]
  );
  // Grouped only once its groups are in, so a list never shows every task in
  // the empty group while they are on their way.
  const active = data ? offered.find((each) => grouping.includes(each.grouping.column)) : undefined;
  return { all, offered, active, entry };
}

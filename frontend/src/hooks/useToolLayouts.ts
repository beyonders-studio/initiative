/**
 * How an instance of a tool lists what it holds, and shows one of them: its
 * layouts. A project has a table, a board and a Gantt, and a task's detail;
 * the initiative's calendar has the event's detail;
 * each is drawn as shipped until it is changed, and is changed on its own. How
 * a person narrows a list, and sorts it, is theirs (their view, kept by
 * {@link useProjectTaskView}), not the layout's.
 *
 * The set carries `can_configure`, computed server-side (the project's owner,
 * the initiative's managers, a community admin). Permission is never derived
 * client-side, and this is the one request that answers it for the tasks page
 * and the settings alike.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type DetailLayoutDefinitionInput,
  type DetailLayoutRead,
  type DetailLayoutWrite,
  type GetLayoutsParams,
  type ListLayoutRead,
  type ListLayoutReadKind,
  type ListLayoutWrite,
  Tool,
  type ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getGetInitiativeLayoutsQueryKey,
  getGetLayoutsQueryKey,
  getInitiativeLayouts,
  getLayouts,
  putDefaultLayout,
  putLayout,
  resetLayout,
} from "@/api/generated/layouts/layouts";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/** The tools whose every instance lays out its own items: the backend's
 *  per-instance layout tools that draw a detail. */
export const INSTANCE_LAYOUT_TOOLS: ReadonlySet<Tool> = new Set([
  Tool.project,
  Tool.queue,
  Tool.counter_group,
  Tool.catalog,
]);

/** The layouts one instance of a tool keeps as its own: a project's, a queue's. */
export const instanceTarget = (tool: Tool, id: number): GetLayoutsParams => ({
  tool,
  tool_id: id,
});

/** A tool the whole initiative shares (its calendar, its posts), whose
 *  layouts are the initiative's. */
export const sharedTarget = (tool: Tool, initiativeId: number): GetLayoutsParams => ({
  tool,
  initiative_id: initiativeId,
});

export const toolLayoutsQuery = (communityId: number, target: GetLayoutsParams) => ({
  queryKey: getGetLayoutsQueryKey(communityId, target),
  queryFn: () => getLayouts(communityId, target),
});

/** A target's layouts, or nothing while `target` is null. */
export const useToolLayouts = (target: GetLayoutsParams | null) => {
  const communityId = useActiveCommunityId();
  return useQuery<ToolLayoutSetRead>({
    ...toolLayoutsQuery(communityId, target ?? instanceTarget(Tool.project, 0)),
    enabled: target !== null,
    // The client keeps previous data by default, which across a target switch
    // would show the last target's layouts — and its `can_configure`, which
    // gates the editor. Showing one target's permissions while another loads
    // is not a stale list, it is the wrong answer.
    placeholderData: undefined,
  });
};

/** One instance's own layouts, or nothing while `id` is not one. */
export const useInstanceLayouts = (tool: Tool, id: number | null) =>
  useToolLayouts(id !== null && Number.isFinite(id) ? instanceTarget(tool, id) : null);

/** Every project's layouts in an initiative the reader can open, for its
 *  settings, with whether the reader may change each. */
export const useInitiativeLayouts = (initiativeId: number) => {
  const communityId = useActiveCommunityId();
  const params = { initiative_id: initiativeId };
  return useQuery({
    queryKey: getGetInitiativeLayoutsQueryKey(communityId, params),
    queryFn: () => getInitiativeLayouts(communityId, params),
    // Another initiative's projects, while this one's load, would be listed
    // under this one's addresses.
    placeholderData: undefined,
  });
};

const isList = (layout: ListLayoutRead | DetailLayoutRead): layout is ListLayoutRead =>
  "is_default" in layout;

/** The ways a target lists what it holds, in the order its tool draws them. */
export const listLayouts = (set: Pick<ToolLayoutSetRead, "layouts"> | undefined) =>
  (set?.layouts ?? []).filter(isList);

/** The target's details, in the order its tool draws them. */
export const detailLayouts = (set: Pick<ToolLayoutSetRead, "layouts"> | undefined) =>
  (set?.layouts ?? []).filter((layout): layout is DetailLayoutRead => !isList(layout));

/** One detail's layout as changed, or null where it is drawn as shipped. */
export const detailLayoutOf = (
  set: ToolLayoutSetRead | undefined,
  kind: DetailLayoutRead["kind"],
  /** For a detail laid out per type (a project's task page), which type's. */
  taskTypeId?: number | null
): DetailLayoutDefinitionInput | null => {
  const layout = detailLayouts(set).find(
    (each) => each.kind === kind && (each.task_type_id ?? null) === (taskTypeId ?? null)
  );
  return layout?.updated_at ? (layout.definition as DetailLayoutDefinitionInput) : null;
};

/** One change to a target's layouts: one saved, one put back as shipped, or
 *  the list it opens on. */
export type LayoutChange =
  | { save: ListLayoutWrite | DetailLayoutWrite }
  | {
      reset: ListLayoutReadKind | DetailLayoutRead["kind"];
      /** For a detail laid out per type: which type's page. */
      taskTypeId?: number;
    }
  | { opensOn: ListLayoutReadKind };

/** Make `changes`, one request each, in order, writing each answer to the
 *  target's set as it comes. Each layout keeps its own date: nothing else is
 *  sent, so nothing else changes. Answers with the set as the last change
 *  left it. */
export const useSaveLayouts = (
  target: GetLayoutsParams,
  options?: MutationOpts<ToolLayoutSetRead | undefined, LayoutChange[]>
) => {
  const queryClient = useQueryClient();
  return useCommunityMutation<ToolLayoutSetRead | undefined, LayoutChange[]>(
    {
      mutationFn: async (communityId, changes) => {
        let set: ToolLayoutSetRead | undefined;
        for (const change of changes) {
          set =
            "save" in change
              ? await putLayout(communityId, change.save, target)
              : "reset" in change
                ? await resetLayout(communityId, change.reset, {
                    ...target,
                    ...(change.taskTypeId ? { task_type_id: change.taskTypeId } : {}),
                  })
                : await putDefaultLayout(communityId, { kind: change.opensOn }, target);
          queryClient.setQueryData(getGetLayoutsQueryKey(communityId, target), set);
        }
        return set;
      },
      // The set is each answer; the initiative's list of layouts, and how full
      // the board's limited columns are, read anew.
      invalidate: () => invalidate(q.initiativeLayouts(), q.columnLimits()),
      errorKey: "layouts:saveError",
    },
    options
  );
};

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

import { useQueryClient } from "@tanstack/react-query";

import {
  type GetLayoutsParams,
  type LayoutTarget,
  Tool,
  type ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getGetLayoutsQueryKey,
  getGetLayoutsQueryOptions,
  putDefaultLayout,
  putLayout,
  resetLayout,
  useGetInitiativeLayouts,
  useGetLayouts,
} from "@/api/generated/layouts/layouts";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { LayoutChange } from "@/ui/layouts/layoutSet";

/** The tools whose every instance lays out its own items: the backend's
 *  per-instance layout tools that draw a detail. */
export const INSTANCE_LAYOUT_TOOLS: ReadonlySet<Tool> = new Set([Tool.project, Tool.counter_group]);

/** The layouts one instance of a tool keeps as its own: a project's, or a
 *  collection's, which lays out its files as an instance does. */
export const instanceTarget = (tool: LayoutTarget, id: number): GetLayoutsParams => ({
  tool,
  tool_id: id,
});

/** A tool the whole initiative shares (its calendar, its posts), whose
 *  layouts are the initiative's. */
export const sharedTarget = (tool: Tool, initiativeId: number): GetLayoutsParams => ({
  tool,
  initiative_id: initiativeId,
});

/** A target's layouts, or nothing while `target` is null. */
export const useToolLayouts = (target: GetLayoutsParams | null) => {
  const communityId = useActiveCommunityId();
  return useGetLayouts(communityId, target ?? instanceTarget(Tool.project, 0), {
    query: {
      enabled: target !== null,
      // The client keeps previous data by default, which across a target switch
      // would show the last target's layouts — and its `can_configure`, which
      // gates the editor. Showing one target's permissions while another loads
      // is not a stale list, it is the wrong answer.
      placeholderData: undefined,
    },
  });
};

/** One instance's own layouts, or nothing while `id` is not one. */
export const useInstanceLayouts = (tool: LayoutTarget, id: number | null) =>
  useToolLayouts(id !== null && Number.isFinite(id) ? instanceTarget(tool, id) : null);

/** Reads a target's layouts when asked, from the cache where they are held:
 *  for a decision made on a click, such as what a collection requires of the
 *  files going in. */
export const useReadToolLayouts = () => {
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  return (target: GetLayoutsParams) =>
    queryClient.fetchQuery(getGetLayoutsQueryOptions(communityId, target));
};

/** Every project's layouts in an initiative the reader can open, for its
 *  settings, with whether the reader may change each. */
export const useInitiativeLayouts = (initiativeId: number) => {
  const communityId = useActiveCommunityId();
  const params = { initiative_id: initiativeId };
  return useGetInitiativeLayouts(communityId, params, {
    // Another initiative's projects, while this one's load, would be listed
    // under this one's addresses.
    query: { placeholderData: undefined },
  });
};

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

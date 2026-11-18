import type { Tool, ToolCommentSettings } from "@/api/generated/initiativeAPI.schemas";
import { setToolCommentSettings } from "@/api/generated/tools/tools";
import { invalidate, q } from "@/api/query-keys";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * The one comment-switch mutation for every tool — PUTs the new state to the
 * generic `/tools/{tool}/{toolId}/comments` route, then invalidates that tool's
 * list + detail queries so the settings page and the entity's page agree on
 * whether the thread is there.
 *
 * Tasks are sub-resources, not tools: their threads are part of
 * their own flow and have no switch.
 */
export const useSetToolComments = (
  tool: Tool,
  options?: MutationOpts<ToolCommentSettings, { id: number; enabled: boolean }>
) =>
  useCommunityMutation<ToolCommentSettings, { id: number; enabled: boolean }>(
    {
      mutationFn: (communityId, { id, enabled }) =>
        setToolCommentSettings(communityId, tool, id, {
          comments_enabled: enabled,
        }),
      invalidate: (_data, vars) => {
        invalidate(q.tool(tool, vars.id));
        // The thread itself: turning the switch back on shows the comments that
        // were there all along, so the cached (refused) read must go.
        void invalidate(q.allComments());
      },
      errorKey: "common:toolSettings.commentsError",
    },
    options
  );

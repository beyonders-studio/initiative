import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { apiMutator } from "@/api/mutator";
import { invalidate, q } from "@/api/query-keys";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { type ToolCommentEntity, toolRouteSegment } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";

/**
 * The one comment-switch mutation for every tool — the `comments_enabled`
 * field of the tool's own update (`PATCH /{tool}/{toolId}`), then invalidates
 * that tool's list + detail queries so the settings page and the entity's page
 * agree on whether the thread is there.
 *
 * Tasks are sub-resources, not tools: their threads are part of
 * their own flow and have no switch.
 */
export const useSetToolComments = (
  tool: Tool,
  options?: MutationOpts<ToolCommentEntity, { id: number; enabled: boolean }>
) =>
  useCommunityMutation<ToolCommentEntity, { id: number; enabled: boolean }>(
    {
      mutationFn: (communityId, { id, enabled }) =>
        apiMutator<ToolCommentEntity>({
          url: `/api/v1/c/${communityId}/${toolRouteSegment(tool)}/${id}`,
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          data: { comments_enabled: enabled },
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

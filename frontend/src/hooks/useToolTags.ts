import type { TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { setToolTags } from "@/api/generated/tools/tools";
import { invalidate, q } from "@/api/query-keys";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * The one set-tags mutation for every tool — PUTs the FULL tag id list (the
 * picker owns the complete selection, so there is no read-modify) to the
 * generic `/tools/{tool}/{toolId}/tags` route, then invalidates that tool's
 * list + detail queries so every consumer reflects the change.
 *
 * Tasks and events are sub-resources, not tools — their tags are
 * set by their own update (`tag_ids` on the PATCH).
 */
export const useSetToolTags = (
  tool: Tool,
  options?: MutationOpts<TagSummary[], { id: number; tagIds: number[] }>
) =>
  useCommunityMutation<TagSummary[], { id: number; tagIds: number[] }>(
    {
      mutationFn: (communityId, { id, tagIds }) =>
        setToolTags(communityId, tool, id, {
          tag_ids: tagIds,
        }),
      invalidate: (_data, vars) => invalidate(q.tool(tool, vars.id)),
      errorKey: "tags:toolTagsError",
    },
    options
  );

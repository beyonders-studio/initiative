import type { TagSetRequest, TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  setCalendarTags,
  setContactTags,
  setCounterGroupTags,
  setDashboardTags,
  setFileTags,
  setPostTags,
  setProjectTags,
  setWikiTags,
} from "@/api/generated/tools/tools";
import { invalidate, q } from "@/api/query-keys";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/** Each tool's `PUT /{tool}/{id}/tags`, one route shape for every tool. */
const SET_TAGS: Record<
  Tool,
  (communityId: number, id: number, data: TagSetRequest) => Promise<TagSummary[]>
> = {
  project: setProjectTags,
  file: setFileTags,
  counter_group: setCounterGroupTags,
  calendar: setCalendarTags,
  dashboard: setDashboardTags,
  post: setPostTags,
  wiki: setWikiTags,
  contact: setContactTags,
};

/**
 * The one set-tags mutation for every tool — PUTs the FULL tag id list (the
 * picker owns the complete selection, so there is no read-modify) to the
 * tool's `/{tool}/{id}/tags` route, then invalidates that tool's list +
 * detail queries so every consumer reflects the change.
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
        SET_TAGS[tool](communityId, id, {
          tag_ids: tagIds,
        }),
      invalidate: (_data, vars) => invalidate(q.tool(tool, vars.id)),
      errorKey: "tags:toolTagsError",
    },
    options
  );

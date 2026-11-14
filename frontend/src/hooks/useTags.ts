import { keepPreviousData } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  GetTagEntitiesParams,
  TagCreate,
  TagRead,
  TagUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createTag,
  deleteTag,
  updateTag,
  useGetTag,
  useGetTagCounts,
  useGetTagEntities,
  useListTags,
} from "@/api/generated/tags/tags";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/mascotToast";
import type { MutationOpts } from "@/types/mutation";

/** Refresh every list that embeds TagSummary chips — a rename/recolor or
 * delete must reach all of them, not just the tags list. */
const invalidateTagBearers = () => {
  void invalidate(
    q.allTasks(),
    q.allProjects(),
    q.allFiles(),
    q.allCounterGroups(),
    q.allCalendars()
  );
};

export const useTags = (options?: { enabled?: boolean }) => {
  const communityId = useActiveCommunityId();
  return useListTags(communityId, {
    query: { staleTime: 60 * 1000, enabled: options?.enabled ?? true },
  });
};

/**
 * Saved tag ids, less any the community no longer has. A deleted tag does not
 * quietly stop narrowing: sent as `tag_ids in (42)` it matches nothing, so the
 * list goes empty while the picker has no tag left to show why. While the
 * tags load the ids stand; if they can't be read they are dropped, because an
 * id that cannot be checked may be hiding everything. Derived rather than
 * written back: the next change to the filters keeps the pruned set.
 */
export const useKnownTagIds = (ids: number[]): number[] => {
  const { data: tags, isSuccess, isError } = useTags();
  return useMemo(() => {
    if (isError) return ids.length > 0 ? [] : ids;
    if (!isSuccess) return ids;
    const known = new Set(tags.map((tag) => tag.id));
    const kept = ids.filter((id) => known.has(id));
    return kept.length === ids.length ? ids : kept;
  }, [ids, tags, isSuccess, isError]);
};

export const useTag = (tagId: number | null) => {
  const communityId = useActiveCommunityId();
  return useGetTag(communityId, tagId!, undefined, {
    query: { enabled: !!tagId, staleTime: 60 * 1000 },
  });
};

export const useCreateTag = (options?: MutationOpts<TagRead, TagCreate>) =>
  useCommunityMutation<TagRead, TagCreate>(
    {
      mutationFn: (communityId, data) => createTag(communityId, data),
      invalidate: () => invalidate(q.allTags()),
      errorKey: "tags:createError",
    },
    options
  );

export const useUpdateTag = (
  options?: MutationOpts<TagRead, { tagId: number; data: TagUpdate }>
) => {
  const { t } = useTranslation("tags");
  return useCommunityMutation<TagRead, { tagId: number; data: TagUpdate }>(
    {
      mutationFn: (communityId, { tagId, data }) => updateTag(communityId, tagId, data),
      invalidate: () => {
        toast.success(t("updated"));
        void invalidate(q.allTags());
        invalidateTagBearers();
      },
      errorKey: "tags:updateError",
    },
    options
  );
};

export const useDeleteTag = (
  options?: MutationOpts<void, number> & {
    /** Skip the per-delete success toast — for batch callers that show one
     * summary toast instead. Error toasts still fire per tag. */
    silent?: boolean;
  }
) => {
  const { t } = useTranslation("tags");
  const { silent, ...rest } = options ?? {};
  return useCommunityMutation<void, number>(
    {
      mutationFn: async (communityId, tagId) => {
        await deleteTag(communityId, tagId);
      },
      invalidate: () => {
        if (!silent) {
          toast.success(t("deleted"));
        }
        void invalidate(q.allTags());
        invalidateTagBearers();
      },
      errorKey: "tags:deleteError",
    },
    rest
  );
};

/** How many things of each taggable kind carry the tag, keyed by kind — the
 *  tag page's tabs, before any of their tables is read. */
export const useTagCounts = (tagId: number | null) => {
  const communityId = useActiveCommunityId();
  return useGetTagCounts(communityId, tagId!, { query: { enabled: !!tagId } });
};

/** One page of the things of one kind carrying the tag. The page in hand stays
 *  up while the next one is read. */
export const useTagEntities = (tagId: number, params: GetTagEntitiesParams) => {
  const communityId = useActiveCommunityId();
  return useGetTagEntities(communityId, tagId, params, {
    query: { placeholderData: keepPreviousData },
  });
};

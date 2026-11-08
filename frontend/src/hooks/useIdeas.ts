/**
 * The published ideas on Initiative Cloud, readable signed in or not, the
 * votes for them, and the team's Idea panel on an Ideas-board task.
 */

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  getListIdeasQueryKey,
  getReadIdeaQueryKey,
  listIdeas,
  readIdea,
  takeVoteBack,
  voteForIdea,
} from "@/api/generated/ideas/ideas";
import type {
  IdeaListRead,
  IdeaPanelRead,
  IdeaRead,
  ListIdeasParams,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getReadTaskIdeaQueryKey,
  publishTaskIdea,
  readTaskIdea,
  unpublishTaskIdea,
} from "@/api/generated/tasks/tasks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

/** Every read of the ideas list and of one idea. */
const refreshIdeas = () =>
  queryClient.invalidateQueries({
    predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/ideas"),
  });

/** How many ideas a page holds. */
const PAGE_SIZE = 50;

/** The published ideas, a page at a time. */
export const useIdeas = (params: Omit<ListIdeasParams, "page" | "page_size">) =>
  useInfiniteQuery({
    queryKey: getListIdeasQueryKey(params),
    queryFn: ({ pageParam }) => listIdeas({ ...params, page: pageParam, page_size: PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (last: IdeaListRead, pages) =>
      pages.length * PAGE_SIZE < last.total ? pages.length + 1 : undefined,
    placeholderData: keepPreviousData,
    retry: false,
  });

/** One published idea, with its description. */
export const useIdea = (taskId: number) =>
  useQuery<IdeaRead>({
    queryKey: getReadIdeaQueryKey(taskId),
    queryFn: () => readIdea(taskId),
    enabled: Number.isFinite(taskId),
    retry: false,
  });

/** Vote for an idea, or take the vote back. */
export const useVoteForIdea = (options?: MutationOpts<IdeaRead, { taskId: number; on: boolean }>) =>
  useApiMutation<IdeaRead, { taskId: number; on: boolean }>(
    {
      mutationFn: ({ taskId, on }) => (on ? voteForIdea(taskId) : takeVoteBack(taskId)),
      invalidate: refreshIdeas,
    },
    options
  );

/** An Ideas-board task's panel; a 404, the usual answer, for any other task. */
export const useTaskIdea = (taskId: number) => {
  const communityId = useActiveCommunityId();
  return useQuery<IdeaPanelRead>({
    queryKey: getReadTaskIdeaQueryKey(communityId, taskId),
    queryFn: () => readTaskIdea(communityId, taskId),
    enabled: Number.isFinite(taskId),
    retry: false,
  });
};

/** Publish an Ideas-board task, or take it off the Ideas page. */
export const usePublishTaskIdea = (
  taskId: number,
  options?: MutationOpts<IdeaPanelRead, boolean>
) => {
  const communityId = useActiveCommunityId();
  return useApiMutation<IdeaPanelRead, boolean>(
    {
      mutationFn: (on) =>
        on ? publishTaskIdea(communityId, taskId) : unpublishTaskIdea(communityId, taskId),
      invalidate: () =>
        Promise.all([
          queryClient.invalidateQueries({
            queryKey: getReadTaskIdeaQueryKey(communityId, taskId),
          }),
          refreshIdeas(),
        ]),
    },
    options
  );
};

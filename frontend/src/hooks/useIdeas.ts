/**
 * The published ideas on Initiative Cloud, readable signed in or not, and the
 * votes for them.
 */

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  getListIdeasQueryKey,
  getListShippedQueryKey,
  getReadIdeaQueryKey,
  getReadRoadmapQueryKey,
  getSimilarIdeasQueryKey,
  listIdeas,
  listShipped,
  readIdea,
  readRoadmap,
  similarIdeas,
  takeVoteBack,
  voteForIdea,
} from "@/api/generated/ideas/ideas";
import type {
  IdeaListRead,
  IdeaRead,
  IdeaRoadmapRead,
  ListIdeasParams,
} from "@/api/generated/initiativeAPI.schemas";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

/** Every read of the ideas: the list, the roadmap, what shipped and one idea. */
export const refreshIdeas = () =>
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
    getNextPageParam: (last: IdeaListRead) => (last.has_next ? last.page + 1 : undefined),
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

/** The roadmap: the board's in-progress statuses, then the shipped one,
 *  each with its published ideas. */
export const useIdeaRoadmap = () =>
  useQuery<IdeaRoadmapRead>({
    queryKey: getReadRoadmapQueryKey(),
    queryFn: () => readRoadmap(),
    retry: false,
  });

/** The published ideas that shipped in `release`; nothing asked for while
 *  `enabled` is false. */
export const useShippedIdeas = (release: string, enabled: boolean) =>
  useQuery<IdeaRead[]>({
    queryKey: getListShippedQueryKey({ release }),
    queryFn: () => listShipped({ release }),
    enabled,
    retry: false,
  });

/** The open published ideas close to `text`, closest first; nothing asked
 *  for while `text` is empty. */
export const useSimilarIdeas = (text: string) =>
  useQuery<IdeaRead[]>({
    queryKey: getSimilarIdeasQueryKey({ text }),
    queryFn: () => similarIdeas({ text }),
    enabled: text.length > 0,
    placeholderData: keepPreviousData,
    retry: false,
  });

/** Vote for an idea, or take the vote back. */
export const useVoteForIdea = (options?: MutationOpts<IdeaRead, { taskId: number; on: boolean }>) =>
  useApiMutation<IdeaRead, { taskId: number; on: boolean }>(
    {
      mutationFn: ({ taskId, on }) => (on ? voteForIdea(taskId) : takeVoteBack(taskId)),
      invalidate: refreshIdeas,
      errorKey: "intake:ideas.voteError",
    },
    options
  );

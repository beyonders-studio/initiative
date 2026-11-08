import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import type {
  GetPostTimelineParams,
  ListPostsParams,
  PollRead,
  PollVoters,
  PollVoteWrite,
  PollWrite,
  PostListResponse,
  PostPinUpdate,
  PostRead,
  PostReaders,
  PostReadMarks,
  PostReadReceipt,
  PostUpdate,
  TimelineResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  deletePostPoll,
  getListPostsQueryKey,
  getReadPostQueryKey,
  listPosts,
  markPostsRead,
  markPostUnread,
  retractPostPollVote,
  setPostPin,
  setPostPoll,
  updatePost,
  useGetPostTimeline,
  useListPostPollVoters,
  useListPostReaders,
  voteOnPostPoll,
} from "@/api/generated/posts/posts";
import { invalidate, patchCachedPost, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const posts = TOOL_HOOKS[Tool.post];
export const usePost = posts.useDetail;
export const useCreatePost = posts.useCreate;
export const useUpdatePost = posts.useUpdate;

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * The board, page by page, as somebody scrolls it.
 *
 * A board is read downwards, not paged through, so this is an infinite query
 * rather than a page cursor in the URL. Pages are small — five — because each
 * row is a body the client mounts an editor for, and what a page bounds is how
 * much is fetched ahead of the reader, not how much they have to look at.
 */
export const usePostsFeed = (params?: ListPostsParams) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    queryKey: getListPostsQueryKey(communityId, params),
    queryFn: ({ pageParam }) => listPosts(communityId, { ...params, page: pageParam as number }),
    initialPageParam: 1,
    getNextPageParam: (last: PostListResponse) => (last.has_next ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
  });
};

/**
 * Who has read a notice, and who it is still waiting on.
 *
 * Fetched when somebody asks — the count is on the card, and the roster behind
 * it is a click. A board of five cards should not fetch five rosters nobody
 * opened.
 */
export const usePostReaders = (postId: number, options?: QueryOpts<PostReaders>) => {
  const communityId = useActiveCommunityId();
  return useListPostReaders(communityId, postId, { query: options });
};

/**
 * The months this board has notices in — what the timeline rail is drawn from.
 *
 * Takes the same filters the feed does, because the rail is a picture of the
 * feed as it currently stands: with the unread filter on, a month that is
 * fully read is not a stop worth offering. The reader's own zone goes with it,
 * since a month is a boundary in somebody's day.
 */
export const usePostsTimeline = (
  params?: GetPostTimelineParams,
  options?: QueryOpts<TimelineResponse>
) => {
  const communityId = useActiveCommunityId();
  return useGetPostTimeline(communityId, params, { query: options });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidatePostAndList = (postId: number) => invalidate(q.post(postId), q.allPosts());

/**
 * Pin a notice to the top of its board, or take it down.
 *
 * Invalidates the whole list rather than patching the cached row: pinning
 * changes the board's *order*, not just this post, so every page of it is
 * stale.
 */
export const useSetPostPin = (postId: number, options?: MutationOpts<PostRead, PostPinUpdate>) =>
  useCommunityMutation<PostRead, PostPinUpdate>(
    {
      mutationFn: (communityId, data) => setPostPin(communityId, postId, data),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );

/**
 * Write one post's read state into every cached copy of it.
 *
 * The count moves with it: marking read adds this reader to it, marking unread
 * takes them back off, so "Read by 12" does not sit there contradicting the
 * button beside it.
 */
const setCachedReadState = (postId: number, isRead: boolean) =>
  patchCachedPost(postId, (post) => {
    if (post.is_read === isRead) return post;
    return {
      ...post,
      is_read: isRead,
      read_count: Math.max(0, post.read_count + (isRead ? 1 : -1)),
    };
  });

/**
 * Tell the server which notices have been on screen.
 *
 * Deliberately does NOT invalidate. Read state changes continuously as
 * somebody scrolls, and refetching for it would move rows under the cursor —
 * and with the unread filter on, delete the one being read. The cached copies
 * are patched instead.
 *
 * Patched on the way OUT rather than on the way back, because nothing here
 * refetches: without an optimistic write the card would keep saying unread
 * until something else happened to refresh it. Put back if the request fails,
 * so a dropped connection does not quietly mark a board read.
 */
export const useMarkPostsRead = (options?: MutationOpts<PostReadReceipt, PostReadMarks>) =>
  useCommunityMutation<PostReadReceipt, PostReadMarks>(
    {
      mutationFn: (communityId, data) => markPostsRead(communityId, data),
      errorKey: "posts:error",
    },
    {
      ...options,
      // Rest args rather than a named signature, so this composes with
      // whatever arity react-query hands the caller's own callbacks.
      onMutate: (...args) => {
        for (const id of args[0].post_ids) setCachedReadState(id, true);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        for (const id of args[1].post_ids) setCachedReadState(id, false);
        options?.onError?.(...args);
      },
      // Only when something actually became read. Reading is a one-way move
      // per notice, so this fires at most once per notice rather than once per
      // batch — which is what keeps a scroll from refetching the rail every
      // second and a half.
      onSuccess: (...args) => {
        if (args[0].marked > 0) void invalidate(q.postTimeline());
        options?.onSuccess?.(...args);
      },
    }
  );

/**
 * Put one notice back to unread.
 *
 * Optimistic for the same reason: this is a button somebody pressed, and
 * nothing invalidates behind it, so the card has to answer immediately or look
 * broken. Restored on failure.
 */
export const useMarkPostUnread = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, postId) => markPostUnread(communityId, postId),
      errorKey: "posts:error",
    },
    {
      ...options,
      onMutate: (...args) => {
        setCachedReadState(args[0], false);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        setCachedReadState(args[1], true);
        options?.onError?.(...args);
      },
      // A deliberate click, and it puts a month back on the rail under the
      // unread filter.
      onSuccess: (...args) => {
        void invalidate(q.postTimeline());
        options?.onSuccess?.(...args);
      },
    }
  );

// ── Polls ───────────────────────────────────────────────────────────────────

/**
 * Who chose what on a notice's poll.
 *
 * Fetched when somebody asks, like the read roster: the tallies are already on
 * the card, and the names behind them are a click.
 */
export const usePostPollVoters = (postId: number, options?: QueryOpts<PollVoters>) => {
  const communityId = useActiveCommunityId();
  return useListPostPollVoters(communityId, postId, { query: options });
};

/**
 * Write the whole post back into every cache that holds it.
 *
 * Every poll route answers with the notice a read would return, so seeding is
 * enough and nothing has to refetch. Deliberately NOT an invalidation: a vote
 * does not change the board's order, and refetching the feed for one would
 * move rows under the cursor mid-scroll.
 */
const seedCachedPost = (post: PostRead) => patchCachedPost(post.id, () => post);

/**
 * This ballot, applied to the poll on screen.
 *
 * Derivable in full: the ids that changed move their own tally by one, and the
 * voter count moves only when somebody goes from having answered to not, or
 * back. The one case it cannot answer is a poll whose numbers are still hidden
 * — there is nothing on the client to add one to — so it records the ballot
 * and leaves the reveal to the response.
 */
const applyBallot = (poll: PollRead, optionIds: number[]): PollRead => {
  const after = new Set(optionIds);
  const hadVoted = poll.options.some((option) => option.voted_by_me);
  const hasVoted = after.size > 0;
  const options = poll.options.map((option) => {
    const now = after.has(option.id);
    if (now === option.voted_by_me) return option;
    const count = option.vote_count;
    return {
      ...option,
      voted_by_me: now,
      vote_count: typeof count === "number" ? Math.max(0, count + (now ? 1 : -1)) : count,
    };
  });
  if (!poll.results_visible) {
    return { ...poll, options, has_voted: hasVoted };
  }
  const total = poll.total_voters ?? 0;
  const delta = hasVoted === hadVoted ? 0 : hasVoted ? 1 : -1;
  return { ...poll, options, has_voted: hasVoted, total_voters: total + delta };
};

const setCachedBallot = (postId: number, optionIds: number[]) =>
  patchCachedPost(postId, (post) => {
    if (!post.poll) return post;
    return { ...post, poll: applyBallot(post.poll, optionIds) };
  });

/**
 * Give a notice its question, or rewrite the one it has.
 *
 * Invalidates rather than seeding: writing a poll is an edit of the notice, so
 * the surfaces that count or excerpt it are stale too.
 */
export const useSetPostPoll = (postId: number, options?: MutationOpts<PostRead, PollWrite>) =>
  useCommunityMutation<PostRead, PollWrite>(
    {
      mutationFn: (communityId, data) => setPostPoll(communityId, postId, data),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );

export const useDeletePostPoll = (postId: number, options?: MutationOpts<PostRead, void>) =>
  useCommunityMutation<PostRead, void>(
    {
      mutationFn: (communityId) => deletePostPoll(communityId, postId),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );

/**
 * Answer a notice's question.
 *
 * Optimistic for the reason marking read is: nothing behind this refetches the
 * board, so the card has to answer the click immediately or look broken. The
 * response then replaces the guess with the server's own count, which is what
 * settles a tally two people moved at once.
 */
export const useVoteOnPostPoll = (
  postId: number,
  options?: MutationOpts<PostRead, PollVoteWrite>
) =>
  useCommunityMutation<PostRead, PollVoteWrite>(
    {
      mutationFn: (communityId, data) => voteOnPostPoll(communityId, postId, data),
      errorKey: "posts:error",
    },
    {
      ...options,
      onMutate: (...args) => {
        setCachedBallot(postId, args[0].option_ids ?? []);
        return options?.onMutate?.(...args);
      },
      onSuccess: (...args) => {
        seedCachedPost(args[0]);
        options?.onSuccess?.(...args);
      },
      // Put the board back the way it was. The cached copy is the only record
      // of the previous ballot, so it is re-read rather than remembered.
      onError: (...args) => {
        invalidate(q.post(postId));
        options?.onError?.(...args);
      },
    }
  );

export const useRetractPostPollVote = (postId: number, options?: MutationOpts<PostRead, void>) =>
  useCommunityMutation<PostRead, void>(
    {
      mutationFn: (communityId) => retractPostPollVote(communityId, postId),
      errorKey: "posts:error",
    },
    {
      ...options,
      onMutate: (...args) => {
        setCachedBallot(postId, []);
        return options?.onMutate?.(...args);
      },
      onSuccess: (...args) => {
        seedCachedPost(args[0]);
        options?.onSuccess?.(...args);
      },
      onError: (...args) => {
        invalidate(q.post(postId));
        options?.onError?.(...args);
      },
    }
  );

/** How a notice's properties are saved one at a time, into its own read. Its
 *  body, poll and schedule are saved by their own buttons. */
export const POST_SAVES: FieldSaveKind<PostRead, PostUpdate> = {
  name: "post",
  readKey: (communityId, id) => getReadPostQueryKey(communityId, id),
  patch: (communityId, id, patch) => updatePost(communityId, id, patch),
  properties: PropertyTarget.post,
  lists: () => q.allPosts(),
  itself: (id) => q.post(id),
};

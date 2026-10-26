import {
  type InfiniteData,
  infiniteQueryOptions,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  createComment,
  deleteComment,
  getListCommentsQueryKey,
  getRecentCommentsQueryKey,
  listComments,
  readComment,
  recentComments,
  updateComment,
} from "@/api/generated/comments/comments";
import {
  CommentAudience,
  type CommentListResponse,
  type CommentRead,
  type ListCommentsParams,
  type RecentActivityEntry,
  type RecentCommentsParams,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { refreshTaskCase } from "@/hooks/useTickets";
import { getHttpStatus } from "@/lib/errorMessage";
import { queryClient } from "@/lib/queryClient";
import { singularOf } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Conversations per page — a top-level comment and every reply under it. */
const COMMENT_PAGE_SIZE = 20;

/** Which thread: exactly one `{target}_id`. The page size and the cursor are
 *  the query's own, so they stay out of the key. */
export type CommentThreadParams = Omit<ListCommentsParams, "limit" | "cursor">;

type CommentThreadData = InfiniteData<CommentListResponse>;

/** One thread as an infinite query — shared by the hook and the route loaders
 *  that warm it, so both land in the same cache entry. */
export const commentThreadQueryOptions = (communityId: number, params: CommentThreadParams) =>
  infiniteQueryOptions({
    queryKey: getListCommentsQueryKey(communityId, params),
    queryFn: ({ pageParam, signal }) =>
      listComments(
        communityId,
        { ...params, limit: COMMENT_PAGE_SIZE, cursor: pageParam },
        undefined,
        signal
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: CommentListResponse) => last.next_cursor ?? undefined,
  });

/** Every loaded comment as one list. A conversation put on the first page as
 *  it arrived (one restored from the trash, say) can turn up again on an
 *  older page loaded afterwards; it is listed once. */
const flattenThread = (data: CommentThreadData) => {
  const seen = new Set<number>();
  return data.pages
    .flatMap((page) => page.comments)
    .filter((comment) => {
      if (seen.has(comment.id)) return false;
      seen.add(comment.id);
      return true;
    });
};

/**
 * One comment thread, newest conversations first, a page at a time.
 *
 * `data` is every comment loaded so far as one list; `fetchNextPage` brings
 * the next older page of conversations.
 */
export const useComments = (params: CommentThreadParams, options?: { enabled?: boolean }) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    ...commentThreadQueryOptions(communityId, params),
    select: flattenThread,
    enabled: options?.enabled,
  });
};

/**
 * What a thread says about writing in it: whether a moderator locked it, and
 * whether this reader moderates the initiative it is in. Read off the same
 * query as the thread itself, so it costs nothing more.
 */
export const useCommentThreadState = (
  params: CommentThreadParams,
  options?: { enabled?: boolean }
) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    ...commentThreadQueryOptions(communityId, params),
    select: (data: CommentThreadData) => ({
      locked: data.pages[0]?.locked ?? false,
      canModerate: data.pages[0]?.can_moderate ?? false,
    }),
    enabled: options?.enabled,
  });
};

export const useRecentComments = (
  params?: RecentCommentsParams,
  options?: QueryOpts<RecentActivityEntry[]>
) => {
  const communityId = useActiveCommunityId();
  return useQuery<RecentActivityEntry[]>({
    queryKey: getRecentCommentsQueryKey(communityId, params),
    queryFn: () => recentComments(communityId, params),
    staleTime: 30 * 1000,
    ...options,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

const mapPages = (
  data: CommentThreadData,
  update: (comments: CommentRead[], index: number) => CommentRead[]
): CommentThreadData => ({
  ...data,
  pages: data.pages.map((page, index) => ({ ...page, comments: update(page.comments, index) })),
});

/**
 * Put one comment where the thread shows it: in place when it is already
 * loaded; a new conversation at the end of the first page, the newest one; a
 * new reply after the rest of its conversation, on the page that holds it. A
 * reply to a conversation not loaded yet arrives with that conversation's page.
 */
const placeComment = (data: CommentThreadData, comment: CommentRead): CommentThreadData => {
  const holds = (id: number) => (page: CommentListResponse) =>
    page.comments.some((c) => c.id === id);
  if (data.pages.some(holds(comment.id))) {
    return mapPages(data, (comments) => comments.map((c) => (c.id === comment.id ? comment : c)));
  }
  const pageIndex =
    comment.parent_comment_id == null ? 0 : data.pages.findIndex(holds(comment.parent_comment_id));
  if (pageIndex === -1 || pageIndex >= data.pages.length) return data;
  return mapPages(data, (comments, index) =>
    index === pageIndex ? [...comments, comment] : comments
  );
};

/**
 * Take a comment out of the thread, and only it: its replies are other
 * people's words and stay, under the thread's placeholder until the server
 * says what stands in its place — the line saying its author deleted it, or
 * nothing it may say.
 */
const dropComment = (data: CommentThreadData, commentId: number): CommentThreadData =>
  mapPages(data, (comments) => comments.filter((c) => c.id !== commentId));

export const useCommentsCache = (params: CommentThreadParams) => {
  const communityId = useActiveCommunityId();
  const qc = useQueryClient();
  const { queryKey } = commentThreadQueryOptions(communityId, params);

  /** A comment just posted or edited, written straight into the thread. */
  const putComment = (comment: CommentRead) => {
    qc.setQueryData(queryKey, (prev) => prev && placeComment(prev, comment));
  };

  const removeComment = (commentId: number) => {
    qc.setQueryData(queryKey, (prev) => prev && dropComment(prev, commentId));
  };

  return { putComment, removeComment };
};

/**
 * The thread a comment belongs to: the one target it names. A task comment
 * also reports its task's project, so the task is read first, as the backend
 * reads a comment's columns.
 */
const COMMENT_TARGETS = [
  "task_id",
  "wiki_page_id",
  "file_id",
  "project_id",
  "queue_id",
  "counter_group_id",
  "calendar_id",
  "dashboard_id",
  "post_id",
  "catalog_id",
  "wiki_id",
] as const satisfies readonly (keyof CommentThreadParams & keyof CommentRead)[];

const inThread = (comment: CommentRead, params: CommentThreadParams) => {
  // What is said with whoever filed a case is the case's conversation, read
  // on the case, never a comment in the task's thread.
  if (comment.audience === CommentAudience.filer) return false;
  const target = COMMENT_TARGETS.find((key) => comment[key] != null);
  return target !== undefined && params[target] === comment[target];
};

/** The cached threads of `parent`. */
const threadsOf = (communityId: number, parent: { type: string; id: number }) => {
  const param = `${singularOf(parent.type)}_id` as keyof CommentThreadParams;
  return queryClient
    .getQueryCache()
    .findAll({ queryKey: getListCommentsQueryKey(communityId) })
    .filter((query) => {
      const params = query.queryKey[1] as CommentThreadParams | undefined;
      return params?.[param] === parent.id;
    });
};

const readBack = async (
  communityId: number,
  parent: { type: string; id: number },
  commentIds: readonly number[]
) => {
  if (parent.type === "tasks") {
    // A comment on a case task may be part of its conversation with the
    // requester, which the case carries.
    void refreshTaskCase(parent.id, communityId);
  }
  const threads = threadsOf(communityId, parent);
  const refetch = () =>
    Promise.all(
      threads.map((thread) =>
        queryClient.invalidateQueries({ queryKey: thread.queryKey, exact: true })
      )
    );
  // A thread nobody is showing is only marked stale, and reads again when it
  // is next shown.
  if (!threads.some((thread) => thread.getObserversCount() > 0)) {
    await refetch();
    return;
  }
  if (commentIds.length > COMMENT_PAGE_SIZE) {
    await refetch();
    return;
  }
  let reads: (CommentRead | number)[];
  try {
    // In id order, so a reply written in the same batch as the comment it
    // answers is placed after it.
    reads = await Promise.all(
      [...commentIds]
        .sort((a, b) => a - b)
        .map((id) =>
          readComment(communityId, id).catch((error: unknown) => {
            if (getHttpStatus(error) === 404) return id;
            throw error;
          })
        )
    );
  } catch {
    await refetch();
    return;
  }
  for (const thread of threads) {
    const params = thread.queryKey[1] as CommentThreadParams;
    queryClient.setQueryData<CommentThreadData>(
      thread.queryKey,
      (prev) =>
        prev &&
        reads.reduce(
          (data, read) =>
            typeof read === "number"
              ? dropComment(data, read)
              : inThread(read, params)
                ? placeComment(data, read)
                : data,
          prev
        )
    );
  }
};

/** Read-backs run one batch at a time, so an earlier batch's reply can never
 *  land after a later one's. */
let pendingSync: Promise<void> = Promise.resolve();

/**
 * Bring the comments a realtime frame named under `parent` into the threads
 * this tab has open.
 *
 * Each is read back on its own (`GET /comments/{id}`, the same access check
 * as the thread) and placed in the thread it names, so the open pages are
 * never fetched again for one new comment. One that no longer reads back has
 * been deleted, or the reader can no longer see it, and comes out. More than
 * a page's worth at once, or a read that fails for any other reason, reads the
 * threads again instead.
 */
export const syncComments = (
  communityId: number,
  parent: { type: string; id: number },
  commentIds: readonly number[]
) => {
  pendingSync = pendingSync.then(() => readBack(communityId, parent, commentIds));
  return pendingSync;
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateComment = (
  options?: MutationOpts<CommentRead, Parameters<typeof createComment>[1]>
) =>
  useCommunityMutation<CommentRead, Parameters<typeof createComment>[1]>(
    {
      mutationFn: (communityId, data) => createComment(communityId, data),
      invalidate: () => invalidate(q.recentComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );

export const useUpdateComment = (
  options?: MutationOpts<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateComment>[2];
    }
  >
) =>
  useCommunityMutation<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateComment>[2];
    }
  >(
    {
      mutationFn: (communityId, { commentId, data }) => updateComment(communityId, commentId, data),
      invalidate: () => invalidate(q.recentComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );

export const useDeleteComment = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, commentId) => deleteComment(communityId, commentId),
      // The thread reads again: a comment with replies under it comes back as
      // the line saying its author deleted it.
      invalidate: () => invalidate(q.allComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );

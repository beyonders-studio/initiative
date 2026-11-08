import {
  type InfiniteData,
  type Query,
  type QueryClient,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import type {
  NotificationCountResponse,
  NotificationListResponse,
  NotificationRead,
  SubjectReadResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  dismissNotification,
  getListNotificationsQueryKey,
  getUnreadNotificationPlacesQueryKey,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  markNotificationUnread,
  readNotificationSubject,
  useListNotifications,
  useUnreadNotificationPlaces,
} from "@/api/generated/notifications/notifications";
import { describes, invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

// How many rows one request carries. The popover takes every page until the
// cursor runs out, so this is a transport size, not a cap on what it shows.
export const NOTIFICATION_PAGE_SIZE = 50;

// ── Queries ─────────────────────────────────────────────────────────────────

// `refetchInterval: false` turns polling off — what a caller passes once the
// notification push channel is carrying the updates instead.
export const useNotifications = (options?: {
  enabled?: boolean;
  refetchInterval?: number | false;
  unreadOnly?: boolean;
  communityId?: number;
  personalOnly?: boolean;
}) => {
  return useListNotifications(
    {
      limit: NOTIFICATION_PAGE_SIZE,
      unread_only: options?.unreadOnly,
      community_id: options?.communityId,
      personal_only: options?.personalOnly,
    },
    { query: { enabled: options?.enabled, refetchInterval: options?.refetchInterval } }
  );
};

/**
 * The inbox page's list: every notification, read and unread, a page at a time.
 *
 * The popover holds what is still unread; this is the record, so it is not
 * filtered by default and it goes back as far as somebody scrolls.
 */
export const useNotificationHistory = (options?: {
  enabled?: boolean;
  unreadOnly?: boolean;
  communityId?: number;
  personalOnly?: boolean;
  refetchInterval?: number | false;
}) => {
  const params = {
    limit: NOTIFICATION_PAGE_SIZE,
    unread_only: options?.unreadOnly,
    community_id: options?.communityId,
    personal_only: options?.personalOnly,
  };
  return useInfiniteQuery({
    queryKey: [...getListNotificationsQueryKey(params), "history"],
    queryFn: ({ pageParam }) =>
      listNotifications({
        ...params,
        cursor: (pageParam as string | undefined) ?? undefined,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: NotificationListResponse) => last.next_cursor ?? undefined,
    enabled: options?.enabled,
    refetchInterval: options?.refetchInterval,
  });
};

/**
 * Every unread notification — all of them, however many pages that takes.
 *
 * The popover's promise is that opening it shows the whole unread set, which
 * is what makes a count on the bell unnecessary. One page of fifty would
 * quietly break that for exactly the people it matters most to, so this
 * follows the cursor to the end.
 */
export const useAllUnreadNotifications = (options?: {
  enabled?: boolean;
  refetchInterval?: number | false;
}) => {
  const query = useNotificationHistory({
    enabled: options?.enabled,
    unreadOnly: true,
    refetchInterval: options?.refetchInterval,
  });
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;

  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const notifications = useMemo(
    () => query.data?.pages.flatMap((page) => page.notifications) ?? [],
    [query.data]
  );
  return {
    notifications,
    // The server's own total, not the length of what has arrived — the dot has
    // to be right before the last page lands.
    unreadCount: query.data?.pages[0]?.unread_count ?? 0,
    isLoading: query.isLoading,
    isComplete: !query.hasNextPage,
  };
};

/** The popover's query: every unread line, a page at a time. */
const UNREAD_INBOX = { limit: NOTIFICATION_PAGE_SIZE, unread_only: true };
const unreadInboxKey = () => [...getListNotificationsQueryKey(UNREAD_INBOX), "history"];

/**
 * Read the popover's first page again and keep what it already held beneath
 * it, or null when the two do not add up to the server's own total.
 *
 * A line that arrives, or returns to the top, lands on the first page, so the
 * rest of the inbox is what it was. Anything else — a line read or withdrawn
 * further down — leaves a row held here that the server no longer counts, and
 * the totals disagree.
 */
const readInboxHead = async (held: InfiniteData<NotificationListResponse>) => {
  const head = await listNotifications(UNREAD_INBOX);
  const fresh = new Set(head.notifications.map((row) => row.id));
  const older = held.pages
    .flatMap((page) => page.notifications)
    .filter((row) => !fresh.has(row.id));
  if (head.notifications.length + older.length !== head.unread_count) {
    return null;
  }
  return older.length > 0
    ? {
        pages: [head, { notifications: older, unread_count: null, next_cursor: null }],
        pageParams: [undefined, head.next_cursor],
      }
    : { pages: [{ ...head, next_cursor: null }], pageParams: [undefined] };
};

/** One read of the first page at a time, so an older answer never lands last. */
let inboxRead: Promise<unknown> = Promise.resolve();

/**
 * What a notification frame makes stale.
 *
 * Every notification read is asked again, except that a line arriving
 * (`created`) or returning to the top (`updated`) costs the popover one page
 * rather than every page it holds. Any other change, or a popover that has not
 * finished loading, reads it whole.
 */
export const refreshNotifications = (action?: string) => {
  const key = unreadInboxKey();
  const inbox = queryClient.getQueryCache().find({ queryKey: key, exact: true });
  const held = inbox?.state.data as InfiniteData<NotificationListResponse> | undefined;
  if (
    (action !== "created" && action !== "updated") ||
    !inbox ||
    !held ||
    inbox.state.fetchStatus !== "idle" ||
    held.pages.at(-1)?.next_cursor
  ) {
    return invalidate(q.notifications());
  }
  const notifications = describes(q.notifications());
  void queryClient.invalidateQueries({
    predicate: (query) => query !== inbox && notifications(query.queryKey),
  });
  inboxRead = inboxRead
    .then(() => readInboxHead(held))
    .then((spliced) =>
      spliced
        ? queryClient.setQueryData(key, spliced)
        : queryClient.invalidateQueries({ queryKey: key, exact: true })
    )
    .catch(() => queryClient.invalidateQueries({ queryKey: key, exact: true }));
  return inboxRead;
};

/**
 * Where there is unread activity, as a set of places rather than a count.
 *
 * A place is (community, initiative, tool) with every level optional, so a node
 * in the navigation shows a dot when any place names it as an ancestor. A
 * direct message names none of them, which is why "is anything unread at all"
 * is just this list being non-empty.
 */
export const useUnreadPlaces = (options?: {
  enabled?: boolean;
  refetchInterval?: number | false;
}) => {
  return useUnreadNotificationPlaces({
    query: { enabled: options?.enabled, refetchInterval: options?.refetchInterval },
  });
};

const OPENED_KEY = ["notifications", "opened"] as const;

/**
 * Whether a cached query is a visit's read that has already been answered.
 * Asking it again reads nothing and clears what the visit is showing, so an
 * invalidation of everything passes over it. One that failed is not answered
 * and is asked again with the rest.
 */
export const isAnsweredVisitRead = (query: Query) =>
  query.queryKey[0] === OPENED_KEY[0] &&
  query.queryKey[1] === OPENED_KEY[1] &&
  query.state.status === "success";

/**
 * Opening an item reads every unread notification about it, and says what was
 * unread there so the page can show it for this visit.
 *
 * A query rather than a mutation so the page and its comment thread share one
 * read. It never refetches while mounted — a second read would find nothing
 * unread and clear what the visit is showing — and it is dropped on leaving,
 * so the next visit reads again.
 */
export const useReadOnOpen = (kind: string, id: number | undefined) => {
  const communityId = useActiveCommunityId();
  const { data } = useQuery<SubjectReadResponse>({
    queryKey: [...OPENED_KEY, communityId, kind, id],
    queryFn: async () => {
      const read = await readNotificationSubject({
        community_id: communityId,
        subject_type: kind,
        subject_id: id as number,
      });
      void invalidate(q.notifications());
      return read;
    },
    enabled: communityId > 0 && Number.isFinite(id),
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  return useMemo(
    () => ({
      commentIds: new Set(data?.comment_ids),
      since: data?.since ? new Date(data.since) : null,
    }),
    [data]
  );
};

// ── Reading, applied before the server has said so ──────────────────────────

/**
 * Fold a read into the cached inbox.
 *
 * Marking read is a statement about the reader, not a negotiation: the badge
 * and the dot move on the click, and the refetch that follows settles it. What
 * this removes is the wait, which on a notification you are already navigating
 * away from was the whole of what you saw.
 *
 * A failure invalidates, so the server's answer replaces this rather than the
 * optimistic state standing.
 */
/**
 * Fold a read into a list's cached pages, or null when nothing moved. Only the
 * first page carries the inbox's total, so a read on any page comes off it.
 */
const applyReadToPages = (
  pages: NotificationListResponse[],
  matches: (notification: NotificationRead) => boolean,
  readAt: string
): NotificationListResponse[] | null => {
  let cleared = 0;
  const next = pages.map((page) => {
    const before = cleared;
    const notifications = page.notifications.map((notification) => {
      if (notification.read_at || !matches(notification)) {
        return notification;
      }
      cleared += 1;
      return { ...notification, read_at: readAt };
    });
    return cleared === before ? page : { ...page, notifications };
  });
  if (cleared === 0) {
    return null;
  }
  const [first, ...rest] = next;
  const total = first.unread_count;
  return [
    { ...first, unread_count: total === null ? null : Math.max(0, total - cleared) },
    ...rest,
  ];
};

type CachedList =
  | NotificationListResponse
  | { pages: NotificationListResponse[]; pageParams: unknown[] };

const applyRead = (client: QueryClient, matches: (notification: NotificationRead) => boolean) =>
  // Every cached list, not one: the popover reads its unread set a page at a
  // time while the inbox page holds its own filters, so they are separate
  // entries — and one is paginated and one is not. A read has to reach both
  // shapes or the dot moves in one place and not the other.
  client.setQueriesData<CachedList>({ queryKey: getListNotificationsQueryKey() }, (current) => {
    if (!current) {
      return current;
    }
    const readAt = new Date().toISOString();
    if ("pages" in current) {
      const pages = applyReadToPages(current.pages, matches, readAt);
      return pages ? { ...current, pages } : current;
    }
    return applyReadToPages([current], matches, readAt)?.[0] ?? current;
  });

// ── Mutations ───────────────────────────────────────────────────────────────

export const useMarkNotificationRead = (options?: MutationOpts<NotificationRead, number>) => {
  // The client this component reads from, not the module's own: the optimistic
  // write has to land in the cache the badge is rendered off.
  const client = useQueryClient();
  return useApiMutation<NotificationRead, number>(
    {
      mutationFn: (notificationId) => markNotificationRead(notificationId),
      invalidate: () => invalidate(q.notifications()),
    },
    {
      ...options,
      onMutate: (...args) => {
        const [notificationId] = args;
        applyRead(client, (notification) => notification.id === notificationId);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        // The optimistic read gives way to what the server says rather than
        // standing; `invalidate` above only fires on success.
        void client.invalidateQueries({
          queryKey: getListNotificationsQueryKey(),
        });
        options?.onError?.(...args);
      },
    }
  );
};

export const useMarkNotificationUnread = (options?: MutationOpts<NotificationRead, number>) => {
  const client = useQueryClient();
  return useApiMutation<NotificationRead, number>(
    {
      mutationFn: (notificationId) => markNotificationUnread(notificationId),
      invalidate: () => invalidate(q.notifications()),
    },
    {
      ...options,
      onSettled: (...args) => {
        void client.invalidateQueries({
          queryKey: getListNotificationsQueryKey(),
        });
        void client.invalidateQueries({
          queryKey: getUnreadNotificationPlacesQueryKey(),
        });
        options?.onSettled?.(...args);
      },
    }
  );
};

export const useDismissNotification = (options?: MutationOpts<void, number>) => {
  const client = useQueryClient();
  return useApiMutation<void, number>(
    {
      mutationFn: (notificationId) => dismissNotification(notificationId),
      invalidate: () => invalidate(q.notifications()),
    },
    {
      ...options,
      onSettled: (...args) => {
        void client.invalidateQueries({
          queryKey: getListNotificationsQueryKey(),
        });
        void client.invalidateQueries({
          queryKey: getUnreadNotificationPlacesQueryKey(),
        });
        options?.onSettled?.(...args);
      },
    }
  );
};

export const useMarkAllNotificationsRead = (
  options?: MutationOpts<NotificationCountResponse, void>
) => {
  const client = useQueryClient();
  return useApiMutation<NotificationCountResponse, void>(
    {
      mutationFn: () => markAllNotificationsRead(),
      invalidate: () => invalidate(q.notifications()),
    },
    {
      ...options,
      onMutate: (...args) => {
        applyRead(client, () => true);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        void client.invalidateQueries({
          queryKey: getListNotificationsQueryKey(),
        });
        options?.onError?.(...args);
      },
    }
  );
};

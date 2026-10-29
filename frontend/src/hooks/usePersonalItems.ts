/**
 * What the reader keeps about items, one seam for all of it: their opens (the
 * header's tabs), their bookmarks, what they subscribe to and their reminders.
 *
 * Tabs and bookmarks are lists of tools: `/me/personal-items?mark=…` across every
 * community, `/c/{id}/personal-items?mark=bookmark` for one community's sidebar and
 * the bookmarks on its pages (a few dozen rows at most, so one read lights every
 * bookmark on screen). One item's subscription is read on its own,
 * `/c/{id}/personal-items/{kind}/{id}`, since a subscription can be on anything.
 */

import { type UseQueryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";

import {
  type ContentKind,
  ListedMark,
  type PersonalItemRead,
  type PersonalItemState,
  Tool,
  type ViewSource,
} from "@/api/generated/initiativeAPI.schemas";
import {
  bookmarkItem,
  clearTaskReminder,
  clearView,
  getListMyPersonalItemsQueryKey,
  getListPersonalItemsQueryKey,
  getReadPersonalItemQueryKey,
  listMyPersonalItems,
  listPersonalItems,
  readPersonalItem,
  recordView,
  setTaskReminder,
  subscribeItem,
  unbookmarkItem,
  unsubscribeItem,
} from "@/api/generated/personal-items/personal-items";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

type QueryOpts<TData> = Omit<UseQueryOptions<TData>, "queryKey" | "queryFn">;

const TABS = { mark: ListedMark.view };
const BOOKMARKS = { mark: ListedMark.bookmark };

/**
 * The header's tabs: the tools the reader opened, across every community, as
 * many as they keep, newest first, with what draws each one's icon.
 */
export const useRecents = (options?: QueryOpts<PersonalItemRead[]>) => {
  return useQuery<PersonalItemRead[]>({
    queryKey: getListMyPersonalItemsQueryKey(TABS),
    queryFn: () => listMyPersonalItems(TABS),
    staleTime: 30 * 1000,
    ...options,
  });
};

const TAB_KINDS = new Set<string>(Object.values(Tool));

/**
 * Mutation that PUTs ``/personal-items/view/{kind}/{id}`` to record an open: of a
 * tool, which becomes a tab, or of something inside one, which does not. Pages
 * call this in a ``useEffect`` once the entity has loaded and access checks
 * have passed. ``source`` is where the open came from; absent is a direct one.
 *
 * ``communityId`` is the entity's OWN community — pass the ``/c/{communityId}`` route param,
 * NOT the active community. The active community is shared across tabs (localStorage +
 * storage events), so recording with it tags the view under the wrong community
 * when another tab is in a different community; the URL path is per-tab.
 */
export const useRecordRecentView = (
  entityType: ContentKind,
  communityId: number,
  source?: ViewSource
) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entityId: number) =>
      recordView(communityId, entityType, entityId, source ? { source } : undefined),
    onSuccess: (written) => {
      if (!TAB_KINDS.has(written.entity_type)) {
        return;
      }
      // The bar is read across every community the reader is in, so it is
      // read again only for a tab it does not have yet — whose name and icon
      // nothing here knows. Reopening one already there moves it to the front.
      const key = getListMyPersonalItemsQueryKey(TABS);
      const held = client.getQueryData<PersonalItemRead[]>(key);
      const opened = held?.find(
        (item) =>
          item.community_id === communityId &&
          item.entity_type === written.entity_type &&
          item.entity_id === written.entity_id
      );
      if (!held || !opened) {
        void invalidate(q.personalItems());
        return;
      }
      // Ordered by when each was viewed, as the server orders them, rather
      // than by which answer arrived last.
      client.setQueryData(
        key,
        held
          .map((item) => (item === opened ? { ...opened, viewed_at: written.viewed_at } : item))
          .sort((a, b) => Date.parse(b.viewed_at ?? "") - Date.parse(a.viewed_at ?? ""))
      );
    },
  });
};

interface OpenOptions {
  /** Where an open inside a page came from (an image in the lightbox, an item
   *  in its dialog). The history entry there is the page's, not the open's. */
  source?: ViewSource;
  /** Record again each time this changes: a wiki is opened by each page. */
  each?: number;
}

/**
 * Records that the reader opened this, once it has loaded (``id`` is set only
 * after the read passed its access checks), in the community the route
 * addresses, with where the open came from: the history entry's
 * ``viewSource``, which a search sets when it navigates. A search that brings
 * the reader back to what is already open records it again.
 */
export const useRecordOpen = (
  kind: ContentKind,
  id: number | undefined,
  { source, each }: OpenOptions = {}
) => {
  const { communityId } = useParams({ strict: false }) as { communityId?: string };
  // Read once a navigation has settled, when the page and its history entry
  // agree: while one is under way they move at different times.
  const settled = useRouterState({ select: (state) => state.status === "idle" });
  const arrivedFrom = useRouterState({
    select: (state) => state.resolvedLocation?.state.viewSource,
  });
  const entry = useRouterState({ select: (state) => state.resolvedLocation?.state.__TSR_key });
  const path = useRouterState({ select: (state) => state.resolvedLocation?.pathname });
  const { mutate } = useRecordRecentView(kind, Number(communityId), source ?? arrivedFrom);
  const recorded = useRef<{ id?: number; each?: number; entry?: string; path?: string }>({});
  useEffect(() => {
    // Closed: opening it again is another open.
    if (!id) {
      recorded.current = {};
      return;
    }
    if (!settled) return;
    const last = recorded.current;
    // A search back to the address of what is open. At another address the
    // page is still loading what it names, and `id` is the one being left.
    const searchedAgain =
      !source && arrivedFrom !== undefined && entry !== last.entry && path === last.path;
    // Kept current whether or not this is an open: an address the page
    // corrects is still the address of what is open.
    recorded.current = { id, each, entry, path };
    if (id !== last.id || each !== last.each || searchedAgain) mutate(id);
  }, [id, each, entry, path, arrivedFrom, settled, source, mutate]);
};

/**
 * Mutation that DELETEs ``/personal-items/view/{kind}/{id}`` (the X on a tab).
 *
 * Community-ADDRESSED: a tab can belong to any of the user's communities regardless of
 * the current context, and per-community entity ids are only unique within their
 * community, so the tab's ``community_id`` travels with the call.
 */
export const useClearRecentView = () => {
  return useMutation({
    mutationFn: async ({
      entityType,
      entityId,
      communityId,
    }: {
      entityType: Tool;
      entityId: number;
      communityId: number;
    }) => {
      await clearView(communityId, entityType, entityId);
    },
    onSuccess: () => {
      void invalidate(q.personalItems());
    },
  });
};

export interface ClearRecentTarget {
  entityType: Tool;
  entityId: number;
  communityId: number;
}

/**
 * Mutation that closes several tabs at once (the "close others" / "close all"
 * context-menu actions). Issues one community-addressed delete per tab in
 * parallel — each tab can live in a different community — then invalidates the
 * recents query a single time.
 *
 * Uses ``onSettled`` (not ``onSuccess``) so the cache is refreshed even on a
 * partial failure: ``Promise.all`` rejects on the first failed DELETE, but
 * earlier deletes may already have succeeded server-side, so we must resync
 * regardless of outcome rather than leave stale tabs until the query expires.
 */
export const useClearRecentViews = () => {
  return useMutation({
    mutationFn: async (targets: ClearRecentTarget[]) => {
      await Promise.all(
        targets.map(({ entityType, entityId, communityId }) =>
          clearView(communityId, entityType, entityId)
        )
      );
    },
    onSettled: () => {
      void invalidate(q.personalItems());
    },
  });
};

/** The reader's bookmarks in one community (the active one unless named), newest first. */
export const useCommunityBookmarks = (
  communityId?: number | null,
  options?: QueryOpts<PersonalItemRead[]>
) => {
  const active = useActiveCommunityId();
  const id = communityId ?? active;
  return useQuery<PersonalItemRead[]>({
    queryKey: getListPersonalItemsQueryKey(id, BOOKMARKS),
    queryFn: () => listPersonalItems(id, BOOKMARKS),
    staleTime: 30 * 1000,
    ...options,
    enabled: Boolean(id) && (options?.enabled ?? true),
  });
};

/** The reader's bookmarks in every community they are in, newest first. */
export const useMyBookmarks = (options?: QueryOpts<PersonalItemRead[]>) =>
  useQuery<PersonalItemRead[]>({
    queryKey: getListMyPersonalItemsQueryKey(BOOKMARKS),
    queryFn: () => listMyPersonalItems(BOOKMARKS),
    staleTime: 30 * 1000,
    ...options,
  });

/** Whether the reader bookmarked this tool, in its community (the active one
 *  unless named). */
export const useIsBookmarked = (tool: Tool, entityId: number, communityId?: number): boolean => {
  const { data } = useCommunityBookmarks(communityId);
  return useMemo(
    () => Boolean(data?.some((item) => item.entity_type === tool && item.entity_id === entityId)),
    [data, tool, entityId]
  );
};

export interface ToggleBookmarkArgs {
  tool: Tool;
  entityId: number;
  /** Star it (true) or take the bookmark off (false). */
  next: boolean;
  /** The tool's own community; the active one when left out. */
  communityId?: number;
  /** What a list shows for it until the server's answer arrives. */
  name?: string;
  initiativeId?: number | null;
}

const sameItem = (item: PersonalItemRead, tool: Tool, entityId: number, communityId: number) =>
  item.entity_type === tool && item.entity_id === entityId && item.community_id === communityId;

/**
 * Star or unbookmark a tool. The bookmark changes at once — the community's list and
 * every community's are rewritten in the cache, and put back if the write
 * fails — and both are read again once it lands.
 */
export const useToggleBookmark = () => {
  const active = useActiveCommunityId();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({ tool, entityId, next, communityId }: ToggleBookmarkArgs) => {
      const id = communityId ?? active;
      if (next) await bookmarkItem(id, tool, entityId);
      else await unbookmarkItem(id, tool, entityId);
    },
    onMutate: async ({ tool, entityId, next, communityId, name, initiativeId }) => {
      const id = communityId ?? active;
      const keys = [
        getListPersonalItemsQueryKey(id, BOOKMARKS),
        getListMyPersonalItemsQueryKey(BOOKMARKS),
      ];
      await Promise.all(keys.map((queryKey) => qc.cancelQueries({ queryKey })));
      const before = keys.map((queryKey) => [queryKey, qc.getQueryData(queryKey)] as const);
      const placeholder: PersonalItemRead = {
        entity_type: tool,
        entity_id: entityId,
        community_id: id,
        initiative_id: initiativeId ?? null,
        name: name ?? "",
        viewed_at: null,
        bookmarked_at: new Date().toISOString(),
        icon: null,
        file_type: null,
        mime_type: null,
        original_filename: null,
      };
      for (const queryKey of keys) {
        qc.setQueryData<PersonalItemRead[]>(queryKey, (prev) => {
          if (!prev) return prev;
          const rest = prev.filter((item) => !sameItem(item, tool, entityId, id));
          return next ? [placeholder, ...rest] : rest;
        });
      }
      return { before };
    },
    onError: (_error, _args, context) => {
      for (const [queryKey, data] of context?.before ?? []) qc.setQueryData(queryKey, data);
    },
    onSettled: () => {
      void invalidate(q.personalItems());
    },
  });
};

/** What the reader keeps about one item, in its community (the active one
 *  unless named): whether they are subscribed to it. */
export const useItemState = (kind: ContentKind, entityId: number, communityId?: number) => {
  const active = useActiveCommunityId();
  const id = communityId ?? active;
  return useQuery<PersonalItemState>({
    queryKey: getReadPersonalItemQueryKey(id, kind, entityId),
    queryFn: () => readPersonalItem(id, kind, entityId),
    staleTime: 30 * 1000,
    enabled: Boolean(id) && entityId > 0,
  });
};

export interface ToggleSubscriptionArgs {
  kind: ContentKind;
  entityId: number;
  /** Subscribe (true) or unsubscribe (false). */
  next: boolean;
  /** The item's own community; the active one when left out. */
  communityId?: number;
}

/**
 * Subscribe to or unsubscribe from anything. The toggle changes at once, is put back if
 * the write fails, and the item is read again once it lands.
 */
export const useToggleSubscription = () => {
  const active = useActiveCommunityId();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({ kind, entityId, next, communityId }: ToggleSubscriptionArgs) => {
      const id = communityId ?? active;
      if (next) await subscribeItem(id, kind, entityId);
      else await unsubscribeItem(id, kind, entityId);
    },
    onMutate: async ({ kind, entityId, next, communityId }) => {
      const queryKey = getReadPersonalItemQueryKey(communityId ?? active, kind, entityId);
      await qc.cancelQueries({ queryKey });
      const before = qc.getQueryData<PersonalItemState>(queryKey);
      if (before) {
        qc.setQueryData<PersonalItemState>(queryKey, {
          ...before,
          subscribed: next,
          subscribed_at: next ? new Date().toISOString() : null,
        });
      }
      return { queryKey, before };
    },
    onError: (_error, _args, context) => {
      if (context?.before) qc.setQueryData(context.queryKey, context.before);
    },
    onSettled: () => {
      // Subscribing to a tool subscribes to what is inside it, so every item's
      // bell is read again; the feed's order follows it too.
      void invalidate(q.personalItems(), q.activity());
    },
  });
};

/** Whether the reader is subscribed to this, and the toggle: what a subscribe
 *  control needs, wherever it sits. `ready` once the state is read and no write is
 *  under way, so the last click is the one that holds. */
export const useSubscription = (kind: ContentKind, entityId: number, communityId?: number) => {
  const { data } = useItemState(kind, entityId, communityId);
  const toggle = useToggleSubscription();
  const subscribed = Boolean(data?.subscribed);
  return {
    subscribed,
    ready: Boolean(data) && !toggle.isPending,
    toggle: () => toggle.mutate({ kind, entityId, next: !subscribed, communityId }),
  };
};

/**
 * The reader's own reminder of a task, and setting or clearing it: `remindAt`
 * an instant, or null to take it off. The field moves at once and is put back
 * if the write fails.
 */
export const useTaskReminder = (taskId: number, communityId?: number) => {
  const active = useActiveCommunityId();
  const id = communityId ?? active;
  const qc = useQueryClient();
  const { data } = useItemState("task", taskId, communityId);
  const queryKey = getReadPersonalItemQueryKey(id, "task", taskId);
  const mutation = useMutation({
    mutationFn: async (remindAt: string | null) => {
      if (remindAt) return setTaskReminder(id, taskId, { remind_at: remindAt });
      await clearTaskReminder(id, taskId);
      return null;
    },
    onMutate: async (remindAt) => {
      await qc.cancelQueries({ queryKey });
      const before = qc.getQueryData<PersonalItemState>(queryKey);
      if (before) {
        qc.setQueryData<PersonalItemState>(queryKey, {
          ...before,
          remind_at: remindAt,
          reminded_at: null,
        });
      }
      return { before };
    },
    onError: (_error, _remindAt, context) => {
      if (context?.before) qc.setQueryData(queryKey, context.before);
    },
    onSuccess: (state) => {
      if (state) qc.setQueryData(queryKey, state);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey });
    },
  });
  return {
    remindAt: data?.remind_at ?? null,
    remindedAt: data?.reminded_at ?? null,
    ready: Boolean(data),
    pending: mutation.isPending,
    set: (remindAt: string | null) => mutation.mutate(remindAt),
  };
};

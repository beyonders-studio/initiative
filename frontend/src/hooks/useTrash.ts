import { keepPreviousData } from "@tanstack/react-query";

import type {
  EntityType,
  ListCommunityTrashParams,
  ListMyTrashParams,
  RestoreResponse,
  TrashListResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListCommunityTrashQueryKey,
  getListMyTrashQueryKey,
  purgeCalendar,
  purgeCalendarEvent,
  purgeCollection,
  purgeComment,
  purgeContact,
  purgeCounter,
  purgeCounterGroup,
  purgeDashboard,
  purgeFile,
  purgeInitiative,
  purgePost,
  purgeProject,
  purgeTag,
  purgeTask,
  purgeWiki,
  purgeWikiPage,
  restoreCalendar,
  restoreCalendarEvent,
  restoreCollection,
  restoreComment,
  restoreContact,
  restoreCounter,
  restoreCounterGroup,
  restoreDashboard,
  restoreFile,
  restoreInitiative,
  restorePost,
  restoreProject,
  restoreTag,
  restoreTask,
  restoreWiki,
  restoreWikiPage,
  useListCommunityTrash,
  useListMyTrash,
} from "@/api/generated/trash/trash";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * One page of the current user's own trashed items across every community they
 * belong to, newest deletion first. Powers the personal trash view on the user
 * settings page — user-scoped, no community context. Restore/purge are addressed
 * per item via its `community_id`.
 */
export const useMyTrashList = (params: ListMyTrashParams, options?: QueryOpts<TrashListResponse>) =>
  useListMyTrash(params, { query: { placeholderData: keepPreviousData, ...options } });

/**
 * One page of the active community's trash, newest deletion first — the
 * community-admin settings view. Regular members never call this (the backend
 * 403s); they use {@link useMyTrashList} instead.
 */
export const useCommunityTrashList = (
  params: ListCommunityTrashParams,
  options?: QueryOpts<TrashListResponse>
) => {
  const communityId = useActiveCommunityId();
  return useListCommunityTrash(communityId, params, {
    query: { placeholderData: keepPreviousData, ...options },
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Maps entity_type -> what a restore makes stale, so the row reappears in
// active lists across the app without an explicit reload. Child entities (task,
// comment, counter) name their parent tool's lists.
const RESTORED: Record<EntityType, () => Spec> = {
  project: q.allProjects,
  wiki: q.allWikis,
  wiki_page: q.allWikis,
  task: q.allTasks,
  file: q.allFiles,
  comment: q.allComments,
  initiative: q.allInitiatives,
  tag: q.allTags,
  calendar: q.allCalendars,
  calendar_event: q.allCalendarEvents,
  counter_group: q.allCounterGroups,
  counter: q.allCounterGroups,
  post: q.allPosts,
  collection: q.allCollections,
  dashboard: q.allDashboards,
  contact: q.allContacts,
};

/** Each kind's `POST /{kind}/{id}/restore`. */
const RESTORE: Record<EntityType, (communityId: number, id: number) => Promise<RestoreResponse>> = {
  project: restoreProject,
  file: restoreFile,
  counter_group: restoreCounterGroup,
  calendar: restoreCalendar,
  dashboard: restoreDashboard,
  post: restorePost,
  wiki: restoreWiki,
  contact: restoreContact,
  task: restoreTask,
  calendar_event: restoreCalendarEvent,
  counter: restoreCounter,
  wiki_page: restoreWikiPage,
  collection: restoreCollection,
  comment: restoreComment,
  initiative: restoreInitiative,
  tag: restoreTag,
};

/** Each kind's `POST /{kind}/{id}/purge`. */
const PURGE: Record<EntityType, (communityId: number, id: number) => Promise<void>> = {
  project: purgeProject,
  file: purgeFile,
  counter_group: purgeCounterGroup,
  calendar: purgeCalendar,
  dashboard: purgeDashboard,
  post: purgePost,
  wiki: purgeWiki,
  contact: purgeContact,
  task: purgeTask,
  calendar_event: purgeCalendarEvent,
  counter: purgeCounter,
  wiki_page: purgeWikiPage,
  collection: purgeCollection,
  comment: purgeComment,
  initiative: purgeInitiative,
  tag: purgeTag,
};

export type RestoreTrashVars = {
  // The item's community — restore is community-scoped, and the cross-community /me view
  // surfaces items from several communities, so it travels with each row.
  communityId: number;
  entityType: EntityType;
  entityId: number;
};

// Both trash views (personal /me and the item's community), every page of each
// (the keys without params are prefixes), so the row disappears from both.
const invalidateTrash = (communityId: number) => {
  void queryClient.invalidateQueries({ queryKey: getListMyTrashQueryKey() });
  void queryClient.invalidateQueries({ queryKey: getListCommunityTrashQueryKey(communityId) });
};

export const useRestoreTrashEntity = (options?: MutationOpts<RestoreResponse, RestoreTrashVars>) =>
  useApiMutation<RestoreResponse, RestoreTrashVars>(
    {
      mutationFn: ({ communityId, entityType, entityId }) =>
        RESTORE[entityType](communityId, entityId),
      invalidate: (_restored, { communityId, entityType }) => {
        invalidateTrash(communityId);
        const restored = RESTORED[entityType];
        if (restored) void invalidate(restored());
      },
      errorKey: "trash:restoreError",
    },
    options
  );

export type PurgeTrashVars = {
  // Purge is community-scoped + admin-only; only reachable from the community view,
  // but it still travels with the row for consistency with restore.
  communityId: number;
  entityType: EntityType;
  entityId: number;
};

export const usePurgeTrashEntity = (options?: MutationOpts<void, PurgeTrashVars>) =>
  useApiMutation<void, PurgeTrashVars>(
    {
      mutationFn: async ({ communityId, entityType, entityId }) => {
        await PURGE[entityType](communityId, entityId);
      },
      invalidate: (_none, { communityId }) => invalidateTrash(communityId),
      errorKey: "trash:purgeError",
    },
    options
  );

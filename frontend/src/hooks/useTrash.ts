import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
  listCommunityTrash,
  listMyTrash,
  purgeTrashEntity,
  restoreTrashEntity,
} from "@/api/generated/trash/trash";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
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
  useQuery<TrashListResponse>({
    queryKey: getListMyTrashQueryKey(params),
    queryFn: () => listMyTrash(params),
    placeholderData: keepPreviousData,
    ...options,
  });

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
  return useQuery<TrashListResponse>({
    queryKey: getListCommunityTrashQueryKey(communityId, params),
    queryFn: () => listCommunityTrash(communityId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Maps entity_type -> what a restore makes stale, so the row reappears in
// active lists across the app without an explicit reload. Child entities (task,
// comment, queue_item, counter) name their parent tool's lists.
const RESTORED: Record<EntityType, () => Spec> = {
  project: q.allProjects,
  wiki: q.allWikis,
  wiki_page: q.allWikis,
  task: q.allTasks,
  file: q.allFiles,
  comment: q.allComments,
  initiative: q.allInitiatives,
  tag: q.allTags,
  queue: q.allQueues,
  queue_item: q.allQueues,
  calendar: q.allCalendars,
  calendar_event: q.allCalendarEvents,
  counter_group: q.allCounterGroups,
  counter: q.allCounterGroups,
  post: q.allPosts,
  library: q.allLibraries,
  library_item: q.allLibraries,
  dashboard: q.allDashboards,
};

export type RestoreTrashVars = {
  // The item's community — restore is community-scoped, and the cross-community /me view
  // surfaces items from several communities, so it travels with each row.
  communityId: number;
  entityType: EntityType;
  entityId: number;
};

export const useRestoreTrashEntity = (
  options?: MutationOpts<RestoreResponse, RestoreTrashVars>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();

  return useMutation({
    ...rest,
    mutationFn: async ({
      communityId,
      entityType,
      entityId,
    }: RestoreTrashVars): Promise<RestoreResponse> =>
      restoreTrashEntity(communityId, entityType, entityId),
    onSuccess: (...args) => {
      const [, variables] = args;
      // Invalidate both trash views (personal /me and the item's community), every
      // page of each (the keys without params are prefixes), so the restored
      // row disappears from both.
      void queryClient.invalidateQueries({ queryKey: getListMyTrashQueryKey() });
      void queryClient.invalidateQueries({
        queryKey: getListCommunityTrashQueryKey(variables.communityId),
      });
      const restored = RESTORED[variables.entityType];
      if (restored) void invalidate(restored());
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export type PurgeTrashVars = {
  // Purge is community-scoped + admin-only; only reachable from the community view,
  // but it still travels with the row for consistency with restore.
  communityId: number;
  entityType: EntityType;
  entityId: number;
};

export const usePurgeTrashEntity = (options?: MutationOpts<void, PurgeTrashVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();

  return useMutation({
    ...rest,
    mutationFn: async ({ communityId, entityType, entityId }: PurgeTrashVars) => {
      await purgeTrashEntity(communityId, entityType, entityId);
    },
    onSuccess: (...args) => {
      const [, variables] = args;
      void queryClient.invalidateQueries({ queryKey: getListMyTrashQueryKey() });
      void queryClient.invalidateQueries({
        queryKey: getListCommunityTrashQueryKey(variables.communityId),
      });
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

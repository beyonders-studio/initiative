import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  extendCommunityGuest,
  makeCommunityGuestAMember,
  setMemberApiAccess,
  setMemberDisplayName,
  setOwnDisplayName,
  updateCommunityMembership,
} from "@/api/generated/communities/communities";
import type {
  AccountDeletionRequest,
  AccountDeletionResponse,
  CommunityRole,
  ExportUsersCsvParams,
  ListUsersParams,
  Tool,
  UserCommunityMemberListResponse,
  UserRead,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getGetInitiativeQueryOptions,
  getSearchInitiativeMembersQueryOptions,
  useSearchInitiativeMembers,
} from "@/api/generated/initiatives/initiatives";
import {
  deleteOwnAccount,
  exportUsersCsv,
  getListDecorationPacksQueryKey,
  getListMyDecorationsQueryKey,
  getListUsersQueryKey,
  getSearchUsersQueryOptions,
  installDecorationPack,
  liftBan,
  liftMemberTimeout,
  removeDecorationPack,
  timeOutMember,
  updateMe,
  useListBans,
  useListDecorationPacks,
  useListMyDecorations,
  useListUsers,
  useReadUserCommunities,
  useReadUserProfile,
  useSearchUsers,
} from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useApiMutation, useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import { useInitiative } from "@/hooks/useInitiatives";
import { downloadBlob } from "@/lib/csv";
import { toMember } from "@/lib/userDisplay";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";
import type { SearchMembers } from "@/ui/member-picker";

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * One page of the active community's roster, searched and ordered on the server —
 * the members table in community settings. A picker wants {@link useUserSearch}
 * instead: the same people, as the slimmer {@link UserSummary}.
 */
export const useUsers = (
  params: ListUsersParams,
  options?: QueryOpts<UserCommunityMemberListResponse>
) => {
  const communityId = useActiveCommunityId();
  return useListUsers(communityId, params, {
    // Keep the page on screen while the next one (or the next search) loads.
    query: { placeholderData: keepPreviousData, ...options },
  });
};

/** Default page size for slim member typeaheads — mirrors the CommandCenter
 *  task search (a bounded dropdown-sized window, not the whole roster). */
export const USER_SEARCH_PAGE_SIZE = 25;

/** Server-side ceiling on one request's `userIds` list — mirrors
 *  `MAX_ID_FILTER_VALUES` in `backend/app/db/query.py`. */
export const USER_ID_LOOKUP_MAX = 100;

export interface UserSearchOptions {
  /** Matches a member's name — by what it contains, and by how close it is, so
   *  a name typed nearly right still finds the person. */
  search?: string;
  /** Which page of the match to read. Defaults to the first, which is all a
   *  typeahead ever wants; the search page reads further. */
  page?: number;
  /** Resolve these specific members instead of browsing the roster — how a
   *  picker turns stored ids back into names/avatars. Narrows the same scoped
   *  set, so an id outside it simply doesn't come back. */
  userIds?: number[];
  /** Bounded page size (server caps at 100). */
  pageSize?: number;
  /** Only the people who can open this row: who may be named on what it
   *  holds (assignees, attendees, person properties). */
  canOpen?: { tool: Tool; id: number | null | undefined };
  /** Gate the request — pass the picker's `open` state so we don't fetch until
   *  the dropdown is shown. */
  enabled?: boolean;
  /** Read a specific community instead of the active one (cross-community surfaces). */
  communityIdOverride?: number;
  /** List the reader first, ahead of whatever order the rest takes. */
  selfFirst?: boolean;
}

/** Shared query params for the three slim member-search endpoints. */
const memberSearchParams = (search: string | undefined, userIds: number[] | undefined) => ({
  search: search?.trim() || undefined,
  user_id: userIds?.length ? userIds.slice(0, USER_ID_LOOKUP_MAX) : undefined,
});

/**
 * One person's profile, by their handle as it appears in a URL
 * (``jordan1234`` — see ``getUrlHandle``).
 *
 * Public and community-independent: the same page whoever opens it, so there
 * is no community in the call.
 */
/**
 * The listed communities one person belongs to.
 *
 * Its own read rather than part of the profile: the profile is the public
 * projection of the account row, and this is about communities. It also changes far
 * more slowly than a status or a presence dot, so it is held longer.
 */
export const useUserCommunities = (handle: string | null | undefined) =>
  useReadUserCommunities(handle as string, {
    query: { enabled: Boolean(handle), staleTime: 5 * 60_000 },
  });

export const useUserProfile = (handle: string | null | undefined) =>
  useReadUserProfile(handle as string, {
    query: {
      enabled: Boolean(handle),
      // A profile changes without the reader doing anything — the subject
      // signs off, edits their status, changes what they are wearing — and
      // this page is outside the community tree, so no realtime socket is
      // going to tell it. Nor does the app refetch on focus. So it asks again
      // on a timer, which pauses while the tab is in the background.
      staleTime: 30_000,
      refetchInterval: 60_000,
    },
  });

/**
 * The decoration store: every pack this build ships, and which you have.
 *
 * The catalog is fixed per build and the answer changes only when you take or
 * give back a pack, so it is held until a mutation says otherwise.
 */
export const useDecorationPacks = () =>
  useListDecorationPacks({
    query: { staleTime: 5 * 60_000 },
  });

/** Taking a pack, and giving one back. Both change what the pickers may offer
 *  and what the profile is wearing, so both refresh all three. */
const useDecorationPackMutation = (
  run: (packId: string) => Promise<unknown>,
  options?: MutationOpts<unknown, string>
) => {
  const queryClient = useQueryClient();
  return useApiMutation<unknown, string>(
    {
      mutationFn: run,
      invalidate: () => {
        void queryClient.invalidateQueries({
          queryKey: getListDecorationPacksQueryKey(),
        });
        void queryClient.invalidateQueries({
          queryKey: getListMyDecorationsQueryKey(),
        });
        // Giving a pack back can take pieces off the profile server-side, so
        // the account the form reads from has changed too.
        void invalidate(q.currentUser());
      },
      errorKey: "profiles:store.failed",
    },
    options
  );
};

export const useInstallDecorationPack = (options?: MutationOpts<unknown, string>) =>
  useDecorationPackMutation((packId) => installDecorationPack(packId), options);

export const useRemoveDecorationPack = (options?: MutationOpts<unknown, string>) =>
  useDecorationPackMutation((packId) => removeDecorationPack(packId), options);

/**
 * What the signed-in account may dress its profile in — what ships with the
 * app plus whatever it has acquired. Drives the pickers on Settings > Profile;
 * a library changes only when a pack is installed, so it is held a good while.
 */
export const useMyDecorations = (options?: { enabled?: boolean }) =>
  useListMyDecorations({
    query: { staleTime: 5 * 60_000, enabled: options?.enabled ?? true },
  });

/**
 * Slim, server-side member typeahead for the active community. Returns
 * {@link UserSummary} rows (id, name, avatar, status, community role) for a bounded
 * page, so a picker never loads the whole roster to filter it client-side.
 * Debounce the `search` value at the call site.
 */
export const useUserSearch = ({
  search,
  page,
  userIds,
  pageSize = USER_SEARCH_PAGE_SIZE,
  enabled = true,
  communityIdOverride,
  canOpen,
  selfFirst,
}: UserSearchOptions = {}) => {
  const activeCommunityId = useActiveCommunityId();
  const communityId = communityIdOverride ?? activeCommunityId;
  return useSearchUsers(
    communityId,
    {
      ...memberSearchParams(search, userIds),
      page_size: pageSize,
      ...(page != null ? { page } : {}),
      ...(canOpen ? { tool: canOpen.tool, resource_id: canOpen.id } : {}),
      ...(selfFirst ? { self_first: true } : {}),
    },
    {
      query: {
        enabled: enabled && communityId != null && (!canOpen || canOpen.id != null),
        staleTime: 30_000,
        // Keep the prior page visible while the next keystroke's request is in
        // flight so the dropdown doesn't flash empty on every character.
        placeholderData: keepPreviousData,
      },
    }
  );
};

/**
 * Slim, server-side typeahead over one initiative's members — same shape as
 * {@link useUserSearch} but scoped to `initiativeId` (assignee/linked-member
 * pickers that must not offer users outside the initiative). Asked only where
 * the reader may read the roster, which a guest given items there may not.
 */
export const useInitiativeMemberSearch = (
  initiativeId: number | null | undefined,
  {
    search,
    userIds,
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
    communityIdOverride,
  }: UserSearchOptions = {}
) => {
  const activeCommunityId = useActiveCommunityId();
  const communityId = communityIdOverride ?? activeCommunityId;
  const { data: initiative } = useInitiative(initiativeId ?? null, {
    enabled: communityIdOverride == null,
  });
  // Another community's initiative is not in this one's cache to ask.
  const readsRoster = communityIdOverride != null || Boolean(initiative?.can.roster);
  return useSearchInitiativeMembers(
    communityId,
    initiativeId as number,
    {
      ...memberSearchParams(search, userIds),
      page_size: pageSize,
    },
    {
      query: {
        enabled: enabled && readsRoster && communityId != null && initiativeId != null,
        staleTime: 30_000,
        placeholderData: keepPreviousData,
      },
    }
  );
};

/**
 * Which roster a member picker searches.
 * - `community`: every community member.
 * - `initiative`: one initiative's members (mentions, linked members).
 * - `canOpen`: the people who can open one row, who are the ones that may be
 *   named on what it holds (task assignees, event attendees, person
 *   properties).
 */
export type MemberSearchScope =
  | { type: "community"; communityIdOverride?: number }
  | { type: "initiative"; initiativeId: number | null | undefined }
  | { type: "canOpen"; tool: Tool; id: number | null | undefined; communityIdOverride?: number };

/**
 * One entry point for the member typeaheads, selected by `scope`. Both
 * underlying queries are declared (rules of hooks) but only the scope-matching
 * one is enabled, so exactly one request fires.
 */
export const useMemberSearch = (
  scope: MemberSearchScope,
  {
    search,
    userIds,
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
  }: Omit<UserSearchOptions, "communityIdOverride" | "canOpen"> = {}
) => {
  const communityQuery = useUserSearch({
    search,
    userIds,
    pageSize,
    enabled: enabled && scope.type !== "initiative",
    communityIdOverride: scope.type === "initiative" ? undefined : scope.communityIdOverride,
    canOpen: scope.type === "canOpen" ? { tool: scope.tool, id: scope.id } : undefined,
  });
  const initiativeQuery = useInitiativeMemberSearch(
    scope.type === "initiative" ? scope.initiativeId : undefined,
    { search, userIds, pageSize, enabled: enabled && scope.type === "initiative" }
  );

  return scope.type === "initiative" ? initiativeQuery : communityQuery;
};

/**
 * {@link useMemberSearch} as a function a picker calls when it searches, for
 * the active community: the same requests, through the same cache.
 */
export const useSearchMembers = (): SearchMembers => {
  const queryClient = useQueryClient();
  const communityId = useActiveCommunityId();
  return useCallback<SearchMembers>(
    async (scope, query) => {
      const ids = "ids" in query ? query.ids : undefined;
      const params = {
        ...memberSearchParams("search" in query ? query.search : undefined, ids),
        page_size: ids ? USER_ID_LOOKUP_MAX : USER_SEARCH_PAGE_SIZE,
      };
      const options = { query: { staleTime: 30_000 } };
      if (scope.type === "initiative") {
        const { initiativeId } = scope;
        if (initiativeId == null) return [];
        // Asked only where the reader may read the roster, which a guest
        // given items there may not.
        const initiative = await queryClient.ensureQueryData(
          getGetInitiativeQueryOptions(communityId, initiativeId)
        );
        if (!initiative.can.roster) return [];
        const page = await queryClient.fetchQuery(
          getSearchInitiativeMembersQueryOptions(communityId, initiativeId, params, options)
        );
        return page.items.map(toMember);
      }
      if (scope.type === "canOpen" && scope.id == null) return [];
      const page = await queryClient.fetchQuery(
        getSearchUsersQueryOptions(
          communityId,
          scope.type === "canOpen"
            ? { ...params, tool: scope.tool, resource_id: scope.id }
            : params,
          options
        )
      );
      return page.items.map(toMember);
    },
    [queryClient, communityId]
  );
};

export type { UserSummary };

// ── Mutations ───────────────────────────────────────────────────────────────

type UpdateCurrentUserVars = Parameters<typeof updateMe>[0];

export const useUpdateCurrentUser = (
  options?: MutationOpts<UserRead, UpdateCurrentUserVars>,
  /** What a failure says. Omit where the caller reports it itself. */
  errorKey?: string
) =>
  useApiMutation<UserRead, UpdateCurrentUserVars>(
    {
      mutationFn: (data) => updateMe(data),
      invalidate: () => invalidate(q.currentUser()),
      errorKey,
    },
    options
  );

export const useDeleteOwnAccount = (
  options?: MutationOpts<AccountDeletionResponse, AccountDeletionRequest>
) =>
  useApiMutation<AccountDeletionResponse, AccountDeletionRequest>(
    {
      mutationFn: (data) => deleteOwnAccount(data),
      errorKey: "settings:deleteAccount.deleteError",
    },
    options
  );

type UpdateCommunityMembershipVars = { communityId: number; userId: number; role: CommunityRole };

export const useUpdateCommunityMembership = (
  options?: MutationOpts<void, UpdateCommunityMembershipVars>
) =>
  useApiMutation<void, UpdateCommunityMembershipVars>(
    {
      mutationFn: (data) =>
        updateCommunityMembership(data.communityId, data.userId, {
          role: data.role,
        } as Parameters<typeof updateCommunityMembership>[2]),
      invalidate: () => invalidate(q.communityMembers()),
      errorKey: "communities:users.failedToUpdateRole",
    },
    options
  );

type SetMemberApiAccessVars = { communityId: number; userId: number; allowed: boolean };

/**
 * Whether one member's personal API keys reach a community. The seat's.
 *
 * The roster pages already loaded take the new answer as soon as it is saved,
 * so the switch does not show the old one while they refetch.
 */
export const useSetMemberApiAccess = (options?: MutationOpts<void, SetMemberApiAccessVars>) => {
  const queryClient = useQueryClient();
  return useApiMutation<void, SetMemberApiAccessVars>(
    {
      mutationFn: ({ communityId, userId, allowed }) =>
        setMemberApiAccess(communityId, userId, { api_keys_allowed: allowed }),
      invalidate: (_data, { communityId, userId, allowed }) => {
        queryClient.setQueriesData<UserCommunityMemberListResponse>(
          { queryKey: getListUsersQueryKey(communityId) },
          (page) =>
            page && {
              ...page,
              items: page.items.map((member) =>
                member.id === userId ? { ...member, api_keys_allowed: allowed } : member
              ),
            }
        );
        return invalidate(q.communityMembers());
      },
      errorKey: "communities:users.apiAccessError",
    },
    options
  );
};

type GuestVars = { communityId: number; userId: number };

/** End a guest's time `days` from now, as far as the community's and the server's limits allow. */
export const useExtendGuest = (options?: MutationOpts<void, GuestVars & { days: number }>) =>
  useApiMutation<void, GuestVars & { days: number }>(
    {
      mutationFn: ({ communityId, userId, days }) =>
        extendCommunityGuest(communityId, userId, { days }),
      invalidate: () => invalidate(q.communityMembers()),
      errorKey: "communities:guests.extendError",
    },
    options
  );

/**
 * Make a guest a member. They take a seat, so the community list — which
 * carries the member count the invite forms read — refreshes with the roster.
 */
export const useMakeGuestAMember = (options?: MutationOpts<void, GuestVars>) => {
  const { refreshCommunities } = useCommunities();
  return useApiMutation<void, GuestVars>(
    {
      mutationFn: ({ communityId, userId }) => makeCommunityGuestAMember(communityId, userId),
      invalidate: () => {
        void refreshCommunities();
        return invalidate(q.communityMembers());
      },
      errorKey: "communities:guests.makeMemberError",
    },
    options
  );
};

/** Everybody the active community has banned, the most recent first. */
export const useCommunityBans = ({ enabled = true }: { enabled?: boolean } = {}) =>
  useListBans(useActiveCommunityId(), { query: { enabled } });

type MemberVars = { userId: number };

/** Lift a ban, so they can be invited or join again. */
export const useLiftBan = (options?: MutationOpts<void, MemberVars>) =>
  useCommunityMutation<void, MemberVars>(
    {
      mutationFn: (communityId, { userId }) => liftBan(communityId, userId),
      invalidate: () => invalidate(q.communityMembers()),
      errorKey: "communities:bans.liftError",
    },
    options
  );

/** Hold a member's content read-only until `endsAt`. Replaces a timeout they have. */
export const useTimeOutMember = (options?: MutationOpts<void, MemberVars & { endsAt: Date }>) =>
  useCommunityMutation<void, MemberVars & { endsAt: Date }>(
    {
      mutationFn: (communityId, { userId, endsAt }) =>
        timeOutMember(communityId, userId, { ends_at: endsAt.toISOString() }),
      invalidate: () => invalidate(q.communityMembers()),
      errorKey: "communities:timeOut.error",
    },
    options
  );

/** End a member's timeout early. */
export const useLiftMemberTimeout = (options?: MutationOpts<void, MemberVars>) =>
  useCommunityMutation<void, MemberVars>(
    {
      mutationFn: (communityId, { userId }) => liftMemberTimeout(communityId, userId),
      invalidate: () => invalidate(q.communityMembers()),
      errorKey: "communities:timeOut.liftError",
    },
    options
  );

type SetDisplayNameVars = { communityId: number; userId?: number; displayName: string | null };

/**
 * What somebody is called in one community — their own, without `userId`, or
 * a member's, by an administrator. The name is drawn wherever the community
 * draws people, so its content, its rosters and the people lists refresh
 * along with the community list.
 */
export const useSetMemberDisplayName = (options?: MutationOpts<void, SetDisplayNameVars>) =>
  useApiMutation<void, SetDisplayNameVars>(
    {
      mutationFn: async ({ communityId, userId, displayName }) => {
        const body = { display_name: displayName };
        await (userId === undefined
          ? setOwnDisplayName(communityId, body)
          : setMemberDisplayName(communityId, userId, body));
      },
      invalidate: () =>
        invalidate(q.communityContent(), q.communityMembers(), q.people(), q.allCommunities()),
      errorKey: "communities:displayName.saveFailed",
    },
    options
  );

type ExportCommunityUsersVars = {
  params: ExportUsersCsvParams;
  filename: string;
};

/** Download the community members CSV from the backend and trigger a browser save. */
export const useExportCommunityUsersCsv = (
  options?: MutationOpts<void, ExportCommunityUsersVars>
) =>
  useCommunityMutation<void, ExportCommunityUsersVars>(
    {
      mutationFn: async (communityId, { params, filename }) => {
        const blob = (await exportUsersCsv(communityId, params, {
          responseType: "blob",
          // FastAPI expects ?user_id=1&user_id=2; axios's default `[]` suffix gets ignored.
          paramsSerializer: { indexes: null },
        })) as Blob;
        downloadBlob(blob, filename);
      },
      errorKey: "communities:users.exportError",
    },
    options
  );

export const useUpdateNotificationPreferences = (
  options?: MutationOpts<void, Record<string, boolean | string | number | null>>
) =>
  useApiMutation<void, Record<string, boolean | string | number | null>>(
    {
      mutationFn: async (data) => {
        await updateMe(data as Parameters<typeof updateMe>[0]);
      },
      invalidate: () => invalidate(q.currentUser()),
    },
    options
  );

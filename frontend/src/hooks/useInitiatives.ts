import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  GetInitiativeMembersParams,
  InitiativeCreate,
  InitiativeDirectoryEntry,
  InitiativeJoinRequestCreate,
  InitiativeJoinRequestRead,
  InitiativeMemberListResponse,
  InitiativeMemberRead,
  InitiativeRead,
  JoinRequestStatus,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeListScope } from "@/api/generated/initiativeAPI.schemas";
import {
  addInitiativeMember,
  approveJoinRequest,
  createInitiative,
  createJoinRequest,
  deleteInitiative,
  denyJoinRequest,
  getGetInitiativeMembersQueryKey,
  getInitiativeMembers,
  joinInitiative,
  removeInitiativeMember,
  updateInitiative,
  updateInitiativeMember,
  useGetInitiative,
  useGetInitiativeMembers,
  useListInitiativeDirectory,
  useListInitiatives,
  useListJoinRequests,
} from "@/api/generated/initiatives/initiatives";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import { toast } from "@/lib/mascotToast";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * The initiatives you are in — the sidebar's list, and every initiative picker.
 *
 * A community admin is no exception here: their authority still reaches the whole
 * community, but their navigation is their own memberships. {@link useCommunityInitiatives}
 * is the community-wide listing.
 */
export const useInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  const communityId = useActiveCommunityId();
  return useListInitiatives(communityId, undefined, { query: options });
};

const COMMUNITY_SCOPE = { scope: InitiativeListScope.community } as const;

/**
 * Every initiative in the community, for the community-settings management table.
 * Community admins only — the endpoint answers 403 to anyone else.
 */
export const useCommunityInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  const communityId = useActiveCommunityId();
  return useListInitiatives(communityId, COMMUNITY_SCOPE, { query: options });
};

/**
 * Fetch initiatives for a specific community via explicit community addressing
 * (validated ?community_id=). Unlike useInitiatives, this does not depend on the
 * user's current community context — the creation wizards use it from personal
 * pages to list a chosen community's initiatives.
 */
export const useInitiativesForCommunity = (
  communityId: number | null,
  options?: QueryOpts<InitiativeRead[]>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useListInitiatives(communityId!, undefined, {
    query: { enabled: !!communityId && userEnabled, ...rest },
  });
};

/**
 * The community's initiative directory: what a member may discover and join.
 *
 * Deliberately separate from {@link useInitiatives}, which keeps its contract of
 * "initiatives you are in" — a directory entry carries only what an initiative
 * published about itself (name, colour, description, roster size) plus the
 * caller's own state, never its content. A guest has no directory to read.
 */
export const useInitiativeDirectory = (options?: QueryOpts<InitiativeDirectoryEntry[]>) => {
  const communityId = useActiveCommunityId();
  const communityWide = Boolean(useCommunities().activeCommunity?.can.community_wide);
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useListInitiativeDirectory(communityId, {
    query: { enabled: communityId > 0 && communityWide && userEnabled, ...rest },
  });
};

/**
 * One initiative's join-request queue — who has knocked, and what they said.
 *
 * Manager-only on the server (a plain member has no more business reading who
 * asked to get in than a non-member does), so callers gate the mount on the
 * same standing that gates managing the roster; a stray call answers 403 and
 * the queue simply doesn't render.
 *
 * `status` defaults to the pending rows, which is the queue in the sense that
 * matters: the ones still open to an answer.
 */
export const useInitiativeJoinRequests = (
  initiativeId: number | null,
  params?: { status?: JoinRequestStatus },
  options?: QueryOpts<InitiativeJoinRequestRead[]>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useListJoinRequests(communityId, initiativeId!, params, {
    query: { enabled: communityId > 0 && initiativeId !== null && userEnabled, ...rest },
  });
};

export const useInitiative = (initiativeId: number | null, options?: QueryOpts<InitiativeRead>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useGetInitiative(communityId, initiativeId!, undefined, {
    query: {
      enabled: initiativeId !== null && Number.isFinite(initiativeId) && userEnabled,
      ...rest,
    },
  });
};

/**
 * One page of an initiative's roster, each member with their role, searched and
 * paged on the server. A picker wants `useInitiativeMemberSearch` instead: the
 * same people, as the slimmer `UserSummary`.
 */
export const useInitiativeRoster = (
  initiativeId: number | null,
  params: GetInitiativeMembersParams,
  options?: QueryOpts<InitiativeMemberListResponse>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useGetInitiativeMembers(communityId, initiativeId!, params, {
    query: {
      enabled: initiativeId !== null && userEnabled,
      // Keep the page on screen while the next one (or the next search) loads.
      placeholderData: keepPreviousData,
      ...rest,
    },
  });
};

/**
 * An initiative's roster grown a page at a time, for a list somebody scrolls
 * and searches. Nothing is read until `enabled`, so a roster of thousands
 * costs nothing until it is opened, and then only the pages scrolled to.
 */
export const useInitiativeRosterPages = (
  initiativeId: number,
  search: string,
  enabled: boolean,
  /** Only the members who appear online, idle or busy right now. */
  online = false
) => {
  const communityId = useActiveCommunityId();
  const params = {
    search: search.trim() || undefined,
    ...(online ? { online: true } : {}),
    page_size: 50,
  };
  return useInfiniteQuery({
    queryKey: [...getGetInitiativeMembersQueryKey(communityId, initiativeId, params), "pages"],
    queryFn: ({ pageParam }) =>
      getInitiativeMembers(communityId, initiativeId, { ...params, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.has_next ? last.page + 1 : undefined),
    enabled,
    placeholderData: keepPreviousData,
  });
};

/**
 * Every manager of an initiative, read a page at a time until the roster has
 * no more. Managers are few, and a picker that ticks and unticks them needs
 * all of them to know which is which.
 */
export const useInitiativeManagers = (initiativeId: number) => {
  const communityId = useActiveCommunityId();
  const params = { is_manager: true, page_size: 100 };
  return useQuery<InitiativeMemberRead[]>({
    queryKey: [...getGetInitiativeMembersQueryKey(communityId, initiativeId, params), "every page"],
    queryFn: async () => {
      const managers = new Map<number, InitiativeMemberRead>();
      let page = 1;
      for (;;) {
        const response = await getInitiativeMembers(communityId, initiativeId, { ...params, page });
        // A page past the end is answered with page 1: the roster changed
        // between reads, so the read starts again from the page served.
        if (response.page !== page) managers.clear();
        for (const manager of response.items) managers.set(manager.user.id, manager);
        if (!response.has_next) return [...managers.values()];
        page = response.page + 1;
      }
    },
  });
};

/**
 * An initiative, resolved from the cached initiatives list — the lookup every
 * tool page header uses for its breadcrumb and its colour, since most tool
 * read schemas carry only `initiative_id`, not a nested initiative object.
 * Returns undefined until the id is set and the list has loaded (or for a
 * community-level entity with no initiative_id, forever — callers treat that as
 * "no crumb").
 */
export const useListedInitiative = (
  initiativeId: number | null | undefined
): InitiativeRead | undefined => {
  const initiativesQuery = useInitiatives({ enabled: initiativeId != null });
  return useMemo(
    () => initiativesQuery.data?.find((initiative) => initiative.id === initiativeId),
    [initiativesQuery.data, initiativeId]
  );
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateInitiativeMembersAndList = (initiativeId: number) =>
  invalidate(q.initiativeMembers(initiativeId), q.allInitiatives());

export const useCreateInitiative = (options?: MutationOpts<InitiativeRead, InitiativeCreate>) => {
  const { t } = useTranslation("initiatives");
  return useCommunityMutation<InitiativeRead, InitiativeCreate>(
    {
      // The generated InitiativeCreate carries one `{plural}_enabled` field per
      // toggleable tool — no hand-maintained field list to drift.
      mutationFn: (communityId, data) => createInitiative(communityId, data),
      invalidate: (initiative) => {
        toast.success(t("createDialog.created", { name: initiative.name }));
        return invalidate(q.allInitiatives());
      },
      errorKey: "initiatives:createDialog.createError",
    },
    options
  );
};

export const useUpdateInitiative = (
  options?: MutationOpts<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof updateInitiative>[2];
    }
  >
) =>
  useCommunityMutation<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof updateInitiative>[2];
    }
  >(
    {
      mutationFn: (communityId, { initiativeId, data }) =>
        updateInitiative(communityId, initiativeId, data),
      invalidate: (_data, { initiativeId }) =>
        invalidate(q.allInitiatives(), q.initiative(initiativeId)),
      errorKey: "initiatives:settings.updateError",
    },
    options
  );

/**
 * Self-join an `open` initiative from the community directory.
 *
 * The server decides whether the policy allows it; a refusal comes back as a
 * mapped error code the caller's toast localizes. Success creates an ordinary
 * membership row, so every community surface has to re-read.
 */
export const useJoinInitiative = (
  options?: MutationOpts<InitiativeRead, { initiativeId: number }>
) =>
  useCommunityMutation<InitiativeRead, { initiativeId: number }>(
    {
      mutationFn: (communityId, { initiativeId }) => joinInitiative(communityId, initiativeId),
      invalidate: () => invalidate(q.communityContent()),
      errorKey: "initiatives:directory.joinError",
    },
    options
  );

/**
 * Knock on a `request` initiative: ask a manager to let you in.
 *
 * Nothing about what the requester can see changes until someone answers — the
 * only thing that moves is the card's own state, so the directory is what has
 * to re-read (its `has_pending_request`), along with the queue the managers
 * are watching.
 */
export const useRequestToJoinInitiative = (
  options?: MutationOpts<
    InitiativeJoinRequestRead,
    { initiativeId: number; data: InitiativeJoinRequestCreate }
  >
) =>
  useCommunityMutation<
    InitiativeJoinRequestRead,
    { initiativeId: number; data: InitiativeJoinRequestCreate }
  >(
    {
      mutationFn: (communityId, { initiativeId, data }) =>
        createJoinRequest(communityId, initiativeId, data),
      invalidate: (_data, { initiativeId }) =>
        invalidate(q.allInitiatives(), q.initiativeJoinRequests(initiativeId)),
      errorKey: "initiatives:joinRequests.requestError",
    },
    options
  );

/**
 * Answer one knock. Approving writes the membership row every join path ends
 * at, so it refreshes as broadly as a self-join does; denying moves only the
 * queue, but both take the same route so a resolved row never lingers in one
 * surface after leaving another.
 */
export const useResolveJoinRequest = (
  options?: MutationOpts<
    InitiativeJoinRequestRead,
    { initiativeId: number; requestId: number; approved: boolean }
  >
) =>
  useCommunityMutation<
    InitiativeJoinRequestRead,
    { initiativeId: number; requestId: number; approved: boolean }
  >(
    {
      mutationFn: (communityId, { initiativeId, requestId, approved }) =>
        approved
          ? approveJoinRequest(communityId, initiativeId, requestId)
          : denyJoinRequest(communityId, initiativeId, requestId),
      invalidate: (_data, { initiativeId }) =>
        invalidate(
          q.communityContent(),
          q.initiativeMembers(initiativeId),
          q.initiativeJoinRequests(initiativeId)
        ),
      errorKey: "initiatives:joinRequests.resolveError",
    },
    options
  );

export const useDeleteInitiative = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, initiativeId) => deleteInitiative(communityId, initiativeId),
      invalidate: () => invalidate(q.allInitiatives()),
      errorKey: "initiatives:settings.deleteError",
    },
    options
  );

// Note: the add/update member endpoints return the full updated InitiativeRead
// (roster included), not a single member row — the hooks type what the API
// actually sends.
export const useAddInitiativeMember = (
  options?: MutationOpts<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof addInitiativeMember>[2];
    }
  >,
  /** What a failure says. */
  errorKey?: string
) =>
  useCommunityMutation<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof addInitiativeMember>[2];
    }
  >(
    {
      mutationFn: (communityId, { initiativeId, data }) =>
        addInitiativeMember(communityId, initiativeId, data),
      invalidate: (_data, { initiativeId }) => invalidateInitiativeMembersAndList(initiativeId),
      errorKey,
    },
    options
  );

export const useRemoveInitiativeMember = (
  options?: MutationOpts<void, { initiativeId: number; userId: number }>,
  /** What a failure says. Omit where the caller reports it itself. */
  errorKey?: string
) =>
  useCommunityMutation<void, { initiativeId: number; userId: number }>(
    {
      mutationFn: async (communityId, { initiativeId, userId }) => {
        await removeInitiativeMember(communityId, initiativeId, userId);
      },
      invalidate: (_data, { initiativeId }) => invalidateInitiativeMembersAndList(initiativeId),
      errorKey,
    },
    options
  );

export const useUpdateInitiativeMember = (
  options?: MutationOpts<
    InitiativeRead,
    {
      initiativeId: number;
      userId: number;
      data: Parameters<typeof updateInitiativeMember>[3];
    }
  >,
  /** What a failure says. */
  errorKey?: string
) =>
  useCommunityMutation<
    InitiativeRead,
    {
      initiativeId: number;
      userId: number;
      data: Parameters<typeof updateInitiativeMember>[3];
    }
  >(
    {
      mutationFn: (communityId, { initiativeId, userId, data }) =>
        updateInitiativeMember(communityId, initiativeId, userId, data),
      invalidate: (_data, { initiativeId }) => invalidateInitiativeMembersAndList(initiativeId),
      errorKey,
    },
    options
  );

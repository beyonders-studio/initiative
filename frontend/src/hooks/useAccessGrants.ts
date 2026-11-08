import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveAccessGrant,
  breakGlassAccess,
  cancelAccessRequest,
  createAccessRequest,
  denyAccessGrant,
  getListAccessGrantQueueQueryKey,
  getListAccessGrantsQueryKey,
  listAccessGrantQueue,
  listAccessGrants,
  revokeAccessGrant,
  useBreakGlassRequirements as useBreakGlassRequirementsQuery,
  useListGrantCases,
  useReadAccessGrantLimits,
} from "@/api/generated/access-grants/access-grants";
import type {
  AccessGrantApprove,
  AccessGrantCreate,
  AccessGrantListResponse,
  AccessGrantRead,
  BreakGlassCreate,
} from "@/api/generated/initiativeAPI.schemas";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

// Page size for the grant lists. The lists grow with users and usage, so they
// load a page at a time (newest-first) with a "Load more" affordance rather
// than fetching the whole history at once.
export const ACCESS_GRANTS_PAGE_SIZE = 25;

const nextPage = (last: AccessGrantListResponse) => (last.has_next ? last.page + 1 : undefined);

/** Flatten the loaded pages of an access-grants infinite query into one array. */
export const flattenGrants = (pages: AccessGrantListResponse[] | undefined): AccessGrantRead[] =>
  pages?.flatMap((page) => page.items) ?? [];

/** Any grant mutation refreshes both lists, every filter of each. */
function useInvalidateAccessGrants() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: getListAccessGrantsQueryKey() }),
      qc.invalidateQueries({
        queryKey: getListAccessGrantQueueQueryKey(),
      }),
    ]);
}

/** The current user's own access requests, paged newest-first. */
export const useMyAccessGrants = () =>
  useInfiniteQuery({
    queryKey: getListAccessGrantsQueryKey(),
    queryFn: ({ pageParam }) =>
      listAccessGrants({
        page: pageParam,
        page_size: ACCESS_GRANTS_PAGE_SIZE,
      }),
    initialPageParam: 1,
    getNextPageParam: nextPage,
  });

/**
 * The full queue filtered by status — requires access.approve (approvers). Pass
 * ``live: true`` to keep only grants still within their window (so server-side
 * paging of the active list is accurate).
 */
export const useAccessGrantQueue = (status: string | undefined, opts?: { live?: boolean }) =>
  useInfiniteQuery({
    queryKey: getListAccessGrantQueueQueryKey({
      status,
      live: opts?.live,
    }),
    queryFn: ({ pageParam }) =>
      listAccessGrantQueue({
        status,
        live: opts?.live,
        page: pageParam,
        page_size: ACCESS_GRANTS_PAGE_SIZE,
      }),
    initialPageParam: 1,
    getNextPageParam: nextPage,
  });

/**
 * The longest window the caller may request, as this deployment configures it
 * — requires access.request. The request form offers durations up to it.
 */
export const useAccessGrantLimits = (options?: { enabled?: boolean }) =>
  useReadAccessGrantLimits({ query: { enabled: options?.enabled ?? true } });

/**
 * The open operations cases a grant may be asked for, the reader's own first,
 * and whether a request must name one. Read as the reader, so it lists only
 * cases they can open.
 */
export const useGrantCases = (options?: { enabled?: boolean; search?: string }) => {
  const params = options?.search ? { search: options.search } : undefined;
  return useListGrantCases(params, { query: { enabled: options?.enabled } });
};

export const useCreateAccessRequest = (
  options?: MutationOpts<AccessGrantRead, AccessGrantCreate>
) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, AccessGrantCreate>(
    {
      mutationFn: (payload) => createAccessRequest(payload),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useApproveAccessGrant = (
  options?: MutationOpts<AccessGrantRead, { grantId: number; payload?: AccessGrantApprove }>
) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, { grantId: number; payload?: AccessGrantApprove }>(
    {
      mutationFn: ({ grantId, payload }) => approveAccessGrant(grantId, payload ?? {}),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useDenyAccessGrant = (options?: MutationOpts<AccessGrantRead, number>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, number>(
    {
      mutationFn: (grantId) => denyAccessGrant(grantId),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useRevokeAccessGrant = (options?: MutationOpts<AccessGrantRead, number>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, number>(
    {
      mutationFn: (grantId) => revokeAccessGrant(grantId),
      invalidate: () => invalidate(),
    },
    options
  );
};

/**
 * What a break-glass request will be asked for, read before the form is filled
 * in. Breaking glass carries the account's own second factor once any
 * data.bypass holder has one, which is a property of the platform rather than
 * of the caller — so the form asks rather than inferring it.
 */
export const useBreakGlassRequirements = () =>
  useBreakGlassRequirementsQuery({
    query: {
      // Somebody else enrolling changes this answer, and nothing here would know
      // to invalidate it — so it is read fresh on mount rather than inheriting
      // the shared staleness window.
      staleTime: 0,
      refetchOnMount: "always",
    },
  });

/**
 * Self-issue a break-glass grant (requires data.bypass). Unlike a request, this
 * is created AND approved in one step, so it's live immediately — the holder can
 * then enter the community via its ``/c/{community_id}`` path until it expires.
 */
export const useBreakGlass = (options?: MutationOpts<AccessGrantRead, BreakGlassCreate>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<AccessGrantRead, BreakGlassCreate>(
    {
      mutationFn: (payload) => breakGlassAccess(payload),
      invalidate: () => invalidate(),
    },
    options
  );
};

export const useCancelAccessRequest = (options?: MutationOpts<void, number>) => {
  const invalidate = useInvalidateAccessGrants();
  return useApiMutation<void, number>(
    {
      mutationFn: (grantId) => cancelAccessRequest(grantId),
      invalidate: () => invalidate(),
    },
    options
  );
};

/**
 * Holds: content kept in place for the platform.
 *
 * A community moderator holds something *for the platform*; from then on it
 * reads as absent to the whole community, the moderator included. The
 * platform reads holds, and releases them, under a `moderate` grant on the
 * community. Who may read the record is decided by the database: anyone else
 * reads none.
 */

import { placeHold, releaseHold, useListHolds } from "@/api/generated/holds/holds";
import type {
  ContentHoldRead,
  HoldCreate,
  HoldPlaced,
  HoldRelease,
} from "@/api/generated/initiativeAPI.schemas";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Every query in the communities: what a hold hides, wherever it was shown. */
export const refreshAfterHolding = () =>
  queryClient.invalidateQueries({
    predicate: (query) => {
      const [path] = query.queryKey as [unknown];
      return typeof path === "string" && path.startsWith("/api/v1/c/");
    },
  });

export const usePlaceHold = (communityId: number, options?: MutationOpts<HoldPlaced, HoldCreate>) =>
  useApiMutation<HoldPlaced, HoldCreate>(
    {
      mutationFn: (body) => placeHold(communityId, body),
      // What was held now reads as absent wherever it was shown.
      invalidate: refreshAfterHolding,
      errorKey: "moderation:hold.error",
    },
    options
  );

/** The holds on one operations case, in the community they were placed in. */
export const useCaseHolds = (
  communityId: number | null | undefined,
  caseTaskId: number,
  options?: QueryOpts<ContentHoldRead[]>
) => {
  const params = { case_task_id: caseTaskId };
  return useListHolds(communityId ?? 0, params, {
    query: {
      enabled: communityId != null,
      // Without a grant on that community the answer is a refusal, which is
      // the usual answer, not a failure.
      retry: false,
      ...options,
    },
  });
};

export const useReleaseHold = (
  communityId: number,
  options?: MutationOpts<ContentHoldRead, { holdId: number; outcome: HoldRelease }>
) =>
  useApiMutation<ContentHoldRead, { holdId: number; outcome: HoldRelease }>(
    {
      mutationFn: ({ holdId, outcome }) => releaseHold(communityId, holdId, { outcome }),
      invalidate: refreshAfterHolding,
      errorKey: "moderation:hold.releaseError",
    },
    options
  );

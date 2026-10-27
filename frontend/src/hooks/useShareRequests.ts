import { useQuery } from "@tanstack/react-query";

import type {
  ListShareRequestsParams,
  SearchEntityType,
  ShareRequestAnswer,
  ShareRequestBatch,
  ShareRequestCreate,
  ShareRequestRead,
  ShareStanding,
} from "@/api/generated/initiativeAPI.schemas";
import {
  answerShareRequests,
  createShareRequest,
  getListShareRequestsQueryKey,
  getReadShareStandingQueryKey,
  listShareRequests,
  readShareStanding,
} from "@/api/generated/sharing/sharing";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * Where the reader stands on one thing: the rung they hold on the tool that
 * decides it, and what they asked for that nobody has answered.
 *
 * A 404 is an answer rather than a failure — there is nothing to offer — and
 * any other failure leaves the page as it would have been without it, so
 * neither is asked twice.
 */
export const useShareStanding = (
  kind: SearchEntityType,
  entityId: number | null,
  enabled = true
) => {
  const communityId = useActiveCommunityId();
  const params = { kind, entity_id: entityId ?? 0 };
  return useQuery<ShareStanding>({
    queryKey: getReadShareStandingQueryKey(communityId, params),
    queryFn: () => readShareStanding(communityId, params),
    enabled: enabled && entityId !== null && Number.isFinite(entityId),
    retry: false,
    // Another thing's standing is never this one's.
    placeholderData: undefined,
  });
};

/** The requests waiting on the reader's answer: from one ask, or on one thing. */
export const useShareRequests = (params: ListShareRequestsParams, enabled = true) => {
  const communityId = useActiveCommunityId();
  return useQuery<ShareRequestRead[]>({
    queryKey: getListShareRequestsQueryKey(communityId, params),
    queryFn: () => listShareRequests(communityId, params),
    enabled,
  });
};

/** Ask for one thing, or for the files of a collection or a wiki. */
export const useCreateShareRequest = (
  options?: MutationOpts<ShareRequestBatch, ShareRequestCreate>
) =>
  useCommunityMutation<ShareRequestBatch, ShareRequestCreate>(
    {
      mutationFn: (communityId, data) => createShareRequest(communityId, data),
      // A collection and a wiki count what the reader has asked for.
      invalidate: (_, data) =>
        invalidate(
          q.shareRequests(),
          ...(data.collection_id != null ? [q.collection(data.collection_id)] : []),
          ...(data.wiki_id != null ? [q.wiki(data.wiki_id)] : [])
        ),
      errorKey: "access:request.error",
    },
    options
  );

/** An answer to some of the requests the reader may answer, by their rows. */
export type ShareRequestReply = Omit<ShareRequestAnswer, "ids"> & {
  requests: ShareRequestRead[];
};

/**
 * Say yes or no to some requests. A yes changes who can reach each thing, so
 * the reads of those tools — their pages, their sharing — are asked again.
 */
export const useAnswerShareRequests = (options?: MutationOpts<void, ShareRequestReply>) =>
  useCommunityMutation<void, ShareRequestReply>(
    {
      mutationFn: (communityId, { requests, ...answer }) =>
        answerShareRequests(communityId, { ...answer, ids: requests.map((row) => row.id) }),
      invalidate: (_, { requests, approve }) =>
        invalidate(
          q.shareRequests(),
          ...(approve
            ? [...new Set(requests.map((row) => row.resource_type))].map((tool) => q.toolList(tool))
            : [])
        ),
      errorKey: "access:answer.error",
    },
    options
  );

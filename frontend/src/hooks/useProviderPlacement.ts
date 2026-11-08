import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  PlacementCommunityRead,
  PlacementInitiativeRead,
  ProviderPlacementRuleCreate,
  ProviderPlacementRuleUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createProviderPlacementRule,
  deleteProviderPlacementRule,
  getListPlacementRequestsQueryKey,
  getListProviderPlacementQueryKey,
  setProviderPlacementEverywhere,
  updateProviderPlacementRule,
  useListPlacementCommunities,
  useListPlacementTargets,
} from "@/api/generated/provider-placement/provider-placement";
import {
  agreeCommunityNarrowing,
  getReadCommunityNarrowingsQueryKey,
} from "@/api/generated/settings/settings";
import type { QueryOpts } from "@/types/query";

/** Communities a rule for this provider may name, searched by name. */
export const usePlacementCommunities = (
  providerId: number,
  query: string,
  options?: QueryOpts<PlacementCommunityRead[]>
) => {
  const params = { provider_id: providerId, search: query.trim() || undefined };
  return useListPlacementCommunities(params, { query: options });
};

/** The initiatives, and their roles, a rule naming this community may place
 *  people in. */
export const usePlacementTargets = (
  providerId: number,
  communityId: number | null,
  options?: QueryOpts<PlacementInitiativeRead[]>
) => {
  return useListPlacementTargets(providerId, communityId ?? 0, {
    query: {
      enabled: communityId !== null,
      // A community this provider's rules do not reach answers 404; asking
      // again would not change that.
      retry: false,
      ...options,
    },
  });
};

const useInvalidatePlacement = () => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListProviderPlacementQueryKey(),
    });
  };
};

/** Apply the rules to every community they name, or only where accepted. */
export const useSetPlacementEverywhere = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: (enabled: boolean) => setProviderPlacementEverywhere({ enabled }),
    onSuccess: invalidate,
  });
};

export const useCreatePlacementRule = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: (data: ProviderPlacementRuleCreate) => createProviderPlacementRule(data),
    onSuccess: invalidate,
  });
};

export const useUpdatePlacementRule = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: ({ ruleId, data }: { ruleId: number; data: ProviderPlacementRuleUpdate }) =>
      updateProviderPlacementRule(ruleId, data),
    onSuccess: invalidate,
  });
};

export const useDeletePlacementRule = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: (ruleId: number) => deleteProviderPlacementRule(ruleId),
    onSuccess: invalidate,
  });
};

/** Agree that a community's claim is its own, from the list of those waiting. */
export const useAgreePlacementRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ communityId, connectionId }: { communityId: number; connectionId: number }) =>
      agreeCommunityNarrowing(communityId, connectionId, { agreed: true }),
    onSuccess: (_data, { communityId }) => {
      void queryClient.invalidateQueries({
        queryKey: getListPlacementRequestsQueryKey(),
      });
      void queryClient.invalidateQueries({
        queryKey: getReadCommunityNarrowingsQueryKey(communityId),
      });
    },
  });
};

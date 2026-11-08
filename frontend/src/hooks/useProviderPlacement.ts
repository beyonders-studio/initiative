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
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
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

const invalidatePlacement = () =>
  queryClient.invalidateQueries({ queryKey: getListProviderPlacementQueryKey() });

/** Apply the rules to every community they name, or only where accepted. */
export const useSetPlacementEverywhere = () =>
  useApiMutation({
    mutationFn: (enabled: boolean) => setProviderPlacementEverywhere({ enabled }),
    invalidate: invalidatePlacement,
    errorKey: "settings:providerPlacement.everywhere.error",
  });

export const useCreatePlacementRule = () =>
  useApiMutation({
    mutationFn: (data: ProviderPlacementRuleCreate) => createProviderPlacementRule(data),
    invalidate: invalidatePlacement,
    errorKey: "settings:providerPlacement.addError",
  });

export const useUpdatePlacementRule = () =>
  useApiMutation({
    mutationFn: ({ ruleId, data }: { ruleId: number; data: ProviderPlacementRuleUpdate }) =>
      updateProviderPlacementRule(ruleId, data),
    invalidate: invalidatePlacement,
    errorKey: "settings:providerPlacement.saveError",
  });

export const useDeletePlacementRule = () =>
  useApiMutation({
    mutationFn: (ruleId: number) => deleteProviderPlacementRule(ruleId),
    invalidate: invalidatePlacement,
    errorKey: "settings:providerPlacement.removeError",
  });

/** Agree that a community's claim is its own, from the list of those waiting. */
export const useAgreePlacementRequest = () =>
  useApiMutation({
    mutationFn: ({ communityId, connectionId }: { communityId: number; connectionId: number }) =>
      agreeCommunityNarrowing(communityId, connectionId, { agreed: true }),
    invalidate: (_data, { communityId }) => {
      void queryClient.invalidateQueries({ queryKey: getListPlacementRequestsQueryKey() });
      void queryClient.invalidateQueries({
        queryKey: getReadCommunityNarrowingsQueryKey(communityId),
      });
    },
    errorKey: "settings:communities.sheet.narrowings.error",
  });

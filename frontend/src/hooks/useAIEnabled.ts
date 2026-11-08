import { useGetResolvedAiSettings } from "@/api/generated/ai-settings/ai-settings";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

/**
 * Whether AI features are available to the current member in the active community.
 *
 * AI resolution is community-scoped: the backend collapses the global mode and
 * the owner's default connection into a single `enabled` flag on
 * `GET /c/{communityId}/settings/ai/resolved`, and names the mode as `source`.
 * The member is AI enabled exactly when that endpoint returns `enabled: true`,
 * so we trust it directly rather than re-deriving credential state on the
 * client.
 */
export const useAIEnabled = () => {
  const communityId = useActiveCommunityId();
  const query = useGetResolvedAiSettings(communityId, {
    query: { enabled: communityId > 0, staleTime: 5 * 60 * 1000 },
  });

  return {
    isEnabled: Boolean(query.data?.enabled),
    isLoading: query.isLoading,
    isError: query.isError,
    data: query.data,
  };
};

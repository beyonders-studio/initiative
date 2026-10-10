import { useBootstrapStatus } from "@/api/generated/auth/auth";
import { useAuth } from "@/hooks/useAuth";
import { type CommunityEntry, useCommunities } from "@/hooks/useCommunities";

export interface DemoCopy {
  /** When the copy, and the account with it, is deleted. */
  expiresAt: string;
  /** The copy's community. */
  communityId: number;
  /** The copy, once the community list has loaded. */
  community: CommunityEntry | null;
}

/**
 * The demo copy the signed-in account was made for, or null for every account
 * that was not made by a demo link.
 */
export const useDemoCopy = (): DemoCopy | null => {
  const { user } = useAuth();
  const { communities } = useCommunities();
  const communityId = user?.demo_community_id;
  if (!user?.demo_expires_at || communityId == null) return null;
  return {
    expiresAt: user.demo_expires_at,
    communityId,
    community: communities.find((community) => community.id === communityId) ?? null,
  };
};

/** Whether this server is the demo deployment, which names itself "Demo".
 *  With `enabled` false it asks nothing and answers false. */
export const useIsDemoServer = (enabled = true): boolean =>
  useBootstrapStatus({ query: { staleTime: 60_000, enabled } }).data?.demo === true;

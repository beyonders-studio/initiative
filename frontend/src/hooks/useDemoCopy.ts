import { useAuth } from "@/hooks/useAuth";
import { type CommunityEntry, useCommunities } from "@/hooks/useCommunities";

export interface DemoCopy {
  /** When the copy, and the account with it, is deleted. */
  expiresAt: string;
  /** The copy, once the community list has loaded. */
  community: CommunityEntry | null;
}

/**
 * The demo copy the signed-in account was made for, or null for every account
 * that was not made by a demo link.
 *
 * A demo link makes its account a member of its copy and nothing else, so the
 * copy is the account's first community.
 */
export const useDemoCopy = (): DemoCopy | null => {
  const { user } = useAuth();
  const { communities } = useCommunities();
  if (!user?.demo_expires_at) return null;
  return { expiresAt: user.demo_expires_at, community: communities[0] ?? null };
};

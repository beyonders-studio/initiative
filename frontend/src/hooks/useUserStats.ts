import { useGetUserStats } from "@/api/generated/users/users";

export function useUserStats(communityId?: number | null) {
  const params = communityId ? { community_id: communityId } : undefined;

  return useGetUserStats(params, { query: { staleTime: 5 * 60 * 1000 } });
}

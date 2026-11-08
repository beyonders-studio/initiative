/**
 * Reactions are read as part of whatever carries them — a comment arrives with
 * its `reactions` already filled — so there is no list query here, only the
 * toggle and the suggested set.
 */

import type { ReactionSummary, ReactionTarget } from "@/api/generated/initiativeAPI.schemas";
import {
  toggleReaction,
  useSuggestedReactions as useSuggestedReactionsQuery,
} from "@/api/generated/reactions/reactions";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** What each reaction target invalidates once its reactions move. */
const INVALIDATE_BY_TARGET: Record<ReactionTarget, () => void> = {
  // The bar draws the reply itself, and the thread hears it as the comment's
  // own change, so only the community's feed — which shows the chips too — is left.
  comment: () => void invalidate(q.recentComments()),
  // A post's chips ride along with the post, so the board and the post's own
  // page both have to hear it — which is what invalidating the whole list does.
  post: () => void invalidate(q.allPosts()),
};

/**
 * The emoji every picker offers first. Served by the backend so the row is one
 * product-wide decision — the same suggestions for everyone, rather than
 * whatever each browser happened to pick last.
 */
export const useSuggestedReactions = (options?: QueryOpts<string[]>) => {
  const communityId = useActiveCommunityId();
  return useSuggestedReactionsQuery(communityId, {
    // A fixed list; there is no reason to ask again this session.
    query: { staleTime: Number.POSITIVE_INFINITY, ...options },
  });
};

export interface ToggleReactionVars {
  targetType: ReactionTarget;
  targetId: number;
  emoji: string;
}

/**
 * Add this emoji, or take it back if it is already yours. The reply is the
 * target's whole reaction state, so the caller can render from it directly
 * while the invalidated queries refetch.
 */
export const useToggleReaction = (options?: MutationOpts<ReactionSummary, ToggleReactionVars>) =>
  useCommunityMutation<ReactionSummary, ToggleReactionVars>(
    {
      mutationFn: (communityId, { targetType, targetId, emoji }) =>
        toggleReaction(communityId, targetType, targetId, {
          emoji,
        }),
      invalidate: (_data, vars) => INVALIDATE_BY_TARGET[vars.targetType]?.(),
      errorKey: "common:reactions.error",
    },
    options
  );

import { createFileRoute, redirect } from "@tanstack/react-router";

import { communityPath } from "@/lib/communityUrl";
import { resolveEntityPath } from "@/lib/entityResolver";

/**
 * Resolve a bare entity reference to the URL that addresses it.
 *
 * A tool entity's address names its initiative, and a few callers hold only an
 * id — a `@mention` in comment text, a stored notification target, a reported
 * comment. They link here; the loader reads the entity, works out where it
 * lives, and redirects before anything renders, keeping the query (an event's
 * `occurrence`) and, for a comment, landing on the comment itself.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/go/$refType/$refId"
)({
  loader: async ({ context, params, location }) => {
    const communityId = Number(params.communityId);
    const path = await resolveEntityPath(
      context.queryClient,
      communityId,
      params.refType,
      Number(params.refId)
    );
    // Unresolvable — deleted, or not visible to this reader. The community home is
    // the honest landing spot; guessing at an address would 404 instead.
    // A comment's address ends in the fragment its thread scrolls to.
    const [target, fragment] = (path ?? "/").split("#");
    throw redirect({
      to: communityPath(communityId, target),
      search: path ? location.search : {},
      ...(fragment ? { hash: fragment } : {}),
      replace: true,
    });
  },
});

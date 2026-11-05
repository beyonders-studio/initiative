import { useParams, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { canonicalInitiativePath } from "@/lib/communityUrl";

/**
 * The initiative an entity page is addressed under.
 *
 * The path is the source of truth while the entity loads — that is what lets a
 * "not found" or "no access" page still offer a back-link. But the entity is
 * the authority once it arrives: an address naming a different initiative is
 * simply wrong, and left alone it would go on generating child, settings and
 * back links into an initiative the entity isn't in.
 *
 * So a disagreement is corrected rather than tolerated — the URL is rewritten
 * in place (no history entry) to the entity's own address, and every caller
 * gets the entity's initiative back.
 *
 * Pass `undefined` while loading. Pass `null` for a genuinely community-level
 * entity (a calendar or contact a community plug-in holds) — that is an
 * address, not a missing value.
 */
export function useCanonicalInitiativeId(
  entityInitiativeId: number | null | undefined
): number | null {
  const router = useRouter();
  const { initiativeId: param } = useParams({ strict: false }) as { initiativeId?: string };
  const fromPath = param ? Number(param) : null;
  const settled = entityInitiativeId !== undefined;
  const effective = settled ? entityInitiativeId : fromPath;

  useEffect(() => {
    if (!settled || entityInitiativeId === fromPath) return;
    const { pathname, search, hash } = router.state.location;
    const corrected = canonicalInitiativePath(pathname, entityInitiativeId);
    if (corrected === pathname) return;
    // Search and hash are handed over as they are rather than pasted onto the
    // path: `search` is the parsed object, not a string, so building a URL out
    // of it threw instead of navigating.
    void router.navigate({ to: corrected, search, hash, replace: true });
  }, [router, settled, entityInitiativeId, fromPath]);

  return effective;
}

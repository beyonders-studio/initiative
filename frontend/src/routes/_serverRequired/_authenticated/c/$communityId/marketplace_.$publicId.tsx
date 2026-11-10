import { createFileRoute } from "@tanstack/react-router";

import type { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { parseListingKind } from "@/lib/marketplace";
import { ListingPage } from "@/pages/community/marketplace/ListingPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/marketplace_/$publicId"
)({
  // `kind` is carried so the back link can return to the shelf the listing
  // was found on; `next` is where installing it returns to, when a plug-in's
  // sign-in sent the seat here to add it.
  validateSearch: (search: Record<string, unknown>): { kind?: ListingKind; next?: string } => {
    const kind = parseListingKind(search.kind);
    return {
      ...(kind ? { kind } : {}),
      ...(typeof search.next === "string" && search.next.startsWith("/")
        ? { next: search.next }
        : {}),
    };
  },
  component: ListingPage,
});

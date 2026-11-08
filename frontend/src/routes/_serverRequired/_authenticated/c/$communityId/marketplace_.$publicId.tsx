import { createFileRoute } from "@tanstack/react-router";

import type { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { parseListingKind } from "@/lib/marketplace";
import { MarketplaceListingPage } from "@/pages/marketplace/MarketplaceListingPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/marketplace_/$publicId"
)({
  // Carried so the back link can return to the shelf the listing was found on.
  validateSearch: (search: Record<string, unknown>): { kind?: ListingKind } => {
    const kind = parseListingKind(search.kind);
    return kind ? { kind } : {};
  },
  component: MarketplaceListingPage,
});

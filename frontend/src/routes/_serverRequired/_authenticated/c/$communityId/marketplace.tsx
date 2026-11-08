import { createFileRoute } from "@tanstack/react-router";

import { type CommunityShelf, parseCommunityShelf } from "@/lib/marketplace";
import { MarketplaceBrowsePage } from "@/pages/marketplace/MarketplaceBrowsePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/marketplace")({
  /** Which shelf of this community's marketplace to show. The shelves a person
   *  buys from — profile packs — have their own marketplace and are not here;
   *  see `@/lib/marketplace`, which is where the accepted values come from. */
  validateSearch: (search: Record<string, unknown>): { kind: CommunityShelf } => ({
    kind: parseCommunityShelf(search.kind),
  }),
  component: MarketplaceBrowsePage,
});

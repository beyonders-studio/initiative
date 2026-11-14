import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { MarketplacePage } from "@/pages/my/marketplace/MarketplacePage";

// Outside the `/c/$communityId` tree: what is sold here installs to a person, not
// to a community, and belongs to them in every community they are in.
export const Route = createFileRoute("/_serverRequired/_authenticated/marketplace")({
  component: MarketplaceRoute,
});

function MarketplaceRoute() {
  const { user } = useAuth();
  if (!user) return null;
  return <MarketplacePage user={user} />;
}

import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/hooks/useAuth";
import { UserMarketplacePage } from "@/pages/marketplace/UserMarketplacePage";

// Outside the `/c/$communityId` tree: what is sold here installs to a person, not
// to a community, and belongs to them in every community they are in.
export const Route = createFileRoute("/_serverRequired/_authenticated/marketplace")({
  component: MarketplacePage,
});

function MarketplacePage() {
  const { user } = useAuth();
  if (!user) return null;
  return <UserMarketplacePage user={user} />;
}

import { createFileRoute } from "@tanstack/react-router";

import type { BillingPortalPage } from "@/hooks/useBillingPortal";
import { BillingForwardPage } from "@/pages/community/settings/usage/BillingForwardPage";

/**
 * Forwards to the billing portal for one community, for links sent by email.
 *
 * Outside the `$communityId` layout on purpose: that layout serves only
 * communities in the community list, and one on hold is not in it. The handoff
 * request decides who may go on.
 */
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId_/billing")({
  validateSearch: (search: Record<string, unknown>): { page: BillingPortalPage } => ({
    page: search.page === "upgrade" ? "upgrade" : "manage",
  }),
  component: BillingForwardPage,
});

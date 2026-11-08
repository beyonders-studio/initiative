import { createFileRoute } from "@tanstack/react-router";

import { CommunityInvitePage } from "@/pages/CommunityInvitePage";

export const Route = createFileRoute("/_serverRequired/invite/$code")({
  component: CommunityInvitePage,
});

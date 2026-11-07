import { createFileRoute } from "@tanstack/react-router";

import { CommunityLoginPage } from "@/pages/CommunityLoginPage";

export const Route = createFileRoute("/_serverRequired/community/$communityId/login")({
  component: CommunityLoginPage,
});

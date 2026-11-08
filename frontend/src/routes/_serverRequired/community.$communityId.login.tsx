import { createFileRoute } from "@tanstack/react-router";

import { CommunitySignInPage } from "@/pages/signIn/CommunitySignInPage";

export const Route = createFileRoute("/_serverRequired/community/$communityId/login")({
  component: CommunitySignInPage,
});

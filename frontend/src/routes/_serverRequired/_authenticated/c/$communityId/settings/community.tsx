import { createFileRoute } from "@tanstack/react-router";

import { CommunityPage } from "@/pages/community/settings/community/CommunityPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/community"
)({
  component: CommunityPage,
});

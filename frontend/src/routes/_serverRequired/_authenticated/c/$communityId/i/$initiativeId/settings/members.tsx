import { createFileRoute } from "@tanstack/react-router";

import { MembersPage } from "@/pages/community/initiatives/settings/members/MembersPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/members"
)({
  component: MembersPage,
});

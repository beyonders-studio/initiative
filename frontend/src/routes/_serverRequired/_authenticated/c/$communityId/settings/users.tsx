import { createFileRoute } from "@tanstack/react-router";

import { UsersPage } from "@/pages/community/settings/users/UsersPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/users"
)({
  component: UsersPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { SettingsUsersPage } from "@/pages/SettingsUsersPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/users"
)({
  component: SettingsUsersPage,
});

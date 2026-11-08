import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityRolesPage } from "@/pages/SettingsCommunityRolesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/roles"
)({
  component: SettingsCommunityRolesPage,
});

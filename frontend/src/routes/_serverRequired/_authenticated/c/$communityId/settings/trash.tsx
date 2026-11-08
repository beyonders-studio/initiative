import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityTrashPage } from "@/pages/SettingsCommunityTrashPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/trash"
)({
  component: SettingsCommunityTrashPage,
});

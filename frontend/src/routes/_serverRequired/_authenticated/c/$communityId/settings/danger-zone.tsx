import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityDangerZonePage } from "@/pages/SettingsCommunityDangerZonePage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/danger-zone"
)({
  component: SettingsCommunityDangerZonePage,
});

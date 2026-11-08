import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityIndexPage } from "@/pages/SettingsCommunityIndexPage";

// No page of its own: `/settings` sends each person to the first tab they may
// open — see SettingsCommunityIndexPage.
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/settings/")({
  component: SettingsCommunityIndexPage,
});

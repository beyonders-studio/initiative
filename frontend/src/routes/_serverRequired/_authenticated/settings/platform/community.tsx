import { createFileRoute } from "@tanstack/react-router";

import { SettingsPlatformCommunityPage } from "@/pages/SettingsPlatformCommunityPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/community")(
  {
    component: SettingsPlatformCommunityPage,
  }
);

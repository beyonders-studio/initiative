import { createFileRoute } from "@tanstack/react-router";

import { SettingsPlatformAnnouncementsPage } from "@/pages/SettingsPlatformAnnouncementsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/operator/announcements"
)({
  component: SettingsPlatformAnnouncementsPage,
});

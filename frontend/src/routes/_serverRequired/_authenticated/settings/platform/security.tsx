import { createFileRoute } from "@tanstack/react-router";

import { SettingsPlatformSecurityPage } from "@/pages/SettingsPlatformSecurityPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/security")({
  component: SettingsPlatformSecurityPage,
});

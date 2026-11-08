import { createFileRoute } from "@tanstack/react-router";

import { SettingsPlatformUsersPage } from "@/pages/SettingsPlatformUsersPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/users")({
  component: SettingsPlatformUsersPage,
});

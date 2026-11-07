import { createFileRoute } from "@tanstack/react-router";

import { UserSettingsSecurityPage } from "@/pages/user/settings/UserSettingsSecurityPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/security")({
  component: UserSettingsSecurityPage,
});

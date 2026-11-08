import { createFileRoute } from "@tanstack/react-router";

import { UserSettingsPrivacyPage } from "@/pages/user/settings/UserSettingsPrivacyPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/privacy")({
  component: UserSettingsPrivacyPage,
});

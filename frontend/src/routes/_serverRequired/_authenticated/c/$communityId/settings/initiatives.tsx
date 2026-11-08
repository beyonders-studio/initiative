import { createFileRoute } from "@tanstack/react-router";

import { SettingsInitiativesPage } from "@/pages/SettingsInitiativesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/initiatives"
)({
  component: SettingsInitiativesPage,
});

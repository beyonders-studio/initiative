import { createFileRoute } from "@tanstack/react-router";

import { WikiSettingsPage } from "@/pages/initiativeTools/wikis/WikiSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/settings"
)({
  component: WikiSettingsPage,
});

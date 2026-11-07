import { createFileRoute } from "@tanstack/react-router";

import { ToolSettingsDetailsPage } from "@/pages/toolSettings/ToolSettingsDetailsPage";

// Details is what a wiki's settings open on, so it is served at `/settings`
// itself rather than redirecting to a `/settings/details` alias.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/settings/"
)({
  component: ToolSettingsDetailsPage,
});

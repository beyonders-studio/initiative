import { createFileRoute } from "@tanstack/react-router";

import { AdvancedPage } from "@/pages/community/tools/settings/AdvancedPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/settings/advanced"
)({
  component: AdvancedPage,
});

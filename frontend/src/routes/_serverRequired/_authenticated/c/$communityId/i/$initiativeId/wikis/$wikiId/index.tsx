import { createFileRoute } from "@tanstack/react-router";

import { WikiPage } from "@/pages/community/tools/wikis/WikiPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/wikis/$wikiId/"
)({
  // A wiki is a surface, not a page in the reading column: it puts its
  // own header against the top and scrolls its own middle.
  staticData: { fullBleed: true },
  component: WikiPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { AdvancedPage } from "@/pages/community/tools/settings/AdvancedPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/posts/$postId/settings/advanced"
)({
  component: AdvancedPage,
});

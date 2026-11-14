import { createFileRoute } from "@tanstack/react-router";

import { LayoutsPage } from "@/pages/community/initiatives/settings/LayoutsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/layouts"
)({
  component: LayoutsPage,
});

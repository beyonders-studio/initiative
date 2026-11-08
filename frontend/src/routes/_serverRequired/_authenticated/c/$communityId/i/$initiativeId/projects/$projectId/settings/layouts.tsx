import { createFileRoute } from "@tanstack/react-router";

import { LayoutsPage } from "@/pages/community/tools/settings/LayoutsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/layouts"
)({
  component: LayoutsPage,
});

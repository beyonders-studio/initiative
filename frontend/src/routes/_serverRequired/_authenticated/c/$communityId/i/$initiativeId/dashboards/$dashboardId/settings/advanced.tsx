import { createFileRoute } from "@tanstack/react-router";

import { AdvancedPage } from "@/pages/community/tools/settings/AdvancedPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/$dashboardId/settings/advanced"
)({
  component: AdvancedPage,
});

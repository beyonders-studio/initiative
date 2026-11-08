import { createFileRoute } from "@tanstack/react-router";

import { ExportPage } from "@/pages/community/initiatives/settings/ExportPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/export"
)({
  component: ExportPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { DangerPage } from "@/pages/community/initiatives/settings/DangerPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/danger"
)({
  component: DangerPage,
});

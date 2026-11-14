import { createFileRoute } from "@tanstack/react-router";

import { DangerZonePage } from "@/pages/community/settings/DangerZonePage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/danger-zone"
)({
  component: DangerZonePage,
});

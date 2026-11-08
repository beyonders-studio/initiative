import { createFileRoute } from "@tanstack/react-router";

import { TrashPage } from "@/pages/community/settings/TrashPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/trash"
)({
  component: TrashPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { DataPage } from "@/pages/community/settings/data/DataPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/data"
)({
  component: DataPage,
});

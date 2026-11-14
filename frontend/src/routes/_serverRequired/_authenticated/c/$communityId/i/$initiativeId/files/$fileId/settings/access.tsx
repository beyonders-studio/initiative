import { createFileRoute } from "@tanstack/react-router";

import { AccessPage } from "@/pages/community/tools/settings/AccessPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/$fileId/settings/access"
)({
  component: AccessPage,
});

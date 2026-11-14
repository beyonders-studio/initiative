import { createFileRoute } from "@tanstack/react-router";

import { SecurityPage } from "@/pages/community/settings/security/SecurityPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/security"
)({
  component: SecurityPage,
});

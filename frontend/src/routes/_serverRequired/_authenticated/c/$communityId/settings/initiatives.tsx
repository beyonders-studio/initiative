import { createFileRoute } from "@tanstack/react-router";

import { InitiativesPage } from "@/pages/community/settings/initiatives/InitiativesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/initiatives"
)({
  component: InitiativesPage,
});

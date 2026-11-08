import { createFileRoute } from "@tanstack/react-router";

import { DetailsPage } from "@/pages/community/tools/settings/DetailsPage";

// Details is what a counter group's settings open on, so it is served at `/settings`
// itself rather than redirecting to a `/settings/details` alias.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings/"
)({
  component: DetailsPage,
});

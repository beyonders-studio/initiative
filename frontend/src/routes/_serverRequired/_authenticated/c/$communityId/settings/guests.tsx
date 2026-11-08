import { createFileRoute } from "@tanstack/react-router";

import { GuestsPage } from "@/pages/community/settings/GuestsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/guests"
)({
  component: GuestsPage,
});

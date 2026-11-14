import { createFileRoute } from "@tanstack/react-router";

import { ModerationPage } from "@/pages/community/initiatives/moderation/ModerationPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/moderation"
)({
  component: ModerationPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { ModerationPage } from "@/pages/ModerationPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/moderation"
)({
  component: ModerationPage,
});

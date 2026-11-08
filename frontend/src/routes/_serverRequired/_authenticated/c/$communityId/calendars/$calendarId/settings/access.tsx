import { createFileRoute } from "@tanstack/react-router";

import { AccessPage } from "@/pages/community/tools/settings/AccessPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/settings/access"
)({
  component: AccessPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { CommunityCalendarsPage } from "@/pages/community/tools/calendars/CalendarsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/calendars/")({
  component: CommunityCalendarsPage,
});

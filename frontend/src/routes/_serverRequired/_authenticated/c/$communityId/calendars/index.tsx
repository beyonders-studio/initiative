import { createFileRoute } from "@tanstack/react-router";

import { CommunityCalendarsPage } from "@/pages/initiativeTools/events/CalendarsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/calendars/")({
  component: CommunityCalendarsPage,
});

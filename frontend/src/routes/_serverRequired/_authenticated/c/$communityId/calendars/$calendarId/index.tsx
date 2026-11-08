import { createFileRoute } from "@tanstack/react-router";

import { CalendarFocusPage } from "@/pages/initiativeTools/events/CalendarsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/"
)({
  component: CalendarFocusPage,
});

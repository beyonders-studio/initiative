import { createFileRoute } from "@tanstack/react-router";

import { CalendarFocusPage } from "@/pages/community/tools/calendars/CalendarsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/"
)({
  component: CalendarFocusPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { CalendarSettingsPage } from "@/pages/initiativeTools/events/CalendarSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/settings"
)({
  component: CalendarSettingsPage,
});

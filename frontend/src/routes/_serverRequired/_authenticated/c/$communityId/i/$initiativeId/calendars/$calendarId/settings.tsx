import { createFileRoute } from "@tanstack/react-router";

import { CalendarSettingsPage } from "@/pages/initiativeTools/events/CalendarSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/$calendarId/settings"
)({
  component: CalendarSettingsPage,
});

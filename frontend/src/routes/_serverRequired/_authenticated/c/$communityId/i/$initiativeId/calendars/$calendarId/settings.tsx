import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CalendarColorCard } from "@/pages/community/tools/calendars/CalendarColorCard";
import { SettingsLayout } from "@/pages/community/tools/settings/SettingsLayout";

// The calendar's single sharing surface — its events inherit all of it.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/$calendarId/settings"
)({
  component: () => <SettingsLayout tool={Tool.calendar} detailsExtra={<CalendarColorCard />} />,
});

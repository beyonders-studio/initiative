import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CalendarColorCard } from "@/components/initiativeTools/events/CalendarColorCard";
import { ToolSettingsPage } from "@/pages/toolSettings/ToolSettingsPage";

// The calendar's single sharing surface — its events inherit all of it.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/settings"
)({
  component: () => <ToolSettingsPage tool={Tool.calendar} detailsExtra={<CalendarColorCard />} />,
});

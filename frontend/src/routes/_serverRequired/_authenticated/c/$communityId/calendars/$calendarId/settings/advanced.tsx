import { createFileRoute } from "@tanstack/react-router";

import { ToolSettingsAdvancedPage } from "@/pages/toolSettings/ToolSettingsAdvancedPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/settings/advanced"
)({
  component: ToolSettingsAdvancedPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { EventPage } from "@/pages/community/tools/calendars/EventPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/events/$eventId/"
)({
  validateSearch: (search: Record<string, unknown>): { occurrence?: string } => ({
    occurrence: typeof search.occurrence === "string" ? search.occurrence : undefined,
  }),
  component: EventPage,
});

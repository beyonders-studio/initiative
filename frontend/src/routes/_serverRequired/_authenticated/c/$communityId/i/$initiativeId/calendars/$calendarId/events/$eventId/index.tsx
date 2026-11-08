import { createFileRoute } from "@tanstack/react-router";

import { EventDetailPage } from "@/pages/initiativeTools/events/EventDetailPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/$calendarId/events/$eventId/"
)({
  validateSearch: (search: Record<string, unknown>): { occurrence?: string } => ({
    occurrence: typeof search.occurrence === "string" ? search.occurrence : undefined,
  }),
  component: EventDetailPage,
});

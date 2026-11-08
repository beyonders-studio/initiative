import { createFileRoute } from "@tanstack/react-router";

import { TicketPage } from "@/pages/my/tickets/TicketPage";

// Not under `/c/$communityId`: a ticket is the filer's own, followed from outside
// the community that works it — they are not a member there.
export const Route = createFileRoute("/_serverRequired/_authenticated/my-tickets/$taskId")({
  component: TicketPage,
});

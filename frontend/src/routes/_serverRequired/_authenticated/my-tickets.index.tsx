import { createFileRoute } from "@tanstack/react-router";

import { TicketsPage } from "@/pages/my/tickets/TicketsPage";

export interface MyTicketsSearch {
  /** Open a filing form on arrival. ``security`` is what the server's
   *  ``/.well-known/security.txt`` links to. */
  report?: "security";
}

export const Route = createFileRoute("/_serverRequired/_authenticated/my-tickets/")({
  validateSearch: (search: Record<string, unknown>): MyTicketsSearch =>
    search.report === "security" ? { report: "security" } : {},
  component: TicketsPage,
});

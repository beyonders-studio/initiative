/**
 * One ticket the reader filed: where it stands, what has been said to them
 * about it, and — where the ticket takes it — their answer.
 *
 * The people handling it are shown as the team, never by name, and only what
 * was said to the reader is here; the team's own notes are not.
 */
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { FilerState } from "@/api/generated/initiativeAPI.schemas";
import { TicketConversation } from "@/components/tickets/TicketConversation";
import { TicketStateBadge } from "@/components/tickets/TicketStateBadge";
import { useFiledTicket } from "@/hooks/useTickets";
import { ticketTitle } from "@/lib/ticketTitle";
import { Button } from "@/ui/button";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { SkeletonRegion } from "@/ui/page-skeletons";
import { Skeleton } from "@/ui/skeleton";

export const TicketPage = () => {
  const { taskId: raw } = useParams({ strict: false }) as { taskId: string };
  // One ticket's draft is never another's: opening a different ticket on the
  // same route starts its page afresh.
  return <TicketView key={raw} taskId={Number(raw)} />;
};

const TicketView = ({ taskId }: { taskId: number }) => {
  const { t } = useTranslation(["intake", "common"]);
  const ticketQuery = useFiledTicket(taskId, { enabled: Number.isFinite(taskId) });
  const opened = useRelativeTime(ticketQuery.data?.opened_at ?? null);

  const ticket = ticketQuery.data;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/my-tickets">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t("tickets.back")}
        </Link>
      </Button>

      {ticketQuery.isLoading ? (
        <SkeletonRegion>
          <Skeleton className="h-9 w-2/3" />
          <Skeleton className="h-40 w-full" />
        </SkeletonRegion>
      ) : !ticket ? (
        <p className="py-8 text-center text-muted-foreground text-sm">{t("tickets.notFound")}</p>
      ) : (
        <>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-semibold text-2xl tracking-tight">{ticketTitle(t, ticket)}</h1>
              <TicketStateBadge state={ticket.state} />
            </div>
            <p className="text-muted-foreground text-sm">
              {t(`streams.${ticket.stream}.title`)} · {t("tickets.opened", { when: opened })}
            </p>
            {ticket.state === FilerState.waiting_on_you ? (
              <p className="text-sm">{t("tickets.waitingNote")}</p>
            ) : null}
          </div>

          <TicketConversation ticket={ticket} />
        </>
      )}
    </div>
  );
};

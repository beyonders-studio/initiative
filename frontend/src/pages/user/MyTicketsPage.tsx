/**
 * The tickets the reader filed: where each stands, most recently moved first.
 *
 * Not tasks: a filer follows where their ticket stands and what is said to
 * them, never the task the team works it in. The sidebar offers this page once
 * they have filed something. It is also where a security problem is reported
 * from, and where ``/.well-known/security.txt`` sends people to do it.
 */
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { FiledTicketRead } from "@/api/generated/initiativeAPI.schemas";
import {
  ReportSecurityProblemButton,
  SecurityReportDialog,
} from "@/components/tickets/ReportSecurityProblem";
import { TicketStateBadge } from "@/components/tickets/TicketStateBadge";
import { useFiledTickets } from "@/hooks/useTickets";
import { ticketTitle } from "@/lib/ticketTitle";
import { Card } from "@/ui/card";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { SkeletonRegion } from "@/ui/page-skeletons";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

const TicketRow = ({ ticket }: { ticket: FiledTicketRead }) => {
  const { t } = useTranslation("intake");
  const moved = useRelativeTime(ticket.updated_at ?? ticket.opened_at);
  return (
    <li>
      <Link
        to="/my-tickets/$taskId"
        params={{ taskId: String(ticket.task_id) }}
        className="flex items-center gap-3 px-4 py-3 hover:bg-muted focus-visible:bg-muted"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-sm">{ticketTitle(t, ticket)}</p>
          <p className="text-muted-foreground text-xs">
            {t(`streams.${ticket.stream}.title`)} · {moved}
          </p>
        </div>
        <TicketStateBadge state={ticket.state} />
      </Link>
    </li>
  );
};

export const MyTicketsPage = () => {
  const { t } = useTranslation(["intake", "nav"]);
  const { data, isLoading, isError, refetch } = useFiledTickets();
  const items = data?.items ?? [];
  const { report } = useSearch({ strict: false }) as { report?: string };
  const navigate = useNavigate();
  const [reporting, setReporting] = useState(report === "security");
  // Asked for again while already here — the command palette, say — opens it
  // too, not only on arrival.
  const [prevReport, setPrevReport] = useState(report);
  if (prevReport !== report) {
    setPrevReport(report);
    if (report === "security") setReporting(true);
  }

  const closeReport = (open: boolean) => {
    setReporting(open);
    // Arrived from a link to the form: closing it leaves the list, not the
    // link, so going back does not open it again.
    if (!open && report) void navigate({ to: "/my-tickets", search: {}, replace: true });
  };

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-semibold text-3xl tracking-tight">{t("nav:myTickets")}</h1>
        <ReportSecurityProblemButton onOpen={() => setReporting(true)} />
      </div>
      <SecurityReportDialog open={reporting} onOpenChange={closeReport} />
      {isLoading ? (
        <SkeletonRegion>
          <Skeleton className="h-48 w-full" />
        </SkeletonRegion>
      ) : isError ? (
        <StatusMessage onRetry={refetch} />
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground text-sm">{t("tickets.empty")}</p>
      ) : (
        <Card className="overflow-hidden p-0">
          <ul className="divide-y">
            {items.map((ticket) => (
              <TicketRow key={ticket.task_id} ticket={ticket} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
};

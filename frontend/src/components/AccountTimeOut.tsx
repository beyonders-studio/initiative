import { Lock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { FilerState } from "@/api/generated/initiativeAPI.schemas";
import { getReadMyTimeOutQueryKey } from "@/api/generated/users/users";
import { TicketConversation } from "@/components/tickets/TicketConversation";
import { TicketStateBadge } from "@/components/tickets/TicketStateBadge";
import { useAccountTimeOut } from "@/hooks/useAccountTimeOut";
import { useAuth } from "@/hooks/useAuth";
import { useFiledTicket, useFileTicket } from "@/hooks/useTickets";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { queryClient } from "@/lib/queryClient";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { Textarea } from "@/ui/textarea";

/** Matches the column behind it, so the field stops where the server would. */
const BODY_MAX = 5000;

/** How often an appeal is read again. This screen stands in for the app, and
 *  with it the stream that would say the team answered. */
const APPEAL_POLL_MS = 30_000;

/** Asking for the suspension to be lifted, in their own words. */
const AppealDialog = ({
  open,
  onOpenChange,
  onNowhere,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Nothing took it: the screen falls back to the address. */
  onNowhere: () => void;
}) => {
  const { t } = useTranslation(["auth", "common"]);
  const [body, setBody] = useState("");
  const file = useFileTicket({
    onSuccess: () => {
      toast.success(t("timeOut.appealSent"));
      setBody("");
      onOpenChange(false);
      void queryClient.invalidateQueries({ queryKey: getReadMyTimeOutQueryKey() });
    },
    onError: (err) => {
      if (getHttpStatus(err) === 503) {
        onOpenChange(false);
        onNowhere();
        return;
      }
      toast.error(getErrorMessage(err, "auth:timeOut.appealError"));
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("timeOut.appealTitle")}</DialogTitle>
          <DialogDescription>{t("timeOut.appealDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="appeal-body">{t("timeOut.appealLabel")}</Label>
          <Textarea
            id="appeal-body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={6}
            maxLength={BODY_MAX}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            disabled={!body.trim() || file.isPending}
            onClick={() =>
              file.mutate({
                ticket: { stream: "moderation", type: "appeal", body: body.trim() },
                files: [],
              })
            }
          >
            {t("timeOut.appealSubmit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/** The appeal the account made, followed here: where it stands, and the
 *  conversation about it. */
const AppealThread = ({ taskId }: { taskId: number }) => {
  const { t } = useTranslation("auth");
  const { data: ticket } = useFiledTicket(taskId);
  if (!ticket) return null;
  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-sm">{t("timeOut.appealHeading")}</p>
        <TicketStateBadge state={ticket.state} />
      </div>
      <TicketConversation ticket={ticket} />
    </div>
  );
};

/**
 * The screen a suspended account meets in place of the app. It is in time out:
 * it reaches no community and changes nothing until the suspension is lifted,
 * and everything it had is kept for when it is. What it can do here is read
 * why, appeal — or, where appeals are not taken here, see whom to contact —
 * follow its appeal, and sign out.
 */
export const AccountTimeOut = () => {
  const { t } = useTranslation("auth");
  const { logout } = useAuth();
  const { data } = useAccountTimeOut();
  const [appealing, setAppealing] = useState(false);
  // Set when an appeal found nothing to take it after all.
  const [nowhere, setNowhere] = useState(false);
  const appealId = data?.appeal_task_id ?? null;
  const appeal = useFiledTicket(appealId ?? 0, {
    enabled: appealId != null,
    refetchInterval: APPEAL_POLL_MS,
  });
  // One appeal open at a time: another once the last is closed.
  const appealOpen = appealId != null && appeal.data?.state !== FilerState.closed;
  const canAppeal = Boolean(data?.can_appeal) && !nowhere && !appealOpen;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
            <Lock className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          </div>
          <CardTitle>{t("timeOut.title")}</CardTitle>
          <CardDescription>{t("timeOut.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {data?.reason ? (
            <p className="rounded-md bg-muted p-3 text-sm">
              {t("timeOut.reason", { reason: data.reason })}
            </p>
          ) : null}
          {canAppeal ? (
            <Button className="w-full" onClick={() => setAppealing(true)}>
              {appealId != null ? t("timeOut.appealAgain") : t("timeOut.appeal")}
            </Button>
          ) : !appealOpen ? (
            <p className="text-sm">
              {data?.contact_email
                ? t("timeOut.contact", { email: data.contact_email })
                : t("timeOut.contactNobody")}
            </p>
          ) : null}
          {appealId != null ? <AppealThread taskId={appealId} /> : null}
          <Button variant="outline" className="w-full" onClick={() => void logout()}>
            {t("timeOut.signOut")}
          </Button>
        </CardContent>
      </Card>
      <AppealDialog
        open={appealing}
        onOpenChange={setAppealing}
        onNowhere={() => setNowhere(true)}
      />
    </div>
  );
};

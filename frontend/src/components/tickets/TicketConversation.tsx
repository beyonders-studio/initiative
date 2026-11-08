/**
 * The conversation about a filed ticket, as its filer reads it: what they
 * said, what the team said to them, and their answer where the ticket takes
 * one.
 *
 * The people handling it are shown as the team, never by name, and only what
 * was said to the reader is here; the team's own notes are not.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Conversation,
  type FiledTicketDetailRead,
  FilerState,
  type TicketMessageRead,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentContent } from "@/components/comments/CommentContent";
import { EvidenceList, EvidencePicker, filedEvidenceUrl } from "@/components/tickets/Evidence";
import { useReplyToTicket } from "@/hooks/useTickets";
import { Button } from "@/ui/button";
import { Card, CardContent } from "@/ui/card";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { cn } from "@/ui/lib/utils";
import { Textarea } from "@/ui/textarea";

const Message = ({ message, taskId }: { message: TicketMessageRead; taskId: number }) => {
  const { t } = useTranslation("intake");
  const when = useRelativeTime(message.created_at);
  return (
    <li className={cn("flex", message.mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg border px-3 py-2",
          message.mine ? "border-primary/30 bg-primary/5" : "bg-muted/40"
        )}
      >
        <p className="mb-1 text-muted-foreground text-xs">
          {message.mine ? t("tickets.you") : t("tickets.team")} · {when}
        </p>
        <div className="text-sm">
          <CommentContent content={message.content} />
        </div>
        <EvidenceList
          className="mt-2"
          items={message.attachments ?? []}
          urlFor={(id) => filedEvidenceUrl(taskId, id)}
        />
      </div>
    </li>
  );
};

/** Why there is no box to answer in, where there is not one. */
const replyNote = (
  conversation: Conversation,
  state: FilerState
): "tickets.closedNote" | "tickets.noConversation" | "tickets.staffFirst" | null => {
  if (state === FilerState.closed) return "tickets.closedNote";
  if (conversation === Conversation.none) return "tickets.noConversation";
  if (conversation === Conversation.staff_first) return "tickets.staffFirst";
  return null;
};

/**
 * What has been said about a ticket, and the reader's answer where the ticket
 * takes one. The ticket's page draws it, and so does the time-out screen, for
 * an appeal.
 */
export const TicketConversation = ({ ticket }: { ticket: FiledTicketDetailRead }) => {
  const { t } = useTranslation(["intake", "common"]);
  const taskId = ticket.task_id;
  const [reply, setReply] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const replyMutation = useReplyToTicket(taskId, {
    onSuccess: () => {
      setReply("");
      setFiles([]);
    },
  });
  const note = ticket.can_reply ? null : replyNote(ticket.conversation, ticket.state);
  return (
    <>
      <ul className="space-y-3">
        {ticket.messages.map((message) => (
          <Message key={message.id} message={message} taskId={taskId} />
        ))}
      </ul>

      {ticket.can_reply ? (
        <Card>
          <CardContent className="space-y-3 pt-6">
            <Textarea
              value={reply}
              onChange={(event) => setReply(event.target.value)}
              placeholder={t("tickets.replyPlaceholder")}
              aria-label={t("tickets.replyLabel")}
              rows={4}
              disabled={replyMutation.isPending}
            />
            <EvidencePicker
              policy={ticket.evidence}
              files={files}
              onChange={setFiles}
              disabled={replyMutation.isPending}
            />
            <div className="flex justify-end">
              <Button
                type="button"
                disabled={replyMutation.isPending || !reply.trim()}
                onClick={() => replyMutation.mutate({ body: reply.trim(), files })}
              >
                {replyMutation.isPending ? t("tickets.sending") : t("tickets.send")}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : note ? (
        <p className="text-muted-foreground text-sm">{t(note)}</p>
      ) : null}
    </>
  );
};

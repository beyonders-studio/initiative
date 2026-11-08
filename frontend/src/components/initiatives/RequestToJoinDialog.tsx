/**
 * Knock on an initiative that admits people by request.
 *
 * The note is optional and short — a sentence for whoever reads the queue, not
 * a cover letter — and nothing about what the requester can see changes until a
 * manager answers. Sending only creates the row; the card behind this dialog
 * flips to "requested" when the directory re-reads.
 */

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useRequestToJoinInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/mascotToast";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Textarea } from "@/ui/textarea";

/** Mirrors `JOIN_REQUEST_MESSAGE_MAX_LENGTH` in the backend's initiative
 *  schemas, which is the authority — this only stops the typing early so a
 *  request is never composed and then refused. */
export const JOIN_REQUEST_MESSAGE_MAX_LENGTH = 1000;

export interface RequestToJoinDialogProps extends DialogProps {
  /** The initiative being asked about; `null` when nothing is being asked. */
  initiative: { id: number; name: string } | null;
}

export const RequestToJoinDialog = ({
  initiative,
  open,
  onOpenChange,
}: RequestToJoinDialogProps) => {
  const { t } = useTranslation("initiatives");
  const [message, setMessage] = useState("");

  // Reset on close, however it was closed — reopening starts a fresh note.
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (!open) {
      setMessage("");
    }
  }

  const requestToJoin = useRequestToJoinInitiative({
    onSuccess: () => {
      toast.success(t("joinRequests.requested", { name: initiative?.name ?? "" }));
      onOpenChange(false);
    },
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!initiative) {
      return;
    }
    const trimmed = message.trim();
    requestToJoin.mutate({
      initiativeId: initiative.id,
      data: { message: trimmed || null },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card">
        <DialogHeader>
          <DialogTitle>
            {t("joinRequests.dialogTitle", { name: initiative?.name ?? "" })}
          </DialogTitle>
          <DialogDescription>{t("joinRequests.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <Field label={t("joinRequests.messageLabel")} hint={t("joinRequests.messageHint")}>
            <Textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={t("joinRequests.messagePlaceholder")}
              maxLength={JOIN_REQUEST_MESSAGE_MAX_LENGTH}
              rows={3}
              disabled={requestToJoin.isPending}
            />
          </Field>
          <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button type="submit" disabled={!initiative} pending={requestToJoin.isPending}>
              {requestToJoin.isPending ? t("joinRequests.sending") : t("joinRequests.send")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

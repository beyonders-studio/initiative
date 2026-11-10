/**
 * Knock on an initiative or a community that admits people by request.
 *
 * The note is optional and short — a sentence for whoever reads the queue, not
 * a cover letter — and nothing about what the requester can see changes until
 * somebody answers. Sending only creates the row; the card behind this dialog
 * flips to "requested" when its directory re-reads. The caller sends it, so
 * each directory keeps its own request and its own words.
 */

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

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

/** Mirrors the backend's limit on a request's note, which is the authority —
 *  this only stops the typing early so a request is never composed and then
 *  refused. */
const JOIN_REQUEST_MESSAGE_MAX_LENGTH = 1000;

export interface RequestToJoinDialogProps extends DialogProps {
  title: string;
  description: string;
  /** Under the note: what it is for, to whoever reads it. */
  hint: string;
  pending: boolean;
  /** Sends the request, with the note trimmed, or `null` when there is none. */
  onSend: (message: string | null) => void;
}

export const RequestToJoinDialog = ({
  title,
  description,
  hint,
  pending,
  onSend,
  open,
  onOpenChange,
}: RequestToJoinDialogProps) => {
  const { t } = useTranslation("common");
  const [message, setMessage] = useState("");

  // Reset on close, however it was closed — reopening starts a fresh note.
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (!open) {
      setMessage("");
    }
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSend(message.trim() || null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <Field label={t("joinRequests.messageLabel")} hint={hint}>
            <Textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={t("joinRequests.messagePlaceholder")}
              maxLength={JOIN_REQUEST_MESSAGE_MAX_LENGTH}
              rows={3}
              disabled={pending}
            />
          </Field>
          <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button type="submit" pending={pending}>
              {pending ? t("joinRequests.sending") : t("joinRequests.send")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

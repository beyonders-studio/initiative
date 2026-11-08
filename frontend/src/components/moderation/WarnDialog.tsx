/**
 * Warning whoever wrote something, in the moderator's own words.
 *
 * What is typed here is sent to them as it is. It never says who reported
 * the thing, or how many people did.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

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

/** Matches the column behind it. */
const MESSAGE_MAX = 2000;

export interface WarnDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pending?: boolean;
  onConfirm: (message: string) => void;
}

export const WarnDialog = ({ open, onOpenChange, pending = false, onConfirm }: WarnDialogProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [message, setMessage] = useState("");

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) setMessage("");
  }

  const said = message.trim();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("warn.title")}</DialogTitle>
          <DialogDescription>{t("warn.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="warning-message">{t("warn.messageLabel")}</Label>
          <Textarea
            id="warning-message"
            value={message}
            maxLength={MESSAGE_MAX}
            rows={4}
            placeholder={t("warn.messagePlaceholder")}
            onChange={(e) => setMessage(e.target.value)}
          />
        </div>
        <DialogFooter
          submitLabel={t("warn.submit")}
          onSubmit={() => onConfirm(said)}
          pending={pending}
          disabled={!said}
        />
      </DialogContent>
    </Dialog>
  );
};

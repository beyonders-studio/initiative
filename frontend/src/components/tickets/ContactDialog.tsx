/**
 * Who to write to, where there is no form.
 *
 * What a filing surface shows when the deployment has nothing set up to
 * receive that kind of ticket — or the reader may not file one from where they
 * are — but has said who to contact. An address and a way to use it, and
 * nothing to fill in.
 */

import { Mail } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { CopyButton } from "@/ui/copy-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";

export interface ContactDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The address to write to. */
  contact: string;
  /** What the reader already wrote, where a filing could not be received: it
   *  goes into the email, and can be copied, so nothing is written twice. */
  draft?: { subject: string; body: string };
}

/** A `mailto:` for the address, carrying the draft where there is one. */
const mailtoFor = (contact: string, draft?: { subject: string; body: string }): string => {
  const params = new URLSearchParams();
  if (draft?.subject) params.set("subject", draft.subject);
  if (draft?.body) params.set("body", draft.body);
  // URLSearchParams writes spaces as "+", which mail clients show literally.
  const query = params.toString().replace(/\+/g, "%20");
  return `mailto:${contact}${query ? `?${query}` : ""}`;
};

export const ContactDialog = ({ open, onOpenChange, contact, draft }: ContactDialogProps) => {
  const { t } = useTranslation(["intake", "common"]);
  const written = draft ? [draft.subject, draft.body].filter(Boolean).join("\n\n") : "";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("contact.title")}</DialogTitle>
          <DialogDescription>{t("contact.description")}</DialogDescription>
        </DialogHeader>
        <p className="break-all font-medium text-sm">{contact}</p>
        {written && (
          <p className="whitespace-pre-wrap rounded-md border p-3 text-muted-foreground text-sm">
            {written}
          </p>
        )}
        <DialogFooter>
          {written && <CopyButton value={written} label={t("contact.copyDraft")} />}
          <CopyButton value={contact} label={t("contact.copy")} />
          <Button asChild>
            <a href={mailtoFor(contact, draft)}>
              <Mail className="h-4 w-4" aria-hidden="true" />
              {t("contact.write")}
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

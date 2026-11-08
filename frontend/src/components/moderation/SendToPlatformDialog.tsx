/**
 * Handing a report to whoever runs the server, from its card.
 *
 * One question a community moderator can answer: while the platform looks,
 * should this stay up, or disappear? Disappearing holds it where it is —
 * hidden from everyone, them included, and preserved exactly as it is — which
 * is what a legal request to keep something, or something that may be
 * illegal, needs. Either way the report closes as handed over.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  HoldReason,
  type ModerationReportRead,
  ReportOutcome,
  ReportReason,
  type ReportSettle,
} from "@/api/generated/initiativeAPI.schemas";
import {
  emptyHoldWhy,
  HoldFields,
  holdWhyBody,
  holdWhyReady,
} from "@/components/moderation/HoldFields";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

type Choice = "leave" | "hide";

export interface SendToPlatformDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  report: ModerationReportRead;
  /** What the moderator wrote on the card. */
  note: string;
  sending: boolean;
  onSend: (body: ReportSettle) => void;
}

export const SendToPlatformDialog = ({
  open,
  onOpenChange,
  report,
  note,
  sending,
  onSend,
}: SendToPlatformDialogProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const illegal = report.reason === ReportReason.illegal;
  // A report of something illegal is hidden unless the moderator says
  // otherwise: it must stop being seen, and must not be destroyed.
  const [choice, setChoice] = useState<Choice>(illegal ? "hide" : "leave");
  const [why, setWhy] = useState(() =>
    emptyHoldWhy(illegal ? HoldReason.illegal_content : HoldReason.legal_request)
  );
  const hiding = choice === "hide";
  const trimmed = note.trim() || null;

  const send = () =>
    onSend(
      hiding
        ? { outcome: ReportOutcome.held, note: trimmed, hold: holdWhyBody(why) }
        : { outcome: ReportOutcome.escalated, note: trimmed }
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("sendToPlatform.title")}</DialogTitle>
          <DialogDescription>{t("sendToPlatform.description")}</DialogDescription>
        </DialogHeader>
        <RadioGroup
          value={choice}
          onValueChange={(value) => setChoice(value as Choice)}
          className="gap-3"
          aria-label={t("sendToPlatform.question")}
        >
          <div className="flex items-start gap-3 rounded-md border p-3">
            <RadioGroupItem value="leave" id="send-leave" className="mt-1" />
            <div className="space-y-0.5">
              <Label htmlFor="send-leave" className="font-medium">
                {t("sendToPlatform.leaveLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t("sendToPlatform.leaveDescription")}
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-md border p-3">
            <RadioGroupItem value="hide" id="send-hide" className="mt-1" />
            <div className="space-y-0.5">
              <Label htmlFor="send-hide" className="font-medium">
                {t("sendToPlatform.hideLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">{t("sendToPlatform.hideDescription")}</p>
            </div>
          </div>
        </RadioGroup>
        {hiding ? <HoldFields value={why} onChange={setWhy} idPrefix="send-hold" /> : null}
        <DialogFooter
          submitLabel={hiding ? t("sendToPlatform.hideSubmit") : t("sendToPlatform.leaveSubmit")}
          onSubmit={send}
          pending={sending}
          disabled={hiding && !holdWhyReady(why)}
          destructive={hiding}
        />
      </DialogContent>
    </Dialog>
  );
};

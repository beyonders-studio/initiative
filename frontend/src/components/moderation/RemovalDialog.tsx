/**
 * Taking something down, as a moderator: why, and a note for the log.
 *
 * The reason is what its author is told, and what a comment's tombstone says
 * where the comment was; the note stays with the moderators. Used from a
 * thing's own moderation menu and from a report card, which pre-fills the
 * reason it was reported for.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  RemovalReason,
  type RemovalReason as RemovalReasonValue,
} from "@/api/generated/initiativeAPI.schemas";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Textarea } from "@/ui/textarea";

/** Matches the column behind it. */
const NOTE_MAX = 2000;

/** The reasons, in the order a moderator usually reaches for them. */
export const REMOVAL_REASONS: RemovalReasonValue[] = [
  RemovalReason.spam,
  RemovalReason.harassment,
  RemovalReason.hate,
  RemovalReason.off_topic,
  RemovalReason.community_rule,
  RemovalReason.misinformation,
  RemovalReason.sexual_content,
  RemovalReason.violence,
  RemovalReason.self_harm,
  RemovalReason.illegal,
  RemovalReason.other,
];

export interface Removal {
  reason: RemovalReasonValue;
  note: string | null;
}

export interface RemovalDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What the thing is, for the title: a `SearchEntityType` value. */
  targetType: string;
  /** The reason to start from — a report's own, say. */
  initialReason?: RemovalReasonValue | null;
  /** The note to start from. */
  initialNote?: string;
  pending?: boolean;
  onConfirm: (removal: Removal) => void;
}

export const RemovalDialog = ({ open, onOpenChange, ...props }: RemovalDialogProps) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent>
      <RemovalForm {...props} />
    </DialogContent>
  </Dialog>
);

// Drawn only while the dialog is open, so each opening starts from what the
// caller knows, not from last time.
const RemovalForm = ({
  targetType,
  initialReason = null,
  initialNote = "",
  pending = false,
  onConfirm,
}: Omit<RemovalDialogProps, "open" | "onOpenChange">) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [reason, setReason] = useState<RemovalReasonValue | "">(initialReason ?? "");
  const [note, setNote] = useState(initialNote);

  const comment = targetType === "comment";

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("remove.title")}</DialogTitle>
        <DialogDescription>
          {comment ? t("remove.commentDescription") : t("remove.description")}
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="removal-reason">{t("remove.reasonLabel")}</Label>
          <Select value={reason} onValueChange={(v) => setReason(v as RemovalReasonValue)}>
            <SelectTrigger id="removal-reason">
              <SelectValue placeholder={t("remove.reasonPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {REMOVAL_REASONS.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`removalReasons.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">{t("remove.reasonHelp")}</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="removal-note">{t("remove.noteLabel")}</Label>
          <Textarea
            id="removal-note"
            value={note}
            maxLength={NOTE_MAX}
            rows={2}
            placeholder={t("remove.notePlaceholder")}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      </div>
      <DialogFooter
        submitLabel={t("remove.submit")}
        onSubmit={() => {
          if (reason !== "") onConfirm({ reason, note: note.trim() || null });
        }}
        pending={pending}
        disabled={reason === ""}
        destructive
      />
    </>
  );
};

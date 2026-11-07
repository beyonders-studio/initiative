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
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

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

export const RemovalDialog = ({
  open,
  onOpenChange,
  targetType,
  initialReason = null,
  initialNote = "",
  pending = false,
  onConfirm,
}: RemovalDialogProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [reason, setReason] = useState<RemovalReasonValue | "">(initialReason ?? "");
  const [note, setNote] = useState(initialNote);

  // Each opening starts from what the caller knows, not from last time.
  const [prev, setPrev] = useState({ open, initialReason, initialNote });
  if (
    prev.open !== open ||
    prev.initialReason !== initialReason ||
    prev.initialNote !== initialNote
  ) {
    setPrev({ open, initialReason, initialNote });
    if (open) {
      setReason(initialReason ?? "");
      setNote(initialNote);
    }
  }

  const comment = targetType === "comment";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
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
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={reason === "" || pending}
            onClick={() => {
              if (reason !== "") onConfirm({ reason, note: note.trim() || null });
            }}
          >
            {t("remove.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

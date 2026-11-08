/**
 * Holding something for the platform.
 *
 * The content is kept exactly as it is, out of the whole community's sight,
 * until the platform releases it. A platform moderator under a `moderate`
 * grant holds it from the operations case working it (`caseTaskId`); a
 * community's own moderators hold it from its moderation menu, which opens a
 * case of its own — and from then on they can't see it either, which the
 * dialog says before they confirm. From a report card, they hand it over
 * hidden instead (`SendToPlatformDialog`).
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  emptyHoldWhy,
  HoldFields,
  holdWhyBody,
  holdWhyReady,
} from "@/components/moderation/HoldFields";
import { usePlaceHold } from "@/hooks/useHolds";
import { toast } from "@/lib/mascotToast";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";

export interface HoldDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The community the content is in. */
  communityId: number;
  /** A `SearchEntityType` value, and the id. */
  targetType: string;
  targetId: number;
  /** The operations case it is held under. */
  caseTaskId?: number;
  onHeld?: () => void;
}

export const HoldDialog = ({
  open,
  onOpenChange,
  communityId,
  targetType,
  targetId,
  caseTaskId,
  onHeld,
}: HoldDialogProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [why, setWhy] = useState(emptyHoldWhy);

  const place = usePlaceHold(communityId, {
    onSuccess: () => {
      toast.success(t("hold.held"));
      onOpenChange(false);
      setWhy(emptyHoldWhy());
      onHeld?.();
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("hold.title")}</DialogTitle>
          <DialogDescription>{t("hold.description")}</DialogDescription>
        </DialogHeader>
        {caseTaskId == null && (
          <p className="font-medium text-destructive text-sm">{t("hold.communityWarning")}</p>
        )}
        <HoldFields value={why} onChange={setWhy} />
        <DialogFooter
          submitLabel={t("hold.submit")}
          onSubmit={() =>
            place.mutate({
              target_type: targetType,
              target_id: targetId,
              ...holdWhyBody(why),
              case_task_id: caseTaskId ?? null,
            })
          }
          pending={place.isPending}
          disabled={!holdWhyReady(why)}
          destructive
        />
      </DialogContent>
    </Dialog>
  );
};

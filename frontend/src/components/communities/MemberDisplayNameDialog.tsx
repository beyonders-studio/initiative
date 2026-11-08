import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useSetMemberDisplayName } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import type { DialogProps } from "@/types/dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

/** The longest name the server takes (`MEMBER_DISPLAY_NAME_MAX_LENGTH`). */
const MAX_LENGTH = 64;

interface MemberDisplayNameDialogProps extends DialogProps {
  communityId: number;
  /** The member an administrator is naming; left out, the caller names themselves. */
  member?: { id: number; name: string };
  /** The name as it is set now, or null when none is. */
  current: string | null | undefined;
}

/**
 * What somebody is called in one community. Empty clears it, and their
 * handle shows again.
 */
export const MemberDisplayNameDialog = ({
  communityId,
  member,
  current,
  open,
  onOpenChange,
}: MemberDisplayNameDialogProps) => {
  const { t } = useTranslation(["communities", "common"]);
  const [value, setValue] = useState(current ?? "");
  const setDisplayName = useSetMemberDisplayName({
    onSuccess: () => {
      toast.success(t("displayName.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(getErrorMessage(error, "communities:displayName.saveFailed")),
  });

  const [prev, setPrev] = useState({ open, current });
  if (prev.open !== open || prev.current !== current) {
    setPrev({ open, current });
    if (open) setValue(current ?? "");
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setDisplayName.mutate({
      communityId,
      userId: member?.id,
      displayName: value.trim() || null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {member
              ? t("displayName.memberTitle", { name: member.name })
              : t("displayName.ownTitle")}
          </DialogTitle>
          <DialogDescription>
            {member ? t("displayName.memberDescription") : t("displayName.ownDescription")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="member-display-name">{t("displayName.label")}</Label>
            <Input
              id="member-display-name"
              value={value}
              maxLength={MAX_LENGTH}
              onChange={(event) => setValue(event.target.value)}
              autoFocus
            />
          </div>
          <DialogFooter submitLabel={t("common:save")} pending={setDisplayName.isPending} />
        </form>
      </DialogContent>
    </Dialog>
  );
};

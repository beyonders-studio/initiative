/**
 * Confirming that someone should lose their place in an initiative.
 *
 * Removing the membership row removes the access it granted, including the
 * explicit shares that hung off it, so the confirmation says so before it
 * happens. Lives with the members section, which is the only place that opens it.
 */

import { Trans, useTranslation } from "react-i18next";

import type { InitiativeMemberRead } from "@/api/generated/initiativeAPI.schemas";
import { useRemoveInitiativeMember } from "@/hooks/useInitiatives";
import { toast } from "@/lib/mascotToast";
import { getUserDisplayName } from "@/lib/userDisplay";
import { ConfirmDialog } from "@/ui/confirm-dialog";

export interface RemoveInitiativeMemberDialogProps {
  initiativeId: number;
  /** The member being removed; `null` when nobody is. */
  member: InitiativeMemberRead | null;
  onOpenChange: (member: InitiativeMemberRead | null) => void;
}

export const RemoveInitiativeMemberDialog = ({
  initiativeId,
  member,
  onOpenChange,
}: RemoveInitiativeMemberDialogProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  const removeMember = useRemoveInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.memberRemoved"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.removeMemberError");
      toast.error(message);
    },
  });

  return (
    <ConfirmDialog
      open={!!member}
      onOpenChange={(open) => !open && onOpenChange(null)}
      title={t("settings.removeMemberTitle")}
      description={
        <>
          <span className="block">
            <Trans
              i18nKey="settings.removeMemberDescription"
              ns="initiatives"
              values={{ name: getUserDisplayName(member?.user) }}
              components={{ bold: <strong /> }}
            />
          </span>
          <span className="mt-2 block text-destructive">{t("settings.removeMemberWarning")}</span>
        </>
      }
      confirmLabel={t("settings.removeMember")}
      loadingLabel={t("settings.removing")}
      isLoading={removeMember.isPending}
      destructive
      onConfirm={() => {
        if (member) {
          removeMember.mutate(
            { initiativeId, userId: member.user.id },
            { onSuccess: () => onOpenChange(null) }
          );
        }
      }}
    />
  );
};

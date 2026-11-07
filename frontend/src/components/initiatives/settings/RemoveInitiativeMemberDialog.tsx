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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/ui/alert-dialog";

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
    <AlertDialog open={!!member} onOpenChange={(open) => !open && onOpenChange(null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("settings.removeMemberTitle")}</AlertDialogTitle>
          <AlertDialogDescription className="space-y-2">
            <span className="block">
              <Trans
                i18nKey="settings.removeMemberDescription"
                ns="initiatives"
                values={{ name: getUserDisplayName(member?.user) }}
                components={{ bold: <strong /> }}
              />
            </span>
            <span className="block text-destructive">{t("settings.removeMemberWarning")}</span>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={removeMember.isPending}>
            {t("common:cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              if (member) {
                removeMember.mutate(
                  { initiativeId, userId: member.user.id },
                  { onSuccess: () => onOpenChange(null) }
                );
              }
            }}
            disabled={removeMember.isPending}
            className="bg-destructive text-white hover:bg-destructive/90"
          >
            {removeMember.isPending ? t("settings.removing") : t("settings.removeMember")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

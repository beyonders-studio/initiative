import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { removeMember } from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import { toast } from "@/lib/mascotToast";
import { Checkbox } from "@/ui/checkbox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { Label } from "@/ui/label";

interface RemoveCommunityMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  userId: number | null;
  email: string;
  onSuccess?: () => void;
}

/**
 * Community-admin counterpart to ``LeaveCommunityDialog``, and just as plain: removing
 * someone ends their memberships and the access those carried.
 *
 * It asks nothing about their content because nothing has to be decided here.
 * Ownership is released as they go, and what they owned turns up in community
 * settings under unowned content for an admin to claim whenever they like.
 *
 * Banning is removing and keeping them out, so it is asked here rather than
 * offered as a second way to do the same removal.
 */
export const RemoveCommunityMemberDialog = ({
  open,
  onOpenChange,
  userId,
  email,
  onSuccess,
}: RemoveCommunityMemberDialogProps) => {
  const { t } = useTranslation(["communities", "common"]);
  const { refreshCommunities } = useCommunities();
  const banId = useId();
  const [ban, setBan] = useState(false);
  const remove = useCommunityMutation(
    {
      mutationFn: (communityId, member: { id: number; ban: boolean }) =>
        removeMember(communityId, member.id, member.ban ? { ban: true } : undefined),
      invalidate: () => {
        void invalidate(q.communityMembers());
        // The community entry carries member_count, which the invite surfaces read
        // to tell a full community from one with a seat free. It is provider state,
        // not a query, so it refreshes rather than invalidates.
        void refreshCommunities();
      },
      errorKey: "communities:removeMember.failedToRemove",
    },
    {
      onSuccess: (_data, member) => {
        toast.success(
          member.ban ? t("removeMember.banned", { email }) : t("removeMember.removed", { email })
        );
        onSuccess?.();
        onOpenChange(false);
      },
    }
  );

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setBan(false);
        onOpenChange(next);
      }}
      title={t("removeMember.title")}
      description={t("removeMember.description", { email })}
      confirmLabel={ban ? t("removeMember.banButton") : t("removeMember.removeButton")}
      loadingLabel={t("removeMember.removing")}
      isLoading={remove.isPending}
      destructive
      onConfirm={(event) => {
        // Stays open until it is done, so a failure keeps the ban box as set.
        event.preventDefault();
        if (userId !== null) remove.mutate({ id: userId, ban });
      }}
    >
      <p className="text-muted-foreground text-sm">{t("removeMember.ownershipReleased")}</p>
      <div className="flex items-start gap-2">
        <Checkbox
          id={banId}
          checked={ban}
          onCheckedChange={(checked) => setBan(checked === true)}
          className="mt-0.5"
        />
        <div className="space-y-0.5">
          <Label htmlFor={banId}>{t("removeMember.ban")}</Label>
          <p className="text-muted-foreground text-sm">{t("removeMember.banHint")}</p>
        </div>
      </div>
    </ConfirmDialog>
  );
};

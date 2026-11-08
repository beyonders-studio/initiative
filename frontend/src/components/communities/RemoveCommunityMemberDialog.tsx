import { useTranslation } from "react-i18next";

import { removeMember } from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import { toast } from "@/lib/mascotToast";
import { ConfirmDialog } from "@/ui/confirm-dialog";

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
  const remove = useCommunityMutation(
    {
      mutationFn: (communityId, memberId: number) => removeMember(communityId, memberId),
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
      onSuccess: () => {
        toast.success(t("removeMember.removed", { email }));
        onSuccess?.();
        onOpenChange(false);
      },
    }
  );

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("removeMember.title")}
      description={t("removeMember.description", { email })}
      confirmLabel={t("removeMember.removeButton")}
      loadingLabel={t("removeMember.removing")}
      isLoading={remove.isPending}
      destructive
      onConfirm={() => {
        if (userId !== null) remove.mutate(userId);
      }}
    >
      <p className="text-muted-foreground text-sm">{t("removeMember.ownershipReleased")}</p>
    </ConfirmDialog>
  );
};

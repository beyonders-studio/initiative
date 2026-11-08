import { useState } from "react";
import { useTranslation } from "react-i18next";

import { removeMember } from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
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
  const communityId = useActiveCommunityId();
  const { refreshCommunities } = useCommunities();
  const [removing, setRemoving] = useState(false);

  const handleRemove = async () => {
    if (userId === null) return;
    setRemoving(true);
    try {
      await removeMember(communityId, userId);
      void invalidate(q.communityMembers());
      // The community entry carries member_count, which the invite surfaces read
      // to tell a full community from one with a seat free. It is provider state,
      // not a query, so it refreshes rather than invalidates.
      void refreshCommunities();
      toast.success(t("removeMember.removed", { email }));
      onSuccess?.();
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to remove member", err);
      toast.error(getErrorMessage(err, "communities:removeMember.failedToRemove"));
    } finally {
      setRemoving(false);
    }
  };

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("removeMember.title")}
      description={t("removeMember.description", { email })}
      confirmLabel={t("removeMember.removeButton")}
      loadingLabel={t("removeMember.removing")}
      isLoading={removing}
      destructive
      onConfirm={handleRemove}
    >
      <p className="text-muted-foreground text-sm">{t("removeMember.ownershipReleased")}</p>
    </ConfirmDialog>
  );
};

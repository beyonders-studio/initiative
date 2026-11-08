import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { removeMember } from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
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
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("removeMember.title")}</AlertDialogTitle>
        </AlertDialogHeader>
        <div className="space-y-3">
          <AlertDialogDescription>
            {t("removeMember.description", { email })}
          </AlertDialogDescription>
          <p className="text-muted-foreground text-sm">{t("removeMember.ownershipReleased")}</p>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={removing}>{t("common:cancel")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleRemove}
            disabled={removing}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {removing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("removeMember.removing")}
              </>
            ) : (
              t("removeMember.removeButton")
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

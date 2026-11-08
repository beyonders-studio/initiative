import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { checkLeaveEligibility, leaveCommunity } from "@/api/generated/communities/communities";
import type {
  CommunityRead,
  LeaveCommunityEligibilityResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { useCommunities } from "@/hooks/useCommunities";
import { toast } from "@/lib/mascotToast";
import type { DialogProps } from "@/types/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/ui/alert";
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

interface LeaveCommunityDialogProps extends DialogProps {
  community: CommunityRead;
}

/**
 * Holding the community's only superadmin seat is the one thing that stops
 * someone leaving. Content they own is released on the way out — left unowned
 * for a community admin to claim from community settings — so there is nothing to hand
 * over first.
 */
export const LeaveCommunityDialog = ({
  community,
  open,
  onOpenChange,
}: LeaveCommunityDialogProps) => {
  const { t } = useTranslation(["communities", "common"]);
  const { communities, refreshCommunities, switchCommunity, activeCommunityId } = useCommunities();
  const [loading, setLoading] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const [eligibility, setEligibility] = useState<LeaveCommunityEligibilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setEligibility(null);
      setError(null);
      setLoading(true);
      return;
    }

    const checkEligibility = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = (await checkLeaveEligibility(
          community.id
        )) as unknown as LeaveCommunityEligibilityResponse;
        setEligibility(data);
      } catch (err) {
        console.error("Failed to check leave eligibility", err);
        setError(t("leave.failedToCheckEligibility"));
      } finally {
        setLoading(false);
      }
    };

    void checkEligibility();
  }, [open, community.id, t]);

  const hasHardBlocker = !!eligibility && eligibility.is_last_superadmin;

  const handleLeave = async () => {
    setLeaving(true);
    try {
      await leaveCommunity(community.id);

      // Switch to another community if leaving the active one
      if (activeCommunityId === community.id) {
        const otherCommunity = communities.find((g) => g.id !== community.id);
        if (otherCommunity) {
          await switchCommunity(otherCommunity.id);
        }
      }

      await refreshCommunities();
      toast.success(t("leave.leftCommunity", { name: community.name }));
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to leave community", err);
      toast.error(t("leave.failedToLeave"));
    } finally {
      setLeaving(false);
    }
  };

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      );
    }

    if (error) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t("common:error")}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      );
    }

    if (!eligibility) {
      return null;
    }

    if (hasHardBlocker) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t("leave.cannotLeaveTitle")}</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-inside list-disc space-y-1">
              <li>{t("leave.lastSuperadminWarning")}</li>
            </ul>
          </AlertDescription>
        </Alert>
      );
    }

    return (
      <div className="space-y-3">
        <AlertDialogDescription>
          <Trans
            i18nKey="leave.description"
            ns="communities"
            values={{ name: community.name }}
            components={{ bold: <strong /> }}
          />
        </AlertDialogDescription>
        <p className="text-muted-foreground text-sm">{t("leave.ownershipReleased")}</p>
      </div>
    );
  };

  const canShowLeaveButton = !loading && !error && eligibility && !hasHardBlocker;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("leave.title", { name: community.name })}</AlertDialogTitle>
        </AlertDialogHeader>
        {renderContent()}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={leaving}>{t("common:cancel")}</AlertDialogCancel>
          {canShowLeaveButton && (
            <AlertDialogAction
              onClick={handleLeave}
              disabled={leaving}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {leaving ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("leave.leaving")}
                </>
              ) : (
                t("leave.leaveButton")
              )}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

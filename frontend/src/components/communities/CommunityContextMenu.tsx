import { useRouter } from "@tanstack/react-router";
import {
  Copy,
  CreditCard,
  GripVertical,
  LogOut,
  Plus,
  Settings,
  UserPlus,
  Users,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { createCommunityInvite } from "@/api/generated/communities/communities";
import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { InitiativeMark } from "@/components/icons/InitiativeMark";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { holdsBillingSeat } from "@/lib/billingSummary";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

import { LeaveCommunityDialog } from "./LeaveCommunityDialog";

interface CommunityContextMenuProps {
  community: CommunityRead;
  children: ReactNode;
  /**
   * When provided, the menu offers a "Reorder communities" action. Touch devices
   * have no drag affordance of their own (press-and-hold belongs to this
   * menu), so this is the way in to reorder mode there.
   */
  onReorder?: () => void;
}

export const CommunityContextMenu = ({
  community,
  children,
  onReorder,
}: CommunityContextMenuProps) => {
  const router = useRouter();
  const { t } = useTranslation(["communities", "nav"]);
  const { switchCommunity, activeCommunityId } = useCommunities();
  const { canSell, openPortal } = useBillingPortal();
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);

  // A suspended community offers nothing to open, and its membership cannot
  // change until the platform lifts the suspension.
  const closed = !community.can.enter;
  // What the reader runs here, a custom role included: asked when the menu
  // opens, rather than for every community in the list.
  const [menuOpen, setMenuOpen] = useState(false);
  const held = useHeldSurfaces(community, { enabled: menuOpen && !closed });
  const runsAnyPart = community.can.administer || held.holdsAny;
  const [creatingInvite, setCreatingInvite] = useState(false);
  // A community at its seat cap mints no invite (the server refuses), so the item
  // says so rather than handing back an error toast. Both fields are
  // admin-only on the payload, and null max_users means uncapped.
  const atUserLimit = community.max_users != null && community.member_count >= community.max_users;
  // Where a billing portal exists the cap travels with the plan, so a full
  // community leads there — for the seat, which is who the portal answers. An
  // ordinary admin, or anyone where nothing may be sold, sees the plain
  // "community is full" wording instead.
  const upgradeForSeats = atUserLimit && canSell && community.can.seat;

  const handleInviteMembers = async () => {
    if (creatingInvite || atUserLimit) return;
    setCreatingInvite(true);
    try {
      const data = await createCommunityInvite(community.id, {});
      void invalidate(q.communityInvites(community.id));
      const inviteLink = `${window.location.origin}/invite/${data.code}`;
      await navigator.clipboard.writeText(inviteLink);
      toast.success(t("inviteLinkCopied"));
    } catch (err) {
      console.error("Failed to create invite", err);
      toast.error(getErrorMessage(err, "communities:failedToCreateInvite"));
    } finally {
      setCreatingInvite(false);
    }
  };

  const handleViewMembers = async () => {
    if (community.id !== activeCommunityId) {
      await switchCommunity(community.id);
    }
    router.navigate({
      to: "/c/$communityId/members",
      params: { communityId: String(community.id) },
    });
  };

  const handleViewInitiatives = async () => {
    if (community.id !== activeCommunityId) {
      await switchCommunity(community.id);
    }
    router.navigate({ to: "/c/$communityId", params: { communityId: String(community.id) } });
  };

  const handleCommunitySettings = async () => {
    // Switch to this community first if not active, then navigate to settings
    if (community.id !== activeCommunityId) {
      await switchCommunity(community.id);
    }
    router.navigate({
      to: "/c/$communityId/settings",
      params: { communityId: String(community.id) },
    });
  };

  const handleCreateInitiative = async () => {
    // Switch to this community first if not active; the community home holds the
    // initiatives list, and `create` opens its create dialog on arrival.
    if (community.id !== activeCommunityId) {
      await switchCommunity(community.id);
    }
    router.navigate({
      to: "/c/$communityId",
      params: { communityId: String(community.id) },
      search: { create: "true" },
    });
  };

  const inviteLabel = upgradeForSeats
    ? t("inviteMembersUpgrade")
    : atUserLimit
      ? t("inviteMembersCommunityFull")
      : t("inviteMembers");

  const handleCopyCommunityId = () => {
    navigator.clipboard.writeText(String(community.id));
    toast.success(t("communityIdCopied"));
  };

  return (
    <>
      <ContextMenu onOpenChange={setMenuOpen}>
        <ContextMenuTrigger>{children}</ContextMenuTrigger>
        <ContextMenuContent className="w-48">
          <ContextMenuLabel className="truncate">{community.name}</ContextMenuLabel>
          {closed ? null : (
            <>
              <ContextMenuSeparator />
              <ContextMenuItem onClick={handleViewInitiatives}>
                <InitiativeMark className="mr-2 h-4 w-4" />
                {t("viewInitiatives")}
              </ContextMenuItem>
              <ContextMenuItem onClick={handleViewMembers}>
                <Users className="mr-2 h-4 w-4" />
                {t("viewMembers")}
              </ContextMenuItem>
            </>
          )}
          {runsAnyPart && !closed && (
            <>
              <ContextMenuSeparator />
              {held.writes && held.holds("invites") && (
                <ContextMenuItem
                  onClick={
                    upgradeForSeats
                      ? () => void openPortal(community.id, "upgrade")
                      : handleInviteMembers
                  }
                  disabled={creatingInvite || (atUserLimit && !upgradeForSeats)}
                >
                  <UserPlus className="mr-2 h-4 w-4" />
                  {creatingInvite ? t("creatingInvite") : inviteLabel}
                </ContextMenuItem>
              )}
              {community.can.administer_content && (
                <ContextMenuItem onClick={handleCreateInitiative}>
                  <Plus className="mr-2 h-4 w-4" />
                  {t("createInitiative")}
                </ContextMenuItem>
              )}
              <ContextMenuItem onClick={handleCommunitySettings}>
                <Settings className="mr-2 h-4 w-4" />
                {t("nav:communitySettings")}
              </ContextMenuItem>
              {/* The portal is where every change to the plan is made — this
                  only opens it. The seat's own holder's, which is who the
                  portal answers; never a grantee lent the seat. */}
              {canSell && holdsBillingSeat(community) && (
                <ContextMenuItem onClick={() => void openPortal(community.id, "manage")}>
                  <CreditCard className="mr-2 h-4 w-4" />
                  {t("usagePanel.manageBilling")}
                </ContextMenuItem>
              )}
            </>
          )}
          <ContextMenuSeparator />
          {onReorder ? (
            <ContextMenuItem onClick={onReorder}>
              <GripVertical className="mr-2 h-4 w-4" />
              {t("reorderCommunities")}
            </ContextMenuItem>
          ) : null}
          <ContextMenuItem onClick={handleCopyCommunityId}>
            <Copy className="mr-2 h-4 w-4" />
            {t("copyCommunityId")}
          </ContextMenuItem>
          {closed ? null : (
            <>
              <ContextMenuSeparator />
              <ContextMenuItem
                onClick={() => setLeaveDialogOpen(true)}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="mr-2 h-4 w-4" />
                {t("leaveCommunity")}
              </ContextMenuItem>
            </>
          )}
        </ContextMenuContent>
      </ContextMenu>
      <LeaveCommunityDialog
        community={community}
        open={leaveDialogOpen}
        onOpenChange={setLeaveDialogOpen}
      />
    </>
  );
};

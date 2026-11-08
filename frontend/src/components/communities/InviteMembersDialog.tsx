import { useTranslation } from "react-i18next";

import { MemberInvites } from "@/components/communities/CommunityInvites";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityInvites } from "@/hooks/useCommunityInvites";
import type { DialogProps } from "@/types/dialog";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";

/**
 * The active community's member invites, where its members are: its banner and
 * its members page. The same invites as Settings › Users, for whoever hands
 * them out. Callers mount it only while it is open, so closing it drops the
 * form and the link it made.
 */
export const InviteMembersDialog = ({ open, onOpenChange }: DialogProps) => {
  const { t } = useTranslation("communities");
  const { activeCommunity } = useCommunities();
  const invites = useCommunityInvites(activeCommunity?.id ?? null, open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("users.invitesTitle")}</DialogTitle>
          <DialogDescription>{t("users.invitesDescription")}</DialogDescription>
        </DialogHeader>
        <MemberInvites invites={invites} />
      </DialogContent>
    </Dialog>
  );
};

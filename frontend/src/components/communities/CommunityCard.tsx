/**
 * One community in the community directory.
 *
 * Everything on this card is what the community published by opting in — its
 * banner, name, description, icon, shelves, and how many people are already
 * there. A community the caller is already in keeps its card (so a search still
 * finds it) but offers a way in rather than a way to join twice. One that takes
 * requests is asked rather than joined, and says so while the ask waits.
 *
 * The two pictures arrive as URLs and are fetched per card, not carried in the
 * directory payload: a page is up to sixty of these, and each one is then
 * cached against a URL that changes only when the picture does. Every card has
 * a banner: the community's artwork, or the colour it wears instead, which costs
 * no fetch at all.
 */

import { useNavigate } from "@tanstack/react-router";
import { Clock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DirectoryCommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { AgeConfirmationDialog } from "@/components/communities/AgeConfirmationDialog";
import { CommunityCardFace } from "@/components/communities/CommunityCardFace";
import { CommunityAvatar } from "@/components/communities/CommunitySidebar";
import { RequestToJoinDialog } from "@/components/members/RequestToJoinDialog";
import { ReportButton } from "@/components/moderation/ReportButton";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import {
  useAskToJoinDirectoryCommunity,
  useJoinDirectoryCommunity,
  useWithdrawDirectoryJoinRequest,
} from "@/hooks/useCommunityDirectory";
import { communityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";

export const CommunityCard = ({ community }: { community: DirectoryCommunityRead }) => {
  const { t } = useTranslation(["communities", "common"]);
  const navigate = useNavigate();
  const { refreshCommunities, switchCommunity } = useCommunities();
  const join = useJoinDirectoryCommunity();
  const ask = useAskToJoinDirectoryCommunity();
  const withdraw = useWithdrawDirectoryJoinRequest();
  const { user } = useAuth();
  const { communityAgeGateEnabled } = useAppConfig();
  const [askingAge, setAskingAge] = useState(false);
  const [asking, setAsking] = useState(false);
  const byRequest = community.join_policy === "request";

  // Somebody may only take a place in a listed community, or ask for one, once
  // they have said they are old enough. Asked here, before the join, so
  // answering is what joins (or asks) — the server refuses it either way, and
  // being refused after clicking Join is a worse way to be asked a question you
  // can answer.
  //
  // This is the only place the question is put. An account that never answers
  // it keeps every community it was invited to and the whole of the app around
  // this card; all it cannot do is join a community from the directory.
  const needsAgeConfirmation = communityAgeGateEnabled && !user?.age_confirmed_at;

  const open = () => {
    void switchCommunity(community.id);
    void navigate({ to: communityPath(community.id, "/") });
  };

  // The join itself, with no age check in it. The dialog resumes through this
  // rather than through ``handleJoin``: it calls back the moment the
  // confirmation is recorded, which is before React has re-rendered this card
  // with the refreshed account — so a check here would still read the stale
  // "not confirmed" and reopen the dialog it was just dismissed from.
  const performJoin = async () => {
    try {
      await join.mutateAsync(community.id);
      // The switcher is built from the caller's memberships, so it has to learn
      // about the new one before we navigate into it.
      await refreshCommunities();
      toast.success(t("communities:community.joinedToast", { community: community.name }));
      open();
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error, "communities:community.joinFailed"));
    }
  };

  const proceed = () => (byRequest ? setAsking(true) : void performJoin());

  const handleJoin = () => {
    if (needsAgeConfirmation) {
      setAskingAge(true);
      return;
    }
    proceed();
  };

  const sendRequest = async (message: string | null) => {
    try {
      await ask.mutateAsync({ communityId: community.id, message });
      toast.success(t("communities:community.askedToast", { community: community.name }));
      setAsking(false);
    } catch (error) {
      toast.error(getErrorMessage(error, "communities:community.askFailed"));
    }
  };

  const withdrawRequest = async () => {
    try {
      await withdraw.mutateAsync(community.id);
    } catch (error) {
      toast.error(getErrorMessage(error, "communities:community.withdrawFailed"));
    }
  };

  return (
    <>
      <AgeConfirmationDialog open={askingAge} onOpenChange={setAskingAge} onConfirmed={proceed} />
      <RequestToJoinDialog
        title={t("communities:community.askTitle", { community: community.name })}
        description={t("communities:community.askDescription")}
        hint={t("communities:community.askHint")}
        pending={ask.isPending}
        onSend={(message) => void sendRequest(message)}
        open={asking}
        onOpenChange={setAsking}
      />
      <CommunityCardFace
        community={community}
        avatar={<CommunityAvatar name={community.name} icon={community.icon_url} active={false} />}
        aside={
          // A listing is the deployment's to answer for, not the community's
          // own — so no community is sent with it.
          <ReportButton
            targetType="directory_listing"
            targetId={community.id}
            communityId={null}
            className="-mt-1 shrink-0"
          />
        }
      >
        <div className="mt-auto pt-1">
          {community.already_member ? (
            <Button variant="outline" className="w-full" onClick={open}>
              {t("communities:community.open")}
            </Button>
          ) : community.request_pending ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-muted-foreground text-sm">
                <Clock className="h-4 w-4" aria-hidden="true" />
                {t("communities:community.requested")}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void withdrawRequest()}
                pending={withdraw.isPending}
              >
                {t("communities:community.withdraw")}
              </Button>
            </div>
          ) : (
            <Button className="w-full" onClick={handleJoin} pending={join.isPending}>
              {join.isPending
                ? t("communities:community.joining")
                : byRequest
                  ? t("communities:community.askToJoin")
                  : t("communities:community.join")}
            </Button>
          )}
        </div>
      </CommunityCardFace>
    </>
  );
};

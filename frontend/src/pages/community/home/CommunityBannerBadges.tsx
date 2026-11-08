/**
 * How many people are in this community, and how many are here right now.
 *
 * The two counts a community's front page can answer that no page inside it can:
 * the roster is the size of the place, and the room is whether anything is
 * happening in it. They ride on the banner because that is the one element on
 * the page that is about the community rather than about its contents. Beside
 * them, for whoever hands out invites, is the way to add to the count.
 *
 * They are dressed in the banner's own ink rather than in the app's palette —
 * a tint of it for the chip, the colour itself for the words — so one stored
 * colour clothes the whole banner and a chip is never the one thing on it that
 * turns out to be unreadable. The presence dot is the exception: green is what
 * "someone is here" means, on any banner.
 */

import { Link } from "@tanstack/react-router";
import { UserPlus, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import { readableTextShadow } from "@/lib/contrastColor";
import { withAlpha } from "@/lib/cssColor";

export type CommunityBannerBadgesProps = {
  /** The community whose roster the member count leads to. */
  communityId: number;
  memberCount: number;
  onlineCount: number;
  /** The banner's text colour, which these are tinted from. */
  ink: string;
  /** Opens the invite dialog, for whoever hands out invites; passing it is
   *  the gate. */
  onInvite?: () => void;
};

export const CommunityBannerBadges = ({
  communityId,
  memberCount,
  onlineCount,
  ink,
  onInvite,
}: CommunityBannerBadgesProps) => {
  const { t } = useTranslation("communities");

  const chip = {
    backgroundColor: withAlpha(ink, 0.16),
    borderColor: withAlpha(ink, 0.35),
    color: ink,
    textShadow: readableTextShadow(ink),
  };
  const pressable =
    "flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium text-xs backdrop-blur-sm transition hover:brightness-110 focus-visible:outline-2 focus-visible:outline-current";

  return (
    <>
      {/* The count is the way in: it says how many people are here, so it is
          what somebody looking for one of them reaches for. */}
      <Link
        to="/c/$communityId/members"
        params={{ communityId: String(communityId) }}
        className={pressable}
        style={chip}
      >
        <Users className="h-3.5 w-3.5" aria-hidden="true" />
        {t("memberCount", { count: memberCount })}
      </Link>
      {/* A community with nobody in it says nothing rather than "0 online", which
          reads as a verdict on the community rather than on the moment. */}
      {onlineCount > 0 ? (
        <span
          className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium text-xs backdrop-blur-sm"
          style={chip}
        >
          <span className="size-2 rounded-full bg-emerald-400" aria-hidden="true" />
          {t("community.onlineCount", { count: onlineCount })}
        </span>
      ) : null}
      {onInvite ? (
        <button type="button" onClick={onInvite} className={pressable} style={chip}>
          <UserPlus className="h-3.5 w-3.5" aria-hidden="true" />
          {t("inviteMembers")}
        </button>
      ) : null}
    </>
  );
};

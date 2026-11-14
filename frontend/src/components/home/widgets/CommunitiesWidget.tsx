/**
 * The reader's communities as the cards the directory and profiles show — the
 * banner, who is there, what it says about itself — each one the way in: for
 * somebody who is here to follow a club, a space or a team rather than to
 * work a list.
 */

import { Link } from "@tanstack/react-router";
import { Users } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { DirectoryCommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { CommunityCard } from "@/components/communities/CommunityCard";
import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import { useCommunities } from "@/hooks/useCommunities";
import { Button } from "@/ui/button";

export const CommunitiesWidget = () => {
  const { t } = useTranslation("home");
  const { communities } = useCommunities();

  // Each as the directory lists one the reader is already in, which offers a
  // way in rather than a way to join. The banner is the card rendition, as the
  // rail's expanded list draws it: the full one is many times heavier.
  const cards = useMemo<DirectoryCommunityRead[]>(
    () =>
      communities.map((community) => ({
        id: community.id,
        name: community.name,
        description: community.description,
        icon_url: community.icon_url,
        categories: community.categories,
        member_count: community.member_count,
        online_count: community.online_count,
        already_member: true,
        join_policy: community.join_policy,
        request_pending: false,
        banner: { ...community.banner, image_url: community.banner_card_url },
        location: community.location,
      })),
    [communities]
  );

  return (
    <HomeWidgetCard icon={Users} title={t("widgets.communities.title")} to="/communities">
      {cards.length === 0 ? (
        <HomeWidgetNotice
          icon={Users}
          action={
            <Button asChild size="sm" variant="outline">
              <Link to="/communities">{t("widgets.communities.find")}</Link>
            </Button>
          }
        >
          {t("widgets.communities.empty")}
        </HomeWidgetNotice>
      ) : (
        <div className="grid grid-cols-fill-64/3 gap-4">
          {cards.map((community) => (
            <CommunityCard key={community.id} community={community} />
          ))}
        </div>
      )}
    </HomeWidgetCard>
  );
};

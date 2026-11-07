/**
 * What people changed lately in one of the reader's communities: the feed from
 * that community's front page, brought home.
 *
 * It names its community in its options. Without one — a starting layout
 * knows nobody's communities — it shows the reader's first.
 */

import { Link } from "@tanstack/react-router";
import { Activity } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { FeedView } from "@/api/generated/initiativeAPI.schemas";
import { CommunityActivityFeed } from "@/components/communityHome/CommunityActivityFeed";
import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import { useAuth } from "@/hooks/useAuth";
import { type CommunityEntry, useCommunities } from "@/hooks/useCommunities";
import { activityLastVisitKey } from "@/lib/activityLastVisit";
import { communityPath } from "@/lib/communityUrl";
import { getItem } from "@/lib/storage";
import { Button } from "@/ui/button";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

/** The feed's views a card can show; Comments is a list of its own. */
const VIEWS = [FeedView.all, FeedView.yours] as const;

const viewOf = (options: Record<string, unknown>): FeedView =>
  VIEWS.includes(options.view as (typeof VIEWS)[number])
    ? (options.view as FeedView)
    : FeedView.all;

/** The community the options name, while the reader is still in it; else their first. */
const communityOf = (
  options: Record<string, unknown>,
  communities: CommunityEntry[]
): CommunityEntry | undefined =>
  communities.find((community) => community.id === options.communityId) ?? communities[0];

export const ActivityWidget = ({ options }: HomeWidgetProps) => {
  const { t } = useTranslation("home");
  const { communities } = useCommunities();
  const { user } = useAuth();
  const community = communityOf(options, communities);
  const view = viewOf(options);

  // Entries since the reader last opened the community's front page are new.
  // Read, not moved: looking at the widget is not a visit to the community.
  const lastVisit = useMemo(
    () => (user && community ? getItem(activityLastVisitKey(user.id, community.id)) : null),
    [user, community]
  );

  return (
    <HomeWidgetCard
      icon={Activity}
      title={
        community
          ? t("widgets.activity.titleIn", { community: community.name })
          : t("widgets.activity.title")
      }
      to={community ? communityPath(community.id, "/") : undefined}
    >
      {community ? (
        <CommunityActivityFeed
          key={community.id}
          view={view}
          lastVisit={lastVisit}
          communityId={community.id}
        />
      ) : (
        <HomeWidgetNotice
          icon={Activity}
          action={
            <Button asChild size="sm" variant="outline">
              <Link to="/communities">{t("widgets.communities.find")}</Link>
            </Button>
          }
        >
          {t("widgets.activity.noCommunity")}
        </HomeWidgetNotice>
      )}
    </HomeWidgetCard>
  );
};

export const ActivitySettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation(["home", "communityHome"]);
  const { communities } = useCommunities();
  const community = communityOf(options, communities);
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="activity-widget-community">{t("widgets.activity.community")}</Label>
        <Select
          value={community ? String(community.id) : undefined}
          onValueChange={(value) => onChange({ ...options, communityId: Number(value) })}
          disabled={communities.length === 0}
        >
          <SelectTrigger id="activity-widget-community">
            <SelectValue placeholder={t("widgets.activity.noCommunity")} />
          </SelectTrigger>
          <SelectContent>
            {communities.map((each) => (
              <SelectItem key={each.id} value={String(each.id)}>
                {each.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="activity-widget-view">{t("widgets.activity.view")}</Label>
        <Select value={viewOf(options)} onValueChange={(view) => onChange({ ...options, view })}>
          <SelectTrigger id="activity-widget-view">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {VIEWS.map((view) => (
              <SelectItem key={view} value={view}>
                {t(`communityHome:feed.nodes.${view}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
};

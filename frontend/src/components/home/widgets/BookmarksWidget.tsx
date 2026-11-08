/**
 * What the reader bookmarked, from every community: the things they keep coming
 * back to, one click away. Every kind of tool unless the reader picks some in
 * its settings. The bookmark on each row takes it off again.
 */

import { Link } from "@tanstack/react-router";
import { Bookmark } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import { useCommunities } from "@/hooks/useCommunities";
import { useMyBookmarks, useToggleBookmark } from "@/hooks/usePersonalItems";
import { renderRecentIcon } from "@/lib/recentIcon";
import { recentRoute } from "@/lib/recentRoute";
import { toolNavLabelKey } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Skeleton } from "@/ui/skeleton";

import { onlyTool, ToolsSetting, toolsOf } from "./toolFilter";
import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

export const BookmarksWidget = ({ options }: HomeWidgetProps) => {
  const { t } = useTranslation(["home", "search", "common"]);
  const { t: tNav } = useTranslation("nav");
  const tools = toolsOf(options);
  const only = onlyTool(options);
  const bookmarks = useMyBookmarks();
  const unbookmark = useToggleBookmark();
  const { communities } = useCommunities();

  // A row's community, said only to somebody who is in more than one.
  const where = useMemo(() => {
    const names = new Map(communities.map((community) => [community.id, community.name]));
    const several = communities.length > 1;
    return (communityId: number) => (several ? (names.get(communityId) ?? null) : null);
  }, [communities]);

  const rows = (bookmarks.data ?? []).filter((item) => tools.includes(item.entity_type as Tool));

  let body: React.ReactNode;
  if (bookmarks.isLoading) {
    body = (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
          <Skeleton key={i} className="h-10 rounded-lg" />
        ))}
      </div>
    );
  } else if (bookmarks.isError) {
    body = <p className="text-destructive text-sm">{t("widgets.bookmarks.loadError")}</p>;
  } else if (rows.length === 0) {
    body = (
      <HomeWidgetNotice
        icon={Bookmark}
        action={
          <Button asChild size="sm" variant="outline">
            <Link to="/my-tools">{t("widgets.recent.openTools")}</Link>
          </Button>
        }
      >
        {t("widgets.bookmarks.empty")}
      </HomeWidgetNotice>
    );
  } else {
    body = (
      <ul className="space-y-1">
        {rows.map((item) => {
          const kind = t(`search:types.${item.entity_type}` as never, {
            defaultValue: item.entity_type,
          });
          const place = where(item.community_id);
          return (
            <li
              key={`${item.community_id}:${item.entity_type}:${item.entity_id}`}
              className="flex items-center gap-1 rounded-lg transition-colors hover:bg-accent"
            >
              <Link to={recentRoute(item)} className="flex min-w-0 flex-1 items-center gap-3 p-1.5">
                <span className="flex size-6 shrink-0 items-center justify-center">
                  {renderRecentIcon(item)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-sm">{item.name}</span>
                  <span className="block truncate text-muted-foreground text-xs">
                    {only ? place : [kind, place].filter(Boolean).join(" · ")}
                  </span>
                </span>
              </Link>
              <button
                type="button"
                className="mr-1 inline-flex size-7 shrink-0 items-center justify-center rounded-md text-amber-500 transition hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={t("common:bookmark.remove")}
                title={t("common:bookmark.remove")}
                onClick={() =>
                  unbookmark.mutate({
                    tool: item.entity_type,
                    entityId: item.entity_id,
                    communityId: item.community_id,
                    next: false,
                  })
                }
              >
                <Bookmark className="size-4" fill="currentColor" aria-hidden />
              </button>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <HomeWidgetCard
      icon={Bookmark}
      title={
        only
          ? t("widgets.bookmarks.titleIn", { tool: tNav(toolNavLabelKey(only)) })
          : t("widgets.bookmarks.title")
      }
    >
      {body}
    </HomeWidgetCard>
  );
};

export const BookmarksSettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation("home");
  return (
    <ToolsSetting
      id="bookmarks-widget-tools"
      options={options}
      onChange={onChange}
      hint={t("widgets.bookmarks.toolsHint")}
    />
  );
};

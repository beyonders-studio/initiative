import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PersonalItemRead } from "@/api/generated/initiativeAPI.schemas";
import { SkeletonPillRow, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { renderRecentIcon } from "@/lib/recentIcon";
import { type RecentKey, recentKeyMatches, recentRoute } from "@/lib/recentRoute";
import { cn } from "@/lib/utils";

interface RecentTabsBarProps {
  items?: PersonalItemRead[];
  activeKey?: RecentKey | null;
  loading?: boolean;
  onClose: (item: PersonalItemRead) => void;
  onCloseOthers: (item: PersonalItemRead) => void;
  onCloseAll: () => void;
}

/**
 * Sticky-header tabs bar for the most-recently-opened community-scoped items
 * (projects, files, counter groups), capped per user by their
 * ``recent_tabs_limit`` interface setting. Replaces the projects-only
 * ``ProjectTabsBar``.
 *
 * Each tab has a right-click context menu (close / close others / close all)
 * in addition to its inline X button.
 */
export const RecentTabsBar = ({
  items,
  activeKey,
  loading,
  onClose,
  onCloseOthers,
  onCloseAll,
}: RecentTabsBarProps) => {
  const { t } = useTranslation(["projects", "common"]);

  if (!loading && (!items || items.length === 0)) {
    return null;
  }

  return (
    <ScrollArea className="h-12 pt-2.5">
      <div className="flex h-full items-end gap-2 px-4">
        {loading ? (
          <SkeletonRegion label={t("tabsBar.loadingRecent")}>
            <SkeletonPillRow count={3} pillClassName="h-9 w-36 rounded-t-md rounded-b-none" />
          </SkeletonRegion>
        ) : (
          items?.map((item) => {
            const isActive = recentKeyMatches(activeKey ?? null, item);
            return (
              <ContextMenu key={`${item.community_id}-${item.entity_type}-${item.entity_id}`}>
                <ContextMenuTrigger asChild>
                  <div className="flex items-center">
                    <Link
                      to={recentRoute(item)}
                      className={cn(
                        "group inline-flex items-center gap-2 rounded-t-md border border-transparent px-3 py-2 text-sm transition",
                        isActive
                          ? "border-border bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {renderRecentIcon(item)}
                      <span className="max-w-40 truncate">{item.name}</span>
                    </Link>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="ml-1 h-7 w-7 text-muted-foreground hover:text-foreground"
                      onClick={(event) => {
                        event.preventDefault();
                        onClose(item);
                      }}
                      aria-label={t("tabsBar.closeItem", { name: item.name })}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => onClose(item)}>
                    {t("common:close")}
                  </ContextMenuItem>
                  <ContextMenuItem
                    onSelect={() => onCloseOthers(item)}
                    disabled={(items?.length ?? 0) <= 1}
                  >
                    {t("tabsBar.closeOthers")}
                  </ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem onSelect={() => onCloseAll()}>
                    {t("tabsBar.closeAll")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            );
          })
        )}
      </div>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
};

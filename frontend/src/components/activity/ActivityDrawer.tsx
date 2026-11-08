/**
 * The activity beside the page: the community's feed narrowed to the tool or
 * the initiative being looked at, as the community home shows it. Folded to a
 * strip until it is opened, and read only once it is.
 */

import { Activity, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { FeedView } from "@/api/generated/initiativeAPI.schemas";
import { CommunityActivityFeed } from "@/components/communityHome/CommunityActivityFeed";
import { Button } from "@/components/ui/button";
import type { ActivityScope } from "@/lib/recentRoute";
import { cn } from "@/lib/utils";

interface ActivityDrawerProps {
  /** What the page is about, or null for a page with no drawer. */
  scope: ActivityScope | null;
}

export const ActivityDrawer = ({ scope }: ActivityDrawerProps) => {
  const { t } = useTranslation("communityHome");
  const [collapsed, setCollapsed] = useState(true);

  if (!scope) {
    return null;
  }

  const toggleCollapsed = () => {
    setCollapsed((prev) => !prev);
  };

  return (
    <aside
      className={cn(
        "sticky top-0 right-0 z-20 hidden h-app shrink-0 transition-all duration-200 lg:flex",
        collapsed ? "w-15" : "w-80"
      )}
    >
      <div className="flex h-full w-full flex-col border-l bg-card shadow-sm">
        <div
          className="flex flex-col border-b"
          style={{ paddingTop: "var(--safe-area-inset-top)" }}
        >
          <div className="flex h-12 items-center justify-between px-3">
            {!collapsed && (
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <p className="font-semibold text-sm">{t("activityDrawer.title")}</p>
              </div>
            )}
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={toggleCollapsed}
              >
                {collapsed ? (
                  <Activity className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                )}
                <span className="sr-only">
                  {collapsed ? t("activityDrawer.expand") : t("activityDrawer.collapse")}
                </span>
              </Button>
            </div>
          </div>
        </div>
        {collapsed ? (
          <div className="flex-1 px-2 py-4 text-center text-muted-foreground text-xs">
            {t("activityDrawer.title")}
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-3 py-3">
            <CommunityActivityFeed view={FeedView.all} lastVisit={null} scope={scope} />
          </div>
        )}
      </div>
    </aside>
  );
};

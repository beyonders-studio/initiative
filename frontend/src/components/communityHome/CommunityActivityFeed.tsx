/**
 * What people changed lately in the community, a card per item: who did what
 * to it and when, over a preview of the item itself that opens it. It fills the
 * tray under the front page's rail, one view per circle.
 *
 * The endpoint returns only what the reader can open and orders it for them, so
 * nothing is filtered or sorted here. An entry the reader has not seen since
 * their last visit is marked as new.
 */

import { Link } from "@tanstack/react-router";
import { Activity } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityEntry, FeedView } from "@/api/generated/initiativeAPI.schemas";
import { MentionText } from "@/components/user/MentionText";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useActivityFeed } from "@/hooks/useActivity";
import { communityPath, useCommunityPath } from "@/lib/communityUrl";
import type { ActivityScope } from "@/lib/recentRoute";
import { FROM_FEED, hitIcon, searchHitPath } from "@/lib/searchResults";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Badge } from "@/ui/badge";
import { Card } from "@/ui/card";
import { listFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";
import { LoadMore } from "@/ui/load-more";
import { RelativeTime } from "@/ui/relative-time";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

/** "Ada and 2 others commented and edited", in the reader's language. */
const useSentence = () => {
  const { t, i18n } = useTranslation("communityHome");
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const and = listFormat(locale, { type: "conjunction" });
  return (entry: ActivityEntry) => {
    const count = entry.actor_count;
    const names = entry.actors.map((person) => getUserDisplayName(person));
    const rest = count - names.length;
    const people = and.format(rest > 0 ? [...names, t("feed.others", { count: rest })] : names);
    const actions = and.format(entry.verbs.map((verb) => t(`feed.verbs.${verb}`, { count })));
    return t("feed.sentence", { people, actions, count });
  };
};

const FeedCard = ({
  entry,
  isNew,
  communityId,
}: {
  entry: ActivityEntry;
  isNew: boolean;
  communityId?: number;
}) => {
  const { t } = useTranslation(["communityHome", "search"]);
  const activeCommunityPath = useCommunityPath();
  const gp = (to: string) =>
    communityId != null ? communityPath(communityId, to) : activeCommunityPath(to);
  const sentence = useSentence();
  const Icon = hitIcon(entry);
  const path = searchHitPath(entry);
  const where = [entry.tool_title, entry.initiative_name].filter(Boolean).join(" · ");
  const kind = t(`search:types.${entry.entity_type}` as never, { defaultValue: entry.entity_type });

  const body = (
    <>
      <div className="flex items-center gap-3">
        <div className="flex shrink-0 -space-x-3">
          {entry.actors.map((person) => (
            <ProfileAvatar key={person.id} user={person} ring className="size-9" />
          ))}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm">{sentence(entry)}</p>
          <div className="flex items-center gap-2">
            <RelativeTime date={entry.latest} className="text-muted-foreground text-xs" />
            {isNew ? <Badge variant="secondary">{t("feed.new")}</Badge> : null}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3 rounded-lg border bg-muted/40 p-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-background">
          <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">
            <MentionText text={entry.title} disableLink />
          </p>
          <p className="truncate text-muted-foreground text-xs">
            {where ? `${kind} · ${where}` : kind}
          </p>
        </div>
      </div>
    </>
  );

  return (
    <li>
      <Card className={cn("p-4 transition-colors", path && "hover:bg-accent/40")}>
        {path ? (
          <Link to={gp(path)} state={FROM_FEED} className="block">
            {body}
          </Link>
        ) : (
          body
        )}
      </Card>
    </li>
  );
};

/** A card's shape while the first page arrives. */
export const FeedCardSkeleton = () => (
  <Card className="space-y-3 p-4">
    <div className="flex items-center gap-3">
      <Skeleton className="size-9 rounded-full" />
      <div className="flex-1 space-y-1">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-3 w-1/4" />
      </div>
    </div>
    <Skeleton className="h-16 w-full rounded-lg" />
  </Card>
);

interface CommunityActivityFeedProps {
  view: FeedView;
  /** When the reader was last here, as an ISO time; nothing is new without one. */
  lastVisit: string | null;
  /** The one tool or initiative to show, for a feed beside it. */
  scope?: ActivityScope | null;
  /** The community to show, for a feed outside it (the home page); the page's
   *  own community otherwise. */
  communityId?: number;
}

export const CommunityActivityFeed = ({
  view,
  lastVisit,
  scope,
  communityId,
}: CommunityActivityFeedProps) => {
  const { t } = useTranslation("communityHome");
  const feed = useActivityFeed(
    {
      view,
      initiative_id: scope?.initiativeId,
      tool: scope?.tool,
      tool_id: scope?.toolId,
    },
    communityId
  );
  // Each page is ranked afresh, so an item that moved up since the last one
  // can come back on the next; it stays where it was first shown.
  const entries = useMemo(() => {
    const seen = new Set<string>();
    return (feed.data?.pages ?? [])
      .flatMap((page) => page.items)
      .filter((entry) => {
        const key = `${entry.entity_type}:${entry.entity_id}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }, [feed.data]);
  const since = lastVisit ? Date.parse(lastVisit) : null;

  if (feed.isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
          <FeedCardSkeleton key={i} />
        ))}
      </div>
    );
  }
  if (feed.isError && entries.length === 0) {
    return <StatusMessage onRetry={feed.refetch} />;
  }
  if (entries.length === 0) {
    return (
      <div className="flex h-50 flex-col items-center justify-center gap-2 text-muted-foreground text-sm">
        <Activity className="h-8 w-8 opacity-50" aria-hidden="true" />
        <span>{t(`feed.empty.${view}`)}</span>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <ul className="space-y-3">
        {entries.map((entry) => (
          <FeedCard
            key={`${entry.entity_type}:${entry.entity_id}`}
            entry={entry}
            isNew={since != null && Date.parse(entry.latest) > since}
            communityId={communityId}
          />
        ))}
      </ul>
      {feed.isFetchNextPageError ? (
        <p className="px-2 text-destructive text-sm">{t("feed.loadError")}</p>
      ) : null}
      <LoadMore
        hasMore={feed.hasNextPage}
        loading={feed.isFetchingNextPage}
        onLoadMore={feed.fetchNextPage}
      />
    </div>
  );
};

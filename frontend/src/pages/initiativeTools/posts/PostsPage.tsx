import { useRouter } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useToolImportAction } from "@/components/imports/ToolImportAction";
import { CreatePostDialog } from "@/components/initiativeTools/posts/CreatePostDialog";
import { PostCard } from "@/components/initiativeTools/posts/PostCard";
import { PostsFilterBar, type ReadFilter } from "@/components/initiativeTools/posts/PostsFilterBar";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { ToolViewFilter } from "@/components/initiativeTools/shared/ToolViewFilter";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { parsePropertyFilters } from "@/components/properties/PropertyFilter";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import { readToolListFilters, type ToolListFilters } from "@/components/tools/ToolFilterFields";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import { type ListViewSpec, NO_PART_VIEW, useListView, viewKey } from "@/hooks/useListView";
import { PostReadTrackerProvider } from "@/hooks/usePostReadTracker";
import { usePostsFeed, usePostsTimeline } from "@/hooks/usePosts";
import { useKnownTagIds } from "@/hooks/useTags";
import { useToolCounts } from "@/hooks/useToolCounts";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatPeriod, formatPeriodYear } from "@/lib/formatDate";
import { postPeriod } from "@/lib/posts";
import { browserTimezone } from "@/lib/timezones";
import { type ToolView, toolDetailRoute, toolViewParams } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { LoadMore } from "@/ui/load-more";
import { CardGridSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { useVirtualRows } from "@/ui/virtual-rows";

/**
 * A first guess at a card's height, corrected by measurement as each mounts.
 *
 * Only the notices near the window are ever mounted, which is the whole point:
 * every card mounts a Lexical editor for its body, and an hour of scrolling
 * should not leave a hundred of them alive.
 *
 * Deliberately not a threshold. Turning virtualization on partway down a list
 * swaps every rendered card for an estimated one mid-scroll, and the browser
 * keeps the scroll offset while the content under it changes height — which
 * lands the reader somewhere else entirely, usually the top. Virtualizing from
 * the first render costs nothing on a short board (everything fits in the
 * window and overscan, so everything is rendered) and there is no moment where
 * the page changes shape underneath somebody.
 */
const CARD_ESTIMATE_HEIGHT = 420;

/**
 * Cards kept mounted either side of the window.
 *
 * Higher than a list of cheap rows would want, because mounting a card is
 * mounting an editor: the cost is paid when a card enters the set, and paying
 * it during the scroll is what a dropped frame looks like. Three gives it a
 * screen of warning.
 */
const VIRTUALIZER_OVERSCAN = 3;

/** The gap between cards, applied INSIDE each measured element. A flex `gap`
 *  sits between items and so is invisible to `measureElement`, which leaves
 *  the virtualizer's model shorter than the real list by the gap times the
 *  number of rows — and everything below drifts. */
const CARD_GAP = "pb-4";

type PostsViewProps = {
  /** The initiative whose board this is. Required: a board belongs to one. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's bulletin board.
 *
 * A feed rather than a grid of cards, because a notice is meant to be read
 * where it sits. The server owns the order — live pins first, then newest —
 * and hands over five at a time; the board fetches the next five as the reader
 * nears the bottom rather than making them ask for them.
 *
 * The list is virtualized from the first render, so what an hour of scrolling
 * costs is a couple of screens of editors rather than every editor the reader
 * has passed. Heights are measured rather than assumed: a notice is as tall as
 * what somebody wrote.
 */
/** What a person narrows an initiative's board by. */
type PostsFilters = ToolListFilters<typeof Tool.post> & { read: ReadFilter };

const readPostsFilters = (raw: unknown): PostsFilters => {
  const kept = readToolListFilters(raw) as Partial<PostsFilters>;
  return { ...kept, read: kept.read === "unread" ? "unread" : "all" };
};

const NO_TAGS: number[] = [];

/** Where one person's view of an initiative's board is kept. */
const postsViewSpec = (communityId: number, initiativeId: number): ListViewSpec<PostsFilters> => ({
  key: viewKey("initiative", initiativeId, "posts"),
  communityId,
  read: readPostsFilters,
  defaults: { filters: { read: "all" }, ...NO_PART_VIEW },
});

export const PostsView = ({ fixedInitiativeId, canCreate }: PostsViewProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const router = useRouter();
  const gp = useCommunityPath();

  // This person's view of the board: its filters, kept for them, but for a
  // typed search, which is for this visit.
  const communityId = useActiveCommunityId();
  const viewSpec = useMemo(
    () => postsViewSpec(communityId, fixedInitiativeId),
    [communityId, fixedInitiativeId]
  );
  const postsView = useListView(viewSpec);
  const [searchText, setSearchText] = useState("");
  const { setFilters: keepFilters } = postsView;
  const readFilter = postsView.filters.read;
  const listFilters = useMemo<ToolListFilters<typeof Tool.post>>(() => {
    const { read, ...kept } = postsView.filters;
    void read;
    return { ...kept, ...(searchText ? { search: searchText } : {}) };
  }, [postsView.filters, searchText]);
  const setListFilters = useCallback(
    ({ search: typed, ...rest }: ToolListFilters<typeof Tool.post>) => {
      setSearchText(typed ?? "");
      keepFilters((prev) => ({ ...rest, read: prev.read }));
    },
    [keepFilters]
  );
  const setReadFilter = useCallback(
    (read: ReadFilter) => keepFilters((prev) => ({ ...prev, read })),
    [keepFilters]
  );
  const tagIds = useKnownTagIds(listFilters.tag_ids ?? NO_TAGS);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Which of the board's two states it is showing. An archived notice is off
  // the feed, so this is the only place it can be reached.
  const [view, setView] = useState<ToolView>("active");
  const countsQuery = useToolCounts(Tool.post, { initiative_id: fixedInitiativeId });
  const search = useDebouncedValue(listFilters.search ?? "", 300).trim();

  const filters = {
    initiative_id: fixedInitiativeId,
    ...toolViewParams(Tool.post, view),
    ...(search ? { search } : {}),
    ...(tagIds.length > 0 ? { tag_ids: tagIds } : {}),
    ...(listFilters.property_filters ? { property_filters: listFilters.property_filters } : {}),
    ...(readFilter === "unread" ? { unread: true } : {}),
  };
  const filtersKey = JSON.stringify(filters);

  // Where the board has been jumped to, if anywhere. Setting it re-anchors the
  // feed: a new query key, so the reader lands at the top of that month rather
  // than paging through everything since. A jump is into one set of results,
  // so it lapses when the filters change and the board starts at its latest.
  const [jump, setJump] = useState<{ period: string; at: string; filters: string } | null>(null);
  const anchor = jump?.filters === filtersKey ? jump : null;

  const postsQuery = usePostsFeed({ ...filters, ...(anchor ? { until: anchor.at } : {}) });

  // The rail is drawn from the same filters WITHOUT the anchor: it is the map,
  // and a map that only showed where you already are would be no use for
  // going anywhere else.
  const timelineQuery = usePostsTimeline({
    ...filters,
    tz: browserTimezone(),
  });

  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.post, {
    initiativeId: fixedInitiativeId,
  });
  const canCreatePosts = canCreate ?? canCreateDerived;

  // Pinning is initiative authority, not write access on the post — the same
  // rule the server applies, asked here only to decide what to offer.
  const initiativeQuery = useInitiative(fixedInitiativeId);
  const canPin = Boolean(initiativeQuery.data?.can.manage);
  const canModerate = Boolean(initiativeQuery.data?.can.moderate);

  const {
    open: createOpen,
    setOpen: setCreateOpen,
    onOpenChange: handleCreateOpenChange,
  } = useCreateFromSearchParam();

  useRegisterPrimaryCreateAction(
    canCreatePosts ? { run: () => setCreateOpen(true), label: t("createPost") } : null
  );

  const postImport = useToolImportAction({
    tool: Tool.post,
    canImport: canCreatePosts,
    fixedInitiativeId,
  });

  const posts = useMemo(
    () => postsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [postsQuery.data]
  );
  const totalCount = postsQuery.data?.pages[0]?.total_count ?? 0;
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = postsQuery;

  const activeFilterCount =
    (search ? 1 : 0) +
    (tagIds.length > 0 ? 1 : 0) +
    parsePropertyFilters(listFilters.property_filters).length +
    (readFilter === "unread" ? 1 : 0);
  const clearFilters = useCallback(() => {
    setSearchText("");
    keepFilters(null);
  }, [keepFilters]);

  // The page itself scrolls, not a box inside it, so the cards are measured
  // against the app's scroller rather than a container of their own.
  const listRef = useRef<HTMLDivElement | null>(null);
  const {
    virtualizer,
    items: virtualItems,
    paddingTop,
    paddingBottom,
  } = useVirtualRows(listRef, {
    count: posts.length,
    estimateSize: () => CARD_ESTIMATE_HEIGHT,
    overscan: VIRTUALIZER_OVERSCAN,
  });

  // The month at the top of the view, so the rail marks where the reader
  // actually is rather than where they last jumped from.
  //
  // The first VIRTUAL item is not it: the list keeps a few cards mounted above
  // the window on purpose, so around a month boundary that card is one the
  // reader has already scrolled past. The first card whose bottom edge is still
  // below the scroll position is the one they are looking at.
  const activePeriod = useMemo(() => {
    const top = virtualizer.scrollOffset ?? 0;
    const visible = virtualItems.find((item) => item.end > top) ?? virtualItems[0];
    const post = visible ? posts[visible.index] : posts[0];
    return post ? postPeriod(post) : null;
  }, [virtualItems, virtualizer.scrollOffset, posts]);

  /**
   * Jump to a month — glide if it is already loaded, re-anchor if it is not.
   *
   * The two paths land the same way, which is the point: the month's first
   * notice at the top of the view. Gliding is only possible for what is
   * already in the cache, and paging forward to reach a month a year back
   * would be dozens of requests and every notice in between mounting an
   * editor — so anything not loaded re-queries from that instant instead.
   */
  const jumpTo = useCallback(
    (stop: { period: string; anchor: string }) => {
      const loaded = posts.findIndex(
        (post) =>
          postPeriod(post) === stop.period &&
          // A pinned notice is lifted out of its month to the top of the feed,
          // so finding one says nothing about whether its month is loaded —
          // gliding to it would show one raised card where a month was asked
          // for. Only the chronological body counts. An anchored board has no
          // lifted band, so there every notice is in its own place.
          !(anchor === null && post.is_pinned)
      );
      if (loaded >= 0) {
        virtualizer.scrollToIndex(loaded, { align: "start" });
        return;
      }
      setJump({ period: stop.period, at: stop.anchor, filters: filtersKey });
    },
    [posts, virtualizer, anchor, filtersKey]
  );

  const renderCard = useCallback(
    (index: number) => (
      <PostCard
        key={posts[index].id}
        post={posts[index]}
        canPin={canPin}
        canModerate={canModerate}
      />
    ),
    [posts, canPin, canModerate]
  );

  return (
    <PostReadTrackerProvider>
      <div className="space-y-6">
        <ToolListToolbar
          leading={
            <ToolViewFilter
              tool={Tool.post}
              value={view}
              onChange={setView}
              counts={countsQuery.data?.views}
            />
          }
          // The panel below holds the fields; this is what opens it. Without
          // it the filters exist and nothing on the page reaches them.
          filters={{
            open: filtersOpen,
            onOpenChange: setFiltersOpen,
            activeCount: activeFilterCount,
          }}
          actions={
            canCreatePosts ? (
              <Button size="sm" className="h-9" onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("createPost")}
              </Button>
            ) : null
          }
          menuItems={postImport.menuItem}
        />
        {/* Outside the toolbar: a dropdown unmounts its content on close,
            which would take a dialog nested inside it along too. */}
        {postImport.dialog}

        <PostsFilterBar
          value={listFilters}
          onChange={setListFilters}
          readFilter={readFilter}
          onReadFilterChange={setReadFilter}
          filtersOpen={filtersOpen}
          onFiltersOpenChange={setFiltersOpen}
          onClear={clearFilters}
          activeCount={activeFilterCount}
          initiativeId={fixedInitiativeId}
        />

        {postsQuery.isLoading ? (
          <SkeletonRegion label={t("loading")}>
            <CardGridSkeleton count={3} className="space-y-4" />
          </SkeletonRegion>
        ) : postsQuery.isError ? (
          <p className="text-destructive text-sm">{t("loadError")}</p>
        ) : posts.length > 0 ? (
          <>
            {/* No flex `gap` here: the spacing lives inside each measured
                element (see CARD_GAP), so what the virtualizer measures is
                what the list actually occupies. */}
            {anchor && (
              <div className="mx-auto flex w-full max-w-3xl items-center gap-2 text-muted-foreground text-sm">
                <span>
                  {t("common:timeline.jumpedTo", { period: formatPeriod(anchor.period) })}
                </span>
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto p-0 text-sm"
                  onClick={() => setJump(null)}
                >
                  {t("common:timeline.backToLatest")}
                </Button>
              </div>
            )}
            {/* The rail rides alongside the feed and stays put while it
                scrolls, so a jump is always one reach away rather than
                something to scroll back to. On a phone there is no room to
                stand it beside anything: it overlays the feed's edge — its own
                negative margin is what gives the notices the full width — and
                shows itself while the board is moving. */}
            <div className="mx-auto flex w-full max-w-3xl sm:gap-2">
              <div ref={listRef} className="flex min-w-0 flex-1 flex-col">
                <div style={{ height: paddingTop }} />
                {virtualItems.map((item) => (
                  <div
                    key={posts[item.index].id}
                    data-index={item.index}
                    ref={virtualizer.measureElement}
                    className={CARD_GAP}
                  >
                    {renderCard(item.index)}
                  </div>
                ))}
                <div style={{ height: paddingBottom }} />
              </div>
              <TimelineRail
                className="sticky top-16 h-[60vh] self-start"
                stops={timelineQuery.data?.buckets ?? []}
                // Where the reader IS, which after a glide is not where the
                // board was anchored. The banner above says the other half.
                activePeriod={activePeriod}
                onPick={jumpTo}
                formatLabel={(stop) => formatPeriod(stop.period)}
                formatGroup={(stop) => formatPeriodYear(stop.period)}
              />
            </div>
            {/* The bottom of the list asks for the next page as it comes into
                view, a screen ahead, so the next five are there before the
                reader is. */}
            <LoadMore
              auto
              rootMargin="600px"
              hasMore={hasNextPage}
              loading={isFetchingNextPage}
              onLoadMore={fetchNextPage}
            />
          </>
        ) : totalCount > 0 || activeFilterCount > 0 ? (
          <p className="text-muted-foreground text-sm">{t("filters.noMatchingPosts")}</p>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>{t("noPosts")}</CardTitle>
              <CardDescription>{t("noPostsDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={() => setCreateOpen(true)} disabled={!canCreatePosts}>
                {t("createFirst")}
              </Button>
            </CardContent>
          </Card>
        )}

        <CreatePostDialog
          open={createOpen}
          onOpenChange={handleCreateOpenChange}
          initiativeId={fixedInitiativeId}
          onSuccess={(post) => {
            void router.navigate({
              to: gp(toolDetailRoute(Tool.post, fixedInitiativeId, post.id)),
            });
          }}
        />
      </div>
    </PostReadTrackerProvider>
  );
};

import { useNavigate, useParams } from "@tanstack/react-router";
import { Clock, Info, LayoutGrid, Loader2, Plus, Tags } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useReadCatalogItem } from "@/api/generated/catalogs/catalogs";
import type {
  CatalogItemRead,
  TagSummary,
  TimelineBucket,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool, ViewSource } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { BulkEditImageTagsDialog } from "@/components/initiativeTools/catalogs/BulkEditImageTagsDialog";
import { CatalogBulkBar } from "@/components/initiativeTools/catalogs/CatalogBulkBar";
import {
  CatalogDropzone,
  type CatalogDropzoneHandle,
} from "@/components/initiativeTools/catalogs/CatalogDropzone";
import { CatalogGridView } from "@/components/initiativeTools/catalogs/CatalogGridView";
import { CatalogItemSheet } from "@/components/initiativeTools/catalogs/CatalogItemSheet";
import {
  CatalogItemsFilterBar,
  type ImageOrder,
} from "@/components/initiativeTools/catalogs/CatalogItemsFilterBar";
import { CatalogMasonryView } from "@/components/initiativeTools/catalogs/CatalogMasonryView";
import { CatalogTimelineView } from "@/components/initiativeTools/catalogs/CatalogTimelineView";
import { MasonryIcon } from "@/components/initiativeTools/catalogs/MasonryIcon";
import { UploadProgress } from "@/components/initiativeTools/catalogs/UploadProgress";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Lightbox, type LightboxItem } from "@/components/shared/Lightbox";
import {
  CardGridSkeleton,
  DetailHeaderSkeleton,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolChest } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { UserName } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { RelativeTime } from "@/components/ui/relative-time";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import {
  useBulkDeleteCatalogItems,
  useCatalog,
  useCatalogItemsFeed,
  useCatalogItemsTimeline,
  useUpdateCatalog,
} from "@/hooks/useCatalogs";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { type GridToggleOptions, useGridSelection } from "@/hooks/useGridSelection";
import { useImageUploader } from "@/hooks/useImageUploader";
import { useInitiative } from "@/hooks/useInitiatives";
import { LIST, type ListViewSpec, NO_PART_VIEW, useListView, viewKey } from "@/hooks/useListView";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { useKnownTagIds, useTags } from "@/hooks/useTags";
import { imageLabel, imageSrc } from "@/lib/catalogs";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatPeriod } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { catalogItemRoute, toolDetailRoute, toolListRoute, toolSettingsRoute } from "@/lib/tools";

type ViewMode = "masonry" | "grid" | "timeline";

/** What a person narrows a catalog's wall by: its tags. */
type CatalogFilters = { tag_ids: number[] };

const readCatalogFilters = (raw: unknown): CatalogFilters => ({
  tag_ids: Array.isArray((raw as CatalogFilters | null)?.tag_ids)
    ? (raw as CatalogFilters).tag_ids.filter((id) => typeof id === "number")
    : [],
});

/** The wall oldest first, as a sort; newest first is its own order. */
const OLDEST_FIRST = [{ id: "date", desc: false }];

/**
 * Where one person's view of a catalog is kept: how they look at the wall,
 * whether it is grouped by tag, its tags and its order. A typed search is for
 * this visit. What an older release kept (one look and grouping for every
 * wall) is carried over.
 */
const catalogViewSpec = (communityId: number, catalogId: number): ListViewSpec<CatalogFilters> => ({
  key: viewKey(communityId, "catalog", catalogId),
  read: readCatalogFilters,
  defaults: { filters: { tag_ids: [] }, ...NO_PART_VIEW },
  carryOver: (items) => {
    const look = items["catalogs:view-mode"];
    const grouped = items["catalogs:group-by-tag"] === true;
    if (typeof look !== "string" && !grouped) return null;
    return {
      layout: typeof look === "string" ? look : null,
      parts: { [LIST]: grouped ? { grouping: ["tags"] } : {} },
    };
  },
});

const isViewMode = (value: unknown): value is ViewMode =>
  value === "masonry" || value === "grid" || value === "timeline";

/**
 * One catalog: the wall, and the ways of looking at it.
 *
 * Three views of one list. The masonry keeps every picture's shape and packs
 * them; the grid crops them to tiles so forty read at a glance; the timeline
 * is the catalog as a record, a row per day with a rail down the side for
 * jumping months. The first two can be grouped by tag, which is the one
 * grouping a design team asks for: "everything still awaiting a decision".
 *
 * The list is fetched a page at a time as the reader nears the bottom, and
 * every view keeps only the pictures near the viewport in the DOM — so a
 * catalog of a thousand costs a screen or two, however far it is scrolled.
 * The whole page is a drop target: pictures dragged in from a folder land
 * wherever the cursor is, which is over the wall.
 */
export function CatalogDetailPage() {
  const { t } = useTranslation(["catalogs", "common"]);
  // An item's address is the catalog's with the item open beside it.
  const { catalogId, itemId } = useParams({ strict: false }) as {
    catalogId: string;
    itemId?: string;
  };
  const parsedId = Number(catalogId);
  const gp = useCommunityPath();

  const catalogQuery = useCatalog(Number.isFinite(parsedId) ? parsedId : null);
  const catalog = catalogQuery.data;
  const initiativeId = useCanonicalInitiativeId(catalog?.initiative_id);

  const viewedId = catalog?.id;
  useReadOnOpen(Tool.catalog, viewedId);
  useRecordOpen(Tool.catalog, viewedId);

  const canEdit = Boolean(catalog?.can.edit);
  const initiativeQuery = useInitiative(catalog?.initiative_id ?? null);
  const canModerate = Boolean(initiativeQuery.data?.can.moderate);

  // This person's view of the wall: how they look at it, its grouping, tags
  // and order, kept for them on this catalog.
  const communityId = useActiveCommunityId();
  const viewSpec = useMemo(
    () => catalogViewSpec(communityId, Number.isFinite(parsedId) ? parsedId : 0),
    [communityId, parsedId]
  );
  const wallView = useListView(viewSpec);
  const viewMode: ViewMode = isViewMode(wallView.layout) ? wallView.layout : "masonry";
  const setPersistedView = wallView.rememberLayout;
  const groupByTags = wallView.grouping.includes("tags");
  const { setGrouping, setFilters: keepFilters, setSorting } = wallView;
  const setGroupByTags = useCallback(
    (next: boolean) => setGrouping(next ? ["tags"] : []),
    [setGrouping]
  );

  const [searchQuery, setSearchQuery] = useState("");
  // The wall narrows by the kept ids at once; the picker shows their names
  // once the community's tags arrive.
  const tagIds = useKnownTagIds(wallView.filters.tag_ids);
  const { data: communityTags = [] } = useTags();
  const tagFilters = useMemo<TagSummary[]>(
    () => communityTags.filter((tag) => tagIds.includes(tag.id)),
    [communityTags, tagIds]
  );
  const setTagFilters = useCallback(
    (next: TagSummary[]) => keepFilters({ tag_ids: next.map((tag) => tag.id) }),
    [keepFilters]
  );
  const order: ImageOrder = wallView.sorting[0]?.desc === false ? "oldest" : "newest";
  const changeOrder = useCallback(
    (next: ImageOrder) => {
      setSorting(next === "oldest" ? OLDEST_FIRST : []);
      // An anchor names one end of a month, and which end is right depends on
      // the direction. Turning the list around releases the jump rather than
      // reading the anchor backwards.
      setAnchor(null);
    },
    [setSorting]
  );
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(searchQuery, 300);

  // Where the timeline has been jumped to, if anywhere. Setting it re-anchors
  // the feed: a new query key, so the reader lands at that month rather than
  // paging through everything since.
  const [anchor, setAnchor] = useState<{ period: string; at: string } | null>(null);

  const filters = useMemo(
    () => ({
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(tagIds.length > 0 ? { tag_ids: tagIds } : {}),
      ...(order === "oldest" ? { oldest_first: true } : {}),
    }),
    [search, tagIds, order]
  );

  const feed = useCatalogItemsFeed(Number.isFinite(parsedId) ? parsedId : null, {
    ...filters,
    ...(anchor ? { until: anchor.at } : {}),
  });
  const images = useMemo(() => feed.data?.pages.flatMap((page) => page.items) ?? [], [feed.data]);
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = feed;

  // The rail is drawn WITHOUT the anchor: it is the map.
  const timelineQuery = useCatalogItemsTimeline(
    Number.isFinite(parsedId) ? parsedId : null,
    {
      ...(filters.search ? { search: filters.search } : {}),
      ...(filters.tag_ids ? { tag_ids: filters.tag_ids } : {}),
    },
    { enabled: viewMode === "timeline" }
  );

  // The bottom of the wall asks for the next page as it comes into view.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "800px" }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  // Uploads.
  const uploader = useImageUploader(parsedId);
  const dropzoneRef = useRef<CatalogDropzoneHandle | null>(null);
  useRegisterPrimaryCreateAction(
    canEdit ? { run: () => dropzoneRef.current?.open(), label: t("addPictures") } : null
  );

  // The lightbox and the details panel. Both address a picture by id rather
  // than by index, so a page arriving underneath does not swap the picture
  // somebody is looking at.
  const [openId, setOpenId] = useState<number | null>(null);
  // An image opens in the lightbox.
  useRecordOpen("catalog_item", openId ?? undefined, { source: ViewSource.direct });
  const detailsId = itemId === undefined ? null : Number(itemId);
  const navigate = useNavigate();
  const setDetailsId = useCallback(
    (id: number | null) =>
      void navigate({
        to: gp(
          id === null
            ? toolDetailRoute(Tool.catalog, initiativeId, parsedId)
            : catalogItemRoute(initiativeId, parsedId, id)
        ),
        // The wall stays where it was under the item.
        resetScroll: false,
      }),
    [navigate, gp, initiativeId, parsedId]
  );
  const openIndex = openId === null ? -1 : images.findIndex((image) => image.id === openId);
  const lightboxItems = useMemo<LightboxItem[]>(
    () =>
      images.map((image) => ({
        id: image.id,
        src: imageSrc(image),
        alt: imageLabel(image),
        caption: (
          <span className="inline-flex flex-wrap items-center justify-center gap-x-2">
            {imageLabel(image) ? <span>{imageLabel(image)}</span> : null}
            {image.uploader ? <UserName user={image.uploader} className="text-white/70" /> : null}
            <RelativeTime date={image.created_at} className="text-white/60" />
          </span>
        ),
      })),
    [images]
  );
  const onNearEnd = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const listedDetails =
    detailsId === null ? null : (images.find((i) => i.id === detailsId) ?? null);
  // An item opened by its address may not be on a page loaded yet.
  const linkedItem = useReadCatalogItem(communityId, detailsId ?? 0, {
    query: { enabled: Number.isFinite(detailsId) && listedDetails === null },
  });
  const detailsImage =
    listedDetails ?? (linkedItem.data?.catalog_id === parsedId ? linkedItem.data : null);

  const setCover = useUpdateCatalog(parsedId, {
    onSuccess: () => toast.success(t("sheet.coverSet")),
  });
  const renameCatalog = useUpdateCatalog(parsedId);

  // Selecting pictures on the wall. The same click either opens a picture or
  // takes it into the selection, depending which the wall is doing — a tile is
  // the whole target, and a checkbox in the corner of a thumbnail is a
  // smaller one.
  const selection = useGridSelection(images);
  const selecting = selection.active;
  const selectedIds = selection.selectedIds;
  const isSelected = useCallback(
    (image: CatalogItemRead) => selectedIds.has(image.id),
    [selectedIds]
  );
  const onActivate = useCallback(
    (image: CatalogItemRead, options: GridToggleOptions) => {
      if (selection.active) selection.toggle(image, options);
      else setOpenId(image.id);
    },
    [selection.active, selection.toggle]
  );
  const selectAll = useCallback(() => {
    for (const image of images) {
      if (!selectedIds.has(image.id)) selection.toggle(image);
    }
  }, [images, selectedIds, selection.toggle]);

  const [bulkTagsOpen, setBulkTagsOpen] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const bulkDelete = useBulkDeleteCatalogItems(parsedId, {
    onSuccess: (result) => {
      setConfirmBulkDelete(false);
      selection.exit();
      // Anything removed cannot still be the picture the lightbox is showing.
      setOpenId(null);
      toast.success(t("bulk.deleted", { count: result.deleted_count }));
    },
  });
  const onJump = useCallback(
    (bucket: TimelineBucket) => {
      // Which end of the month to land on is the direction the list is read
      // in: newest first the page walks back from the month's last picture,
      // oldest first it walks forward from its first. Taking the wrong end
      // would jump to a month and show everything except it.
      setAnchor({
        period: bucket.period,
        at: order === "oldest" ? bucket.anchor_oldest : bucket.anchor,
      });
      document.querySelector<HTMLElement>("[data-app-scroll]")?.scrollTo({ top: 0 });
    },
    [order]
  );

  const activeFilterCount =
    (search.trim() ? 1 : 0) + (tagIds.length > 0 ? 1 : 0) + (order === "oldest" ? 1 : 0);
  const clearFilters = useCallback(() => {
    setSearchQuery("");
    keepFilters(null);
    setSorting([]);
    setAnchor(null);
  }, [keepFilters, setSorting]);

  if (!Number.isFinite(parsedId) || catalogQuery.isError) {
    return (
      <ToolAccessStatus
        error={catalogQuery.error}
        keys="catalogs:"
        backTo={gp(toolListRoute(Tool.catalog, initiativeId))}
        backLabel={t("backToCatalogs")}
      />
    );
  }

  const viewOptions = [
    { value: "masonry" as const, label: t("views.masonry"), icon: MasonryIcon },
    { value: "grid" as const, label: t("common:toolbar.viewGrid"), icon: LayoutGrid },
    { value: "timeline" as const, label: t("views.timeline"), icon: Clock },
  ];

  return (
    <div className="space-y-6">
      {catalog ? (
        <ToolPageHeader
          tool={Tool.catalog}
          initiativeId={catalog.initiative_id}
          starId={catalog.id}
          settingsTo={
            canEdit ? toolSettingsRoute(Tool.catalog, initiativeId, catalog.id) : undefined
          }
          chest={<ToolChest tool={Tool.catalog} entity={catalog} />}
          title={catalog.name}
          onRename={canEdit ? (name) => renameCatalog.mutateAsync({ name }) : undefined}
        >
          {catalog.description ? (
            <p className="max-w-prose text-muted-foreground">{catalog.description}</p>
          ) : null}
        </ToolPageHeader>
      ) : (
        <DetailHeaderSkeleton actions={0} description={false} />
      )}

      <ToolListToolbar
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        view={{
          value: viewMode,
          onChange: (value) => setPersistedView(value),
          options: viewOptions,
          label: t("views.label"),
        }}
        trailing={
          viewMode !== "timeline" ? (
            <Button
              // The same shape as the filter button beside it: outline when
              // off, secondary when on, label hidden on a narrow row.
              variant={groupByTags ? "secondary" : "outline"}
              size="sm"
              className="h-9 gap-2"
              aria-pressed={groupByTags}
              aria-label={t("groupByTag")}
              onClick={() => setGroupByTags(!groupByTags)}
            >
              <Tags className="h-4 w-4" />
              <span className="hidden sm:inline">{t("groupByTag")}</span>
            </Button>
          ) : null
        }
        onEnterSelection={canEdit && !selecting && images.length > 0 ? selection.enter : undefined}
        actions={
          canEdit ? (
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => dropzoneRef.current?.open()}
            >
              <Plus className="h-4 w-4" />
              {t("addPictures")}
            </Button>
          ) : null
        }
      />

      <CatalogItemsFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        tags={tagFilters}
        onTagsChange={setTagFilters}
        order={order}
        onOrderChange={changeOrder}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
        onClear={clearFilters}
        activeCount={activeFilterCount}
      />

      {selecting && (
        <CatalogBulkBar
          count={selection.selectedItems.length}
          total={images.length}
          onSelectAll={selectAll}
          onClear={selection.clear}
          onEditTags={() => setBulkTagsOpen(true)}
          onDelete={() => setConfirmBulkDelete(true)}
          deleting={bulkDelete.isPending}
          onExit={selection.exit}
        />
      )}

      <UploadProgress
        jobs={uploader.jobs}
        total={uploader.total}
        done={uploader.done}
        failed={uploader.failed}
        active={uploader.active}
        onDismiss={uploader.dismiss}
      />

      {anchor && (
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
          <span>{t("common:timeline.jumpedTo", { period: formatPeriod(anchor.period) })}</span>
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setAnchor(null)}>
            {t("common:timeline.backToLatest")}
          </Button>
        </div>
      )}

      <CatalogDropzone
        ref={dropzoneRef}
        enabled={canEdit}
        onFiles={uploader.enqueue}
        className="min-h-40 rounded-xl"
      >
        {feed.isLoading ? (
          <SkeletonRegion label={t("loadingPictures")}>
            <CardGridSkeleton count={8} className="grid grid-cols-fill-36/4 gap-3" />
          </SkeletonRegion>
        ) : feed.isError ? (
          <p className="text-destructive text-sm">{t("loadError")}</p>
        ) : images.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-8 text-center">
            <p className="font-medium">
              {activeFilterCount > 0 ? t("filters.noMatchingPictures") : t("noPictures")}
            </p>
            {activeFilterCount === 0 && (
              <p className="max-w-md text-muted-foreground text-sm">
                {canEdit ? t("noPicturesDescription") : t("noPicturesReadOnly")}
              </p>
            )}
            {canEdit && activeFilterCount === 0 && (
              <Button onClick={() => dropzoneRef.current?.open()}>
                <Plus className="h-4 w-4" />
                {t("addPictures")}
              </Button>
            )}
          </div>
        ) : viewMode === "grid" ? (
          <CatalogGridView
            images={images}
            groupByTags={groupByTags}
            onActivate={onActivate}
            selecting={selecting}
            isSelected={isSelected}
          />
        ) : viewMode === "timeline" ? (
          <CatalogTimelineView
            images={images}
            buckets={timelineQuery.data?.buckets ?? []}
            onActivate={onActivate}
            selecting={selecting}
            isSelected={isSelected}
            onJump={onJump}
          />
        ) : (
          <CatalogMasonryView
            images={images}
            groupByTags={groupByTags}
            onActivate={onActivate}
            selecting={selecting}
            isSelected={isSelected}
          />
        )}
        <div ref={sentinelRef} className="h-px" />
        {isFetchingNextPage && (
          <div className="flex justify-center py-4">
            <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
          </div>
        )}
      </CatalogDropzone>

      {/* A shelf, like a project's: a catalog's links are browsed along
          rather than read down. */}
      <ToolRelationsPanel
        tool={Tool.catalog}
        entity={catalog}
        canEdit={canEdit}
        entityTitle={catalog?.name}
      />

      {catalog != null && <ToolCommentsPanel tool={Tool.catalog} entity={catalog} />}

      <Lightbox
        open={openIndex >= 0}
        onOpenChange={(next) => {
          if (!next) setOpenId(null);
        }}
        items={lightboxItems}
        index={Math.max(openIndex, 0)}
        onIndexChange={(index) => setOpenId(images[index]?.id ?? null)}
        onNearEnd={onNearEnd}
        actions={
          openId !== null ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-white hover:bg-white/10 hover:text-white"
              onClick={() => setDetailsId(openId)}
            >
              <Info className="size-4" />
              {t("common:toolbar.details")}
            </Button>
          ) : null
        }
      />

      <BulkEditImageTagsDialog
        open={bulkTagsOpen}
        onOpenChange={setBulkTagsOpen}
        catalogId={parsedId}
        images={selection.selectedItems}
        onSuccess={selection.exit}
      />

      <ConfirmDialog
        open={confirmBulkDelete}
        onOpenChange={setConfirmBulkDelete}
        title={t("bulk.deleteTitle", { count: selection.selectedItems.length })}
        description={t("bulk.deleteDescription")}
        confirmLabel={t("bulk.delete")}
        cancelLabel={t("common:cancel")}
        isLoading={bulkDelete.isPending}
        destructive
        onConfirm={() => bulkDelete.mutate(selection.selectedItems.map((image) => image.id))}
      />

      <CatalogItemSheet
        catalogId={parsedId}
        initiativeId={initiativeId}
        image={detailsImage}
        open={detailsImage !== null}
        onOpenChange={(next) => {
          if (!next) setDetailsId(null);
        }}
        canEdit={canEdit}
        canDeleteVersions={Boolean(catalog?.can.delete)}
        canModerate={canModerate}
        isCover={catalog?.cover_item_id === detailsId}
        onSetCover={(imageId) => setCover.mutate({ cover_item_id: imageId })}
        onRemoved={(imageId) => {
          if (openId === imageId) setOpenId(null);
        }}
      />
    </div>
  );
}

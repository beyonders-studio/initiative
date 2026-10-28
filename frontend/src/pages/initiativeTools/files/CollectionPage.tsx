import { Link, useNavigate, useParams } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import {
  ExternalLink,
  LayoutList as LayoutsIcon,
  Loader2,
  Plus,
  Tags,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CollectionFileSummary,
  FileKind,
  type FileSummary,
  type ListLayoutDefinitionInput,
  PropertyTarget,
  SearchEntityType,
  type TimelineBucket,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import { HiddenFilesRequest } from "@/components/access/RequestAccess";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import {
  CollectionDropzone,
  type CollectionDropzoneHandle,
} from "@/components/files/collections/CollectionDropzone";
import {
  type CollectionList,
  CollectionListView,
} from "@/components/files/collections/collectionLists";
import { UploadProgress } from "@/components/files/collections/UploadProgress";
import { FileChooserDialog } from "@/components/files/FileChooserDialog";
import { COLLECTION_SORT_FIELDS } from "@/components/files/fileColumns";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import { Lightbox, type LightboxItem } from "@/components/shared/Lightbox";
import {
  CardGridSkeleton,
  DetailHeaderSkeleton,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolChest } from "@/components/tools/ToolChest";
import {
  readToolListFilters,
  ToolFilterFields,
  type ToolListFilters,
} from "@/components/tools/ToolFilterFields";
import type { ToolIndexRow } from "@/components/tools/ToolIndexPage";
import { TABLE_SORT_FIELDS, ToolIndexTable } from "@/components/tools/ToolIndexTable";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { RelativeTime } from "@/components/ui/relative-time";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import {
  type CollectionFilesParams,
  useAddCollectionFiles,
  useCollection,
  useCollectionFilesFeed,
  useCollectionFilesTimeline,
  useDeleteCollection,
  useRemoveCollectionFiles,
  useUpdateCollection,
} from "@/hooks/useCollections";
import { useCollectionUploader } from "@/hooks/useCollectionUploader";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { type GridToggleOptions, useGridSelection } from "@/hooks/useGridSelection";
import { type ListViewSpec, NO_PART_VIEW, useListView, viewKey } from "@/hooks/useListView";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { propertySaves, useProperties } from "@/hooks/useProperties";
import { useKnownTagIds } from "@/hooks/useTags";
import { detailLayoutOf, listLayouts, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatPeriod } from "@/lib/formatDate";
import { DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import type { StoredRegions } from "@/lib/layouts/detailLayout";
import { withDisplays } from "@/lib/layouts/fields";
import { FILE_DETAIL } from "@/lib/layouts/fileLayout";
import { collectionFileFields } from "@/lib/layouts/files";
import { toast } from "@/lib/mascotToast";
import { browserTimezone } from "@/lib/timezones";
import { collectionRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";

/** A file as the wall and the table both list it. */
type FileRow = CollectionFileSummary & { card: null };

/** What the Files list is narrowed by, which a collection's files are too. */
type FileFilters = ToolListFilters<typeof Tool.file>;

/** Oldest added first, as the walls' order; newest first is the order with
 *  none. */
const OLDEST_FIRST: SortingState = [{ id: "added_at", desc: false }];

/**
 * Where one person's view of a collection is kept: the list they were last
 * looking at, its grouping by tag, their filters and their order. A typed
 * search is for this visit. A converted gallery keeps the id it had, so the
 * view somebody kept on it as a gallery is read until they change this one.
 */
const collectionViewSpec = (
  communityId: number,
  collectionId: number
): ListViewSpec<FileFilters> => ({
  key: viewKey(communityId, "collection", collectionId),
  read: (raw) => readToolListFilters(raw) as FileFilters,
  defaults: { filters: {}, ...NO_PART_VIEW },
  carryOver: (items) =>
    (items[viewKey(communityId, "gallery", collectionId)] as Record<string, unknown> | undefined) ??
    null,
});

/**
 * One collection: its files, laid out as the collection's lists say, and what
 * a sub-tool carries — its tags, properties, links and comments.
 *
 * The lists are the collection's layouts. Each is shown or hidden for the
 * collection, one opens first, and each person picks among those shown. The
 * masonry, grid and timeline are the gallery's walls, kept as they were: the
 * list is fetched a page at a time as the reader nears the bottom, and every
 * wall keeps only the files near the viewport in the DOM. The table is the
 * Files table.
 *
 * Every file keeps its own sharing: the list holds only the files the reader
 * can open, and what they may do to each is the file's own answer. Changing
 * what is in the collection is the collection's, which the server answers in
 * `can.edit`. The whole page is a drop target for someone who may: files
 * dragged in are uploaded into the initiative and put in the collection.
 */
export function CollectionPage() {
  const { t } = useTranslation(["files", "common", "layouts"]);
  const { collectionId } = useParams({ strict: false }) as { collectionId: string };
  const parsedId = Number(collectionId);
  const validId = Number.isFinite(parsedId) ? parsedId : null;
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();

  const collectionQuery = useCollection(validId);
  const collection = collectionQuery.data;
  const initiativeId = useCanonicalInitiativeId(collection?.initiative_id);
  const canEdit = Boolean(collection?.can.edit);
  const filesRoute = gp(toolListRoute(Tool.file, initiativeId));

  useReadOnOpen(SearchEntityType.collection, collection?.id);
  useRecordOpen(SearchEntityType.collection, collection?.id);

  // The lists the collection shows, and the one it opens on.
  const layoutsQuery = useInstanceLayouts("collection", validId);
  const shown = useMemo(
    () => listLayouts(layoutsQuery.data).filter((layout) => !layout.hidden),
    [layoutsQuery.data]
  );

  // This person's view: the list they were last in, its grouping, their
  // filters and their order, kept for them on this collection.
  const viewSpec = useMemo(
    () => collectionViewSpec(communityId, parsedId),
    [communityId, parsedId]
  );
  const view = useListView(viewSpec);
  const listLayout =
    shown.find((layout) => layout.kind === view.layout) ??
    shown.find((layout) => layout.is_default) ??
    shown[0];
  const list = listLayout?.kind as CollectionList | undefined;
  const definition = (listLayout?.definition ?? {}) as ListLayoutDefinitionInput;

  // What the list can show of each file: its own fields, the collection's
  // metadata and the initiative's properties, each scale as the list says.
  const { data: properties = [] } = useProperties({
    initiativeId: collection?.initiative_id,
    enabled: collection !== undefined,
  });
  const allFields = useMemo(
    () => collectionFileFields(collection?.metadata ?? [], properties),
    [collection?.metadata, properties]
  );
  const fields = useMemo(
    () => withDisplays(allFields, definition.displays),
    [allFields, definition.displays]
  );
  const wall = list !== undefined && list !== "table";
  const groupByTags = view.grouping.includes("tags");
  const { setGrouping, setFilters: keepFilters, setSorting } = view;

  const [searchText, setSearchText] = useState("");
  const filters = useMemo<FileFilters>(
    () => ({ ...view.filters, ...(searchText ? { search: searchText } : {}) }),
    [view.filters, searchText]
  );
  const changeFilters = useCallback(
    ({ search: typed, ...rest }: FileFilters) => {
      setSearchText(typed ?? "");
      keepFilters(rest);
    },
    [keepFilters]
  );
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(filters.search ?? "", 300).trim();
  const tagIds = useKnownTagIds(filters.tag_ids ?? []);

  // The walls read newest or oldest first by when each file was added; the
  // table by its own columns, newest added first until one is picked.
  const [sorted] = view.sorting;
  const oldestFirst = sorted?.id === "added_at" && !sorted.desc;
  const sort =
    !wall && sorted && (TABLE_SORT_FIELDS.has(sorted.id) || COLLECTION_SORT_FIELDS.has(sorted.id))
      ? { sort_by: sorted.id, sort_dir: sorted.desc ? "desc" : "asc" }
      : { sort_by: "added_at", sort_dir: oldestFirst ? "asc" : "desc" };

  // Where the timeline has been jumped to, if anywhere. Setting it re-anchors
  // the list: a new query, so the reader lands at that month rather than
  // paging through everything since.
  const [anchor, setAnchor] = useState<{ period: string; at: string } | null>(null);
  const anchored = list === "timeline" ? anchor : null;

  const { collection_id: _within, search: _typed, tag_ids: _tags, ...narrowing } = filters;
  const params: CollectionFilesParams = {
    ...narrowing,
    ...(search ? { search } : {}),
    ...(tagIds.length > 0 ? { tag_ids: tagIds } : {}),
    ...sort,
  };
  const feed = useCollectionFilesFeed(validId, {
    ...params,
    ...(anchored ? { until: anchored.at } : {}),
  });
  // The rail is drawn without the anchor: it is the map.
  const { sort_by: _sortBy, sort_dir: _sortDir, ...narrowed } = params;
  const timelineQuery = useCollectionFilesTimeline(
    validId,
    { ...narrowed, tz: browserTimezone() },
    { enabled: list === "timeline" }
  );
  const onJump = useCallback(
    (bucket: TimelineBucket) => {
      // Which end of the month to land on is the direction the list is read
      // in: newest first the page walks back from the month's last file,
      // oldest first it walks forward from its first.
      setAnchor({
        period: bucket.period,
        at: oldestFirst ? bucket.anchor_oldest : bucket.anchor,
      });
      document.querySelector<HTMLElement>("[data-app-scroll]")?.scrollTo({ top: 0 });
    },
    [oldestFirst]
  );
  const rows = useMemo<FileRow[]>(
    () =>
      feed.data?.pages.flatMap((page) => page.items.map((file) => ({ ...file, card: null }))) ?? [],
    [feed.data]
  );
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = feed;

  // The bottom of the list asks for the next page as it comes into view.
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

  // Putting files in: dropped or uploaded, or picked from the initiative's.
  const uploader = useCollectionUploader(collection);
  const dropzoneRef = useRef<CollectionDropzoneHandle | null>(null);
  const [choosing, setChoosing] = useState(false);
  const inCollection = useMemo(() => new Set(rows.map((row) => row.id)), [rows]);
  const addFile = useAddCollectionFiles(parsedId, {
    onSuccess: () => {
      toast.success(t("collections.fileAdded"));
      setChoosing(false);
    },
  });
  useRegisterPrimaryCreateAction(
    canEdit ? { run: () => setChoosing(true), label: t("collections.addFiles") } : null
  );

  const update = useUpdateCollection(parsedId);
  const [trashing, setTrashing] = useState(false);
  const trash = useDeleteCollection({
    onSuccess: () => {
      toast.success(t("collections.trashed"));
      void navigate({ to: filesRoute });
    },
  });

  // Selecting files. The same click either opens a file or takes it into the
  // selection, depending which the list is doing.
  const selection = useGridSelection<ToolIndexRow>(rows);
  const selecting = selection.active;
  const { selectedIds } = selection;
  const isSelected = useCallback((file: FileSummary) => selectedIds.has(file.id), [selectedIds]);

  const remove = useRemoveCollectionFiles(parsedId, {
    onSuccess: (_data, fileIds) => {
      selection.exit();
      // With its last file gone the collection goes to the trash, and with the
      // last one this reader could see it is out of their reach either way.
      if (collection && fileIds.length >= collection.file_count) {
        toast.success(t("collections.emptied"));
        void navigate({ to: filesRoute });
        return;
      }
      toast.success(t("collections.removed", { count: fileIds.length }));
    },
  });

  // Pictures open in the lightbox over the wall, by id rather than by index,
  // so a page arriving underneath does not swap the one somebody is looking
  // at. Any other file opens on its own page.
  const pictures = useMemo(() => rows.filter((row) => row.kind === FileKind.image), [rows]);
  const [openId, setOpenId] = useState<number | null>(null);
  const openIndex = openId === null ? -1 : pictures.findIndex((file) => file.id === openId);
  const fileRoute = useCallback(
    (file: FileSummary) => gp(toolDetailRoute(Tool.file, file.initiative_id, file.id)),
    [gp]
  );
  // Any other file, where the collection has metadata, opens beside the
  // wall with its values there, and from there on its own page.
  const [besideId, setBesideId] = useState<number | null>(null);
  const besideFile = rows.find((row) => row.id === besideId);
  const hasMetadata = (collection?.metadata.length ?? 0) > 0;
  // A file beside the wall, or under a picture, is drawn as the collection's
  // file detail lays it out, measured against where it is drawn.
  const fileLayout = detailLayoutOf(layoutsQuery.data, "file") as StoredRegions | null;
  const fileContext = useMemo(() => (collection ? { collection } : null), [collection]);
  const drawFile = (file: FileRow) =>
    fileContext ? (
      <div className="@container">
        <DetailLayoutView
          detail={FILE_DETAIL}
          item={file}
          layout={fileLayout}
          context={fileContext}
        />
      </div>
    ) : null;
  const onActivate = useCallback(
    (file: FileSummary, options: GridToggleOptions) => {
      if (selection.active) selection.toggle(file as FileRow, options);
      else if (file.kind === FileKind.image) setOpenId(file.id);
      else if (hasMetadata) setBesideId(file.id);
      else void navigate({ to: fileRoute(file) });
    },
    [selection.active, selection.toggle, navigate, fileRoute, hasMetadata]
  );
  // A table row's name opens it as the walls do, once the collection has
  // metadata of its own; until then it goes to the file's page.
  const openRow = useCallback((row: ToolIndexRow) => onActivate(row as FileRow, {}), [onActivate]);
  const lightboxItems = useMemo<LightboxItem[]>(
    () =>
      pictures.map((file) => ({
        id: file.id,
        src: resolveUploadUrl(file.file_url) ?? "",
        alt: file.name,
        caption: (
          <span className="inline-flex flex-wrap items-center justify-center gap-x-2">
            <span>{file.name}</span>
            <RelativeTime date={file.created_at} className="text-white/60" />
          </span>
        ),
      })),
    [pictures]
  );
  const onNearEnd = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const lightboxFile = openIndex >= 0 ? pictures[openIndex] : undefined;

  const { property_filters: propertyFilters, ...narrowedBy } = filters;
  const activeFilterCount =
    Object.values(narrowedBy).filter((value) =>
      Array.isArray(value)
        ? value.length > 0
        : typeof value === "string"
          ? value.trim()
          : value != null
    ).length +
    (propertyFilters ? 1 : 0) +
    (oldestFirst ? 1 : 0);

  if (validId === null || collectionQuery.isError) {
    return (
      <ToolAccessStatus
        error={collectionQuery.error}
        keys="files:collections."
        backTo={filesRoute}
        backLabel={t("collections.backToFiles")}
      />
    );
  }

  const listOptions = shown.map((layout) => ({
    value: layout.kind as CollectionList,
    label: t(listLayoutLooks[layout.kind].labelKey as never),
    icon: listLayoutLooks[layout.kind].icon,
  }));

  return (
    <div className="space-y-6">
      {collection ? (
        <ToolPageHeader
          tool={Tool.file}
          initiativeId={collection.initiative_id}
          chest={
            <ToolChest
              tool={Tool.file}
              entity={collection}
              kind={{
                archivable: "collection",
                properties: propertySaves[PropertyTarget.collection],
                saveTags: (ids) => update.mutateAsync({ tag_ids: ids }),
              }}
            />
          }
          title={collection.name}
          onRename={canEdit ? (name) => update.mutateAsync({ name }) : undefined}
        >
          {collection.description ? (
            <p className="max-w-prose text-muted-foreground">{collection.description}</p>
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
        view={
          list && listOptions.length > 1
            ? {
                value: list,
                onChange: (next) => view.rememberLayout(next),
                options: listOptions,
                label: t("collections.views.label"),
              }
            : undefined
        }
        trailing={
          list === "masonry" || list === "grid" ? (
            <Button
              // The same shape as the filter button beside it: outline when
              // off, secondary when on, label hidden on a narrow row.
              variant={groupByTags ? "secondary" : "outline"}
              size="sm"
              className="h-9 gap-2"
              aria-pressed={groupByTags}
              aria-label={t("collections.groupByTag")}
              onClick={() => setGrouping(groupByTags ? [] : ["tags"])}
            >
              <Tags className="h-4 w-4" />
              <span className="hidden sm:inline">{t("collections.groupByTag")}</span>
            </Button>
          ) : null
        }
        onEnterSelection={!selecting && rows.length > 0 ? selection.enter : undefined}
        actions={
          canEdit ? (
            <Button variant="outline" size="sm" className="h-9" onClick={() => setChoosing(true)}>
              <Plus className="h-4 w-4" />
              {t("collections.addFiles")}
            </Button>
          ) : null
        }
        menuItems={
          canEdit || layoutsQuery.data?.can_configure ? (
            <>
              {canEdit ? (
                <DropdownMenuItem onSelect={() => dropzoneRef.current?.open()}>
                  <Upload className="h-4 w-4" />
                  {t("collections.uploadFiles")}
                </DropdownMenuItem>
              ) : null}
              {layoutsQuery.data?.can_configure && collection ? (
                <DropdownMenuItem
                  onSelect={() =>
                    void navigate({
                      to: gp(`${collectionRoute(collection.initiative_id, collection.id)}/layouts`),
                    })
                  }
                >
                  <LayoutsIcon className="h-4 w-4" />
                  {t("layouts:tab")}
                </DropdownMenuItem>
              ) : null}
              {canEdit ? (
                <DropdownMenuItem onSelect={() => setTrashing(true)}>
                  <Trash2 className="h-4 w-4" />
                  {t("collections.trash")}
                </DropdownMenuItem>
              ) : null}
            </>
          ) : null
        }
      />

      <ToolFilterPanel
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        onClear={() => {
          changeFilters({});
          setSorting([]);
        }}
        activeCount={activeFilterCount}
      >
        <ToolFilterFields
          tool={Tool.file}
          value={filters}
          onChange={changeFilters}
          initiativeId={collection?.initiative_id}
        >
          {wall ? (
            <div className="w-full space-y-2 sm:w-44">
              <Label
                htmlFor="collection-order"
                className="block font-medium text-muted-foreground text-xs"
              >
                {t("collections.order")}
              </Label>
              <Select
                value={oldestFirst ? "oldest" : "newest"}
                onValueChange={(next) => {
                  setSorting(next === "oldest" ? OLDEST_FIRST : []);
                  // An anchor names one end of a month, and which end depends
                  // on the direction: turning the list around releases it.
                  setAnchor(null);
                }}
              >
                <SelectTrigger id="collection-order">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="newest">{t("collections.newestFirst")}</SelectItem>
                  <SelectItem value="oldest">{t("collections.oldestFirst")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </ToolFilterFields>
      </ToolFilterPanel>

      <BulkAccessSection
        selection={selection}
        tool={Tool.file}
        invalidate={() => void feed.refetch()}
        actions={
          canEdit ? (
            <Button
              variant="outline"
              size="sm"
              disabled={selection.selectedItems.length === 0 || remove.isPending}
              onClick={() => remove.mutate(selection.selectedItems.map((row) => row.id))}
            >
              {remove.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              {t("collections.removeFrom")}
            </Button>
          ) : null
        }
      />

      <UploadProgress
        jobs={uploader.jobs}
        total={uploader.total}
        done={uploader.done}
        failed={uploader.failed}
        active={uploader.active}
        onDismiss={uploader.dismiss}
      />

      {collection ? (
        <HiddenFilesRequest
          hidden={collection.hidden_files}
          target={{ collection_id: collection.id }}
        />
      ) : null}

      {anchored ? (
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
          <span>{t("common:timeline.jumpedTo", { period: formatPeriod(anchored.period) })}</span>
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setAnchor(null)}>
            {t("common:timeline.backToLatest")}
          </Button>
        </div>
      ) : null}

      <CollectionDropzone
        ref={dropzoneRef}
        enabled={canEdit && !choosing}
        onFiles={uploader.enqueue}
        className="min-h-40 rounded-xl"
      >
        {feed.isLoading || layoutsQuery.isLoading ? (
          <SkeletonRegion label={t("collections.loadingFiles")}>
            <CardGridSkeleton count={8} className="grid grid-cols-fill-36/4 gap-3" />
          </SkeletonRegion>
        ) : feed.isError ? (
          <p className="text-destructive text-sm">{t("loadError")}</p>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-8 text-center">
            <p className="font-medium">
              {activeFilterCount > 0 ? t("filters.noMatchingFiles") : t("collections.noFiles")}
            </p>
            {canEdit && activeFilterCount === 0 ? (
              <>
                <p className="max-w-md text-muted-foreground text-sm">
                  {t("collections.noFilesDescription")}
                </p>
                <Button onClick={() => setChoosing(true)}>
                  <Plus className="h-4 w-4" />
                  {t("collections.addFiles")}
                </Button>
              </>
            ) : null}
          </div>
        ) : list ? (
          <CollectionListView
            kind={list}
            definition={definition}
            fields={fields}
            files={rows}
            groupByTags={groupByTags}
            buckets={timelineQuery.data?.buckets}
            onJump={onJump}
            onActivate={onActivate}
            selecting={selecting}
            isSelected={isSelected}
            table={(columns) => (
              <ToolIndexTable
                tool={Tool.file}
                initiativeId={initiativeId ?? 0}
                rows={rows}
                laidOut={columns}
                onOpen={hasMetadata ? openRow : undefined}
                selection={selection}
                sorting={view.sorting}
                onSortingChange={setSorting}
                columnVisibility={view.columns}
                onColumnVisibilityChange={view.setColumns}
              />
            )}
          />
        ) : null}
        <div ref={sentinelRef} className="h-px" />
        {isFetchingNextPage ? (
          <div className="flex justify-center py-4">
            <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
          </div>
        ) : null}
      </CollectionDropzone>

      {/* A shelf, like a project's: a collection's links are browsed along
          rather than read down. Files answer for the cache a link refreshes. */}
      <ToolRelationsPanel
        tool={Tool.file}
        entity={collection}
        target={{ type: SearchEntityType.collection, id: parsedId }}
        canEdit={canEdit}
        entityTitle={collection?.name}
      />

      {collection ? (
        <ToolCommentsPanel
          tool={Tool.file}
          entity={collection}
          target={{ type: "collection", id: collection.id }}
        />
      ) : null}

      <Lightbox
        open={openIndex >= 0}
        onOpenChange={(next) => {
          if (!next) setOpenId(null);
        }}
        items={lightboxItems}
        index={Math.max(openIndex, 0)}
        onIndexChange={(index) => setOpenId(pictures[index]?.id ?? null)}
        onNearEnd={onNearEnd}
        panel={lightboxFile && hasMetadata ? drawFile(lightboxFile) : undefined}
        actions={
          lightboxFile ? (
            <Button
              asChild
              variant="ghost"
              size="sm"
              className="text-white hover:bg-white/10 hover:text-white"
            >
              <Link to={fileRoute(lightboxFile)}>
                <ExternalLink className="size-4" />
                {t("collections.openFile")}
              </Link>
            </Button>
          ) : null
        }
      />

      <Sheet
        open={besideFile !== undefined}
        onOpenChange={(next) => {
          if (!next) setBesideId(null);
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-md" aria-describedby={undefined}>
          {/* The detail draws the file's name where its layout puts it. */}
          <SheetHeader className="sr-only">
            <SheetTitle>{besideFile?.name}</SheetTitle>
          </SheetHeader>
          {besideFile ? (
            // Below the close button, which the name would otherwise run under.
            <div className="space-y-4 pt-6">
              {drawFile(besideFile)}
              <Button asChild variant="outline" size="sm">
                <Link to={fileRoute(besideFile)}>
                  <ExternalLink className="size-4" />
                  {t("collections.openFile")}
                </Link>
              </Button>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>

      {collection ? (
        <FileChooserDialog
          initiativeId={collection.initiative_id}
          exclude={inCollection}
          open={choosing}
          onOpenChange={setChoosing}
          onPick={(fileId) => addFile.mutate([fileId])}
          pending={addFile.isPending}
          text={{
            title: t("collections.addFiles"),
            description: t("collections.pickFile"),
            none: t("collections.noFilesToAdd"),
          }}
        />
      ) : null}

      <ConfirmDialog
        open={trashing}
        onOpenChange={setTrashing}
        title={t("collections.trashTitle")}
        description={t("collections.trashDescription")}
        confirmLabel={t("collections.trash")}
        cancelLabel={t("common:cancel")}
        isLoading={trash.isPending}
        destructive
        onConfirm={() => trash.mutate(parsedId)}
      />
    </div>
  );
}

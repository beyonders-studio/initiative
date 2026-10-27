/**
 * THE index page a tool's entities are browsed from — one initiative's shelf of
 * projects, files, wikis, libraries, queues, counter groups or dashboards.
 *
 * Each of those pages carried its own copy of the same thing: the view toggle,
 * the filter panel, the create button and its dialog, the loading, error,
 * narrowed and empty states, the card grid, and bulk selection. What a tool
 * actually contributes is narrow — which list it reads, what a row looks like,
 * the handful of keys it spells its own way, and the few things only some
 * tools do (a dialog of their own, files dropped on the list, a table, an order
 * of the reader's own) — and that is what {@link TOOL_INDEX} carries. It is a
 * `Record<Tool, …>`, so a new tool cannot arrive without saying either how it
 * lists or what it does instead.
 *
 * Everything else is derived rather than declared per tool, the way
 * `lib/tools.ts` asks: the views read the registry's view specs, the import
 * action its exportable set, the marketplace button its listing kinds, the
 * bulk actions its hooks, and the field ids and routes come from the tool's own
 * spelling rules.
 */

import type { UseQueryResult } from "@tanstack/react-query";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import type { FlatNamespace } from "i18next";
import { LayoutGrid, List, Plus, Tags } from "lucide-react";
import {
  type ComponentType,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { type PropertySummary, type TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import type { BulkAccessItem } from "@/components/access/BulkEditAccessDialog";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { BookmarkButton } from "@/components/BookmarkButton";
import { CreateFileDialog } from "@/components/files/CreateFileDialog";
import { FileCard } from "@/components/files/FileCard";
import { useFileColumns } from "@/components/files/fileColumns";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import { CounterGroupCard } from "@/components/initiativeTools/counters/CounterGroupCard";
import { DashboardCard } from "@/components/initiativeTools/dashboards/DashboardCard";
import { LibraryCard } from "@/components/initiativeTools/libraries/LibraryCard";
import { QueueCard } from "@/components/initiativeTools/queues/QueueCard";
import { CreateToolDialog } from "@/components/initiativeTools/shared/CreateToolDialog";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { ToolViewFilter } from "@/components/initiativeTools/shared/ToolViewFilter";
import { WikiCard } from "@/components/initiativeTools/wikis/WikiCard";
import {
  BrowseMarketplaceButton,
  BrowseMarketplaceMenuItem,
} from "@/components/marketplace/BrowseMarketplaceButton";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { PaginationBar } from "@/components/PaginationBar";
import { CreateProjectDialog } from "@/components/projects/CreateProjectDialog";
import { ProjectCard } from "@/components/projects/ProjectCard";
import { useProjectColumns } from "@/components/projects/projectColumns";
import { parsePropertyFilters } from "@/components/properties/PropertyFilter";
import { CardGridSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { TagBrowseLayout } from "@/components/tags/TagBrowseLayout";
import {
  readToolListFilters,
  ToolFilterFields,
  type ToolListFilters,
} from "@/components/tools/ToolFilterFields";
import { SortableCards } from "@/components/tools/ToolIndexSortable";
import {
  TABLE_SORT_FIELDS,
  ToolIndexTable,
  toolTableStorageKey,
} from "@/components/tools/ToolIndexTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DropOverlay } from "@/components/ui/file-drop";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useFileDrop } from "@/hooks/useFileDrop";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import {
  deviceJSON,
  LIST,
  type ListViewSpec,
  NO_PART_VIEW,
  useListView,
  viewKey,
} from "@/hooks/useListView";
import { useReorderProjects } from "@/hooks/useProjects";
import { useKnownTagIds } from "@/hooks/useTags";
import { useTagTreeSelection } from "@/hooks/useTagTreeSelection";
import { useToolCounts } from "@/hooks/useToolCounts";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import type { AppColumnDef } from "@/lib/table";
import {
  isToolView,
  TOOL_ICONS,
  type ToolView,
  type ToolViewParams,
  toolCamelPlural,
  toolDetailRoute,
  toolListingKind,
  toolRouteSegment,
  toolViewParams,
  toolViews,
} from "@/lib/tools";
import type { DialogProps } from "@/types/dialog";
import type { TranslateFn } from "@/types/i18n";

// ---------------------------------------------------------------------------
// What a tool contributes
// ---------------------------------------------------------------------------

/**
 * One row, as the shared page needs it: enough to key it, label it, select it
 * and share it — plus the card its own tool drew for it.
 *
 * Drawing happens inside the tool's list hook, where the row's real type is
 * known, so no tool's schema has to travel through this file.
 */
export type ToolIndexRow = BulkAccessItem & {
  name: string;
  updated_at: string;
  /** Drawn on the row in the list view; every listed tool's rows carry them. */
  tags?: TagSummary[];
  /** The initiative's properties, as the table's property columns read them. */
  properties?: PropertySummary[];
  card: ReactNode;
};

type ToolIndexLayout = "grid" | "list" | "tags";
const isLayout = (value: unknown): value is ToolIndexLayout =>
  value === "grid" || value === "list" || value === "tags";

/** How the shared page has narrowed the list, handed to the tool's list hook. */
export type ToolIndexFilters = {
  /**
   * The tool's filter fields, as its list endpoint takes them: the search
   * after a beat's pause, so a keystroke is not a request, and nothing for a
   * field left empty. `untagged` only for a tool whose entry says it has it.
   */
  list: ToolListFilters & { untagged?: true };
  /** What the view being shown asks the list for (`toolViewParams`). */
  view: ToolViewParams;
  /** The order the reader picked in a tool's table; empty for the others. */
  sort: { sort_by?: string; sort_dir?: "asc" | "desc" };
  /** The page and its size, for a tool whose list is paged. */
  page: number;
  pageSize: number;
};

/** What a tool's list hook hands back. */
export type ToolIndexList = {
  rows: ToolIndexRow[];
  isLoading: boolean;
  isError: boolean;
  /** The rows are the previous request's, shown while this one loads. */
  isPlaceholderData: boolean;
  /** Rows the server holds for this archive state — what the pager counts. */
  totalCount: number;
  hasNext: boolean;
};

/** Everything one tool adds to the shared page. */
export type ToolIndexEntry = {
  /** Reads this tool's list and draws its cards. */
  useList: (initiativeId: number, filters: ToolIndexFilters) => ToolIndexList;
  /**
   * The keys this tool spells its own way — the page's and its create
   * dialog's. Kept per tool rather than folded into one generic string: "No
   * counter groups match your filters" is written in four locales already, and
   * a shared wording would be a fifth thing to translate that says less.
   * They are in the tool's own namespace, `toolCamelPlural(tool)`.
   */
  text: {
    /** Title of the create button, the bottom-nav action, and the dialog. */
    create: string;
    /** The line under the shared create dialog's title. */
    createDescription?: string;
    noMatches: string;
    emptyTitle: string;
    emptyBody: string;
  };
  /** The tool's card draws its bookmark among controls of its own, so the list
   *  puts none on its corner. */
  cardHasBookmark?: true;
  /** The layout a reader starts on, before they pick one. Cards otherwise. */
  defaultLayout?: ToolIndexLayout;
  /** Cards are small tiles, several to a row, rather than three across. */
  tiles?: true;
  /** A create dialog of the tool's own, for a tool made from more than a name. */
  CreateDialog?: ComponentType<ToolIndexCreateDialogProps>;
  /** Files dropped anywhere on the list open the create dialog holding the
   *  first; `label` is the overlay's key in the tool's namespace. */
  fileDrop?: { label: string };
  /** The list layout as a sortable table, with these columns after the shared
   *  ones. Without it the list layout is one line a row. */
  table?: { useColumns: () => AppColumnDef<ToolIndexRow>[] };
  /** The list can be narrowed to rows with no tag, which the tag tree offers. */
  untagged?: true;
  /**
   * The reader keeps an order of their own, which is the list's order until
   * they pick one in the table, and drag the cards to change it. The mutation
   * is handed the ids of the rows the list starts with, in their new order;
   * the rest keep their place after them.
   */
  reorder?: {
    useReorder: () => { mutate: (orderedIds: number[], options?: ReorderOptions) => void };
  };
};

/** What the page asks of a reorder it sends. */
type ReorderOptions = { onError?: () => void };

/** The hook a tool without an order of its own calls in its place. */
const useNoReorder = () => null;

/** What a tool's own create dialog is handed. */
export type ToolIndexCreateDialogProps = DialogProps & {
  initiativeId: number;
  onSuccess: (created: { id: number }) => void;
  /** A file dropped on the list; the dialog opens holding it. */
  initialFile: File | null;
};

/** A tool that is not browsed as a grid of cards, and what it is instead. */
type ToolIndexOwnPage = { ownPage: string };

const isOwnPage = (entry: ToolIndexEntry | ToolIndexOwnPage): entry is ToolIndexOwnPage =>
  "ownPage" in entry;

/** This page's entry for a tool, or null when the tool has a page of its own. */
export const toolIndexEntry = (tool: Tool): ToolIndexEntry | null => {
  const entry = TOOL_INDEX[tool];
  return isOwnPage(entry) ? null : entry;
};

// ---------------------------------------------------------------------------
// Each tool's list
// ---------------------------------------------------------------------------

/** What the shared page asks every tool's list for. */
type ToolIndexParams = ToolIndexFilters["list"] &
  ToolIndexFilters["sort"] & {
    initiative_id: number;
    page: number;
    page_size: number;
    /** What each card shows of what is inside it, read with the page. */
    include_preview?: true;
  };

/** A row of any listed tool, before its card is drawn. */
type ToolIndexItem = Omit<ToolIndexRow, "card">;

/**
 * A tool's list hook, from its `TOOL_HOOKS` list and how one of its rows is
 * drawn as a card. `extra` is what the tool asks its list for beyond the
 * shared narrowing.
 */
const makeRows =
  <TItem extends ToolIndexItem>(
    useList: (
      params: ToolIndexParams
    ) => UseQueryResult<{ items: TItem[]; total_count: number; has_next: boolean }>,
    drawCard: (item: TItem) => ReactNode,
    extra?: Pick<ToolIndexParams, "include_preview">
  ) =>
  (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
    const query = useList({
      ...filters.list,
      initiative_id: initiativeId,
      ...filters.view,
      ...filters.sort,
      page: filters.page,
      page_size: filters.pageSize,
      ...extra,
    });

    const rows = useMemo(
      () => (query.data?.items ?? []).map((item) => ({ ...item, card: drawCard(item) })),
      [query.data]
    );

    return {
      rows,
      isLoading: query.isLoading,
      isError: query.isError,
      isPlaceholderData: query.isPlaceholderData,
      totalCount: query.data?.total_count ?? 0,
      hasNext: query.data?.has_next ?? false,
    };
  };

const WITH_PREVIEW = { include_preview: true } as const;

// ---------------------------------------------------------------------------
// The table
// ---------------------------------------------------------------------------

/**
 * Every tool, and how one initiative's entities of it are browsed. A tool with
 * a page of its own names it here rather than being left out, so a new tool has
 * to state which of the two it is.
 */
const TOOL_INDEX: Record<Tool, ToolIndexEntry | ToolIndexOwnPage> = {
  [Tool.calendar]: { ownPage: "CalendarsPage — a month grid, not a shelf of cards" },
  [Tool.post]: { ownPage: "PostsPage — a virtualized feed with a timeline rail" },

  [Tool.project]: {
    useList: makeRows(TOOL_HOOKS[Tool.project].useList, (project) => (
      <ProjectCard project={project} />
    )),
    text: {
      create: "addProject",
      noMatches: "noMatchingProjects",
      emptyTitle: "noProjects",
      emptyBody: "noProjectsDescription",
    },
    // Made from a template, with dates and an icon, not just a name.
    CreateDialog: CreateProjectDialog,
    // The rows are projects, which is what these columns read.
    table: { useColumns: useProjectColumns as unknown as () => AppColumnDef<ToolIndexRow>[] },
    reorder: { useReorder: useReorderProjects },
    // Beside its pin and its drag handle.
    cardHasBookmark: true,
  },

  [Tool.file]: {
    useList: makeRows(TOOL_HOOKS[Tool.file].useList, (file) => <FileCard file={file} />),
    text: {
      create: "newFile",
      noMatches: "filters.noMatchingFiles",
      emptyTitle: "noFiles",
      emptyBody: "noFilesDescription",
    },
    defaultLayout: "tags",
    tiles: true,
    // Made from a type, an upload, a link or a template, not just a name.
    CreateDialog: CreateFileDialog,
    fileDrop: { label: "dropToUpload" },
    // The rows are files, which is what these columns read.
    table: { useColumns: useFileColumns as unknown as () => AppColumnDef<ToolIndexRow>[] },
    untagged: true,
  },

  [Tool.queue]: {
    useList: makeRows(
      TOOL_HOOKS[Tool.queue].useList,
      (queue) => <QueueCard queue={queue} />,
      WITH_PREVIEW
    ),
    text: {
      create: "createQueue",
      createDescription: "noQueuesDescription",
      noMatches: "filters.noMatchingQueues",
      emptyTitle: "noQueues",
      emptyBody: "noQueuesDescription",
    },
  },

  [Tool.counter_group]: {
    useList: makeRows(
      TOOL_HOOKS[Tool.counter_group].useList,
      (group) => <CounterGroupCard group={group} />,
      WITH_PREVIEW
    ),
    text: {
      create: "createGroup",
      createDescription: "noGroupsDescription",
      noMatches: "filters.noMatchingGroups",
      emptyTitle: "noGroups",
      emptyBody: "noGroupsDescription",
    },
  },

  [Tool.dashboard]: {
    useList: makeRows(
      TOOL_HOOKS[Tool.dashboard].useList,
      (dashboard) => <DashboardCard dashboard={dashboard} />,
      WITH_PREVIEW
    ),
    text: {
      create: "createDashboard",
      createDescription: "noDashboardsDescription",
      noMatches: "filters.noMatchingDashboards",
      emptyTitle: "noDashboards",
      emptyBody: "noDashboardsDescription",
    },
  },

  [Tool.library]: {
    useList: makeRows(
      TOOL_HOOKS[Tool.library].useList,
      (library) => <LibraryCard library={library} />,
      WITH_PREVIEW
    ),
    text: {
      create: "createLibrary",
      createDescription: "createLibraryDescription",
      noMatches: "filters.noMatchingLibraries",
      emptyTitle: "noLibraries",
      emptyBody: "noLibrariesDescription",
    },
  },

  [Tool.wiki]: {
    useList: makeRows(TOOL_HOOKS[Tool.wiki].useList, (wiki) => <WikiCard wiki={wiki} />),
    text: {
      create: "createWiki",
      createDescription: "createWikiDescription",
      noMatches: "filters.noMatchingWikis",
      emptyTitle: "noWikis",
      emptyBody: "noWikisDescription",
    },
  },
};

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

/**
 * Which view and which page of the list is showing, kept in the URL so a deep
 * link lands on them and the back button walks through the ones that were read.
 */
const useListPage = (tool: Tool) => {
  const router = useRouter();
  const search = useSearch({ strict: false }) as { page?: number; status?: string };

  // Read from the click handler, so the newest URL is the one written back to.
  const searchRef = useRef(search);
  searchRef.current = search;

  // Archived rows are off the live list (and templates off it too, for a tool
  // that has them), so the view is the only place they can be reached.
  const view: ToolView =
    isToolView(search.status) && toolViews(tool).includes(search.status) ? search.status : "active";

  const [page, setPageState] = useState(() => search.page ?? 1);
  const [pageSize, setPageSize] = useState(20);

  // The cursor lives in the URL as well as in state, so a history move (Back
  // out of the archive, say) carries the list with it.
  useEffect(() => {
    const urlPage = search.page ?? 1;
    setPageState((prev) => (prev === urlPage ? prev : urlPage));
  }, [search.page]);

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setPageState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        void router.navigate({
          to: ".",
          search: { ...searchRef.current, page: next <= 1 ? undefined : next },
          replace: true,
        });
        return next;
      });
    },
    [router]
  );

  const setView = useCallback(
    (next: ToolView) => {
      // Pushed, not replaced: a view is somewhere the reader went, so Back
      // takes them out of it. The other view's cursor means nothing in this one.
      void router.navigate({
        to: ".",
        search: {
          ...searchRef.current,
          status: next === "active" ? undefined : next,
          page: undefined,
        },
      });
      setPageState(1);
    },
    [router]
  );

  return { view, setView, page, pageSize, setPage, setPageSize };
};

const NO_TAGS: number[] = [];

/** Newest first, the way a table opens until its reader picks an order. */
const NEWEST_FIRST: SortingState = [{ id: "updated_at", desc: true }];

/**
 * Where one person's view of an initiative's tool list is kept: how it is
 * drawn (cards, rows or by tag), their filters but for a typed search, and
 * the table's order and columns. What an older release kept (how each tool
 * was drawn, the same in every initiative, and the table's order and columns
 * on the device) is carried over.
 */
const toolListViewSpec = (
  tool: Tool,
  communityId: number,
  initiativeId: number,
  reorders: boolean
): ListViewSpec<ToolListFilters> => ({
  key: viewKey(communityId, "initiative", initiativeId, toolRouteSegment(tool)),
  read: readToolListFilters,
  defaults: { filters: {}, ...NO_PART_VIEW, sorting: reorders ? [] : NEWEST_FIRST },
  carryOver: (items) => {
    const layout = items[`${tool}:view-mode`];
    const order = deviceJSON(toolTableStorageKey(tool, "order")) as { sorting?: unknown } | null;
    const columns = deviceJSON(toolTableStorageKey(tool, "columns"));
    if (typeof layout !== "string" && !order && !columns) return null;
    return {
      layout: typeof layout === "string" ? layout : null,
      parts: {
        [LIST]: {
          ...(Array.isArray(order?.sorting) ? { sorting: order.sorting } : {}),
          ...(columns && typeof columns === "object" ? { columns } : {}),
        },
      },
    };
  },
});

/** The list's own narrowing, as the counts endpoint takes it for the tag tree:
 *  tags aside, since the tree counts every one. */
const countFilters = ({ tag_ids: _tags, ...narrowing }: ToolIndexFilters["list"]) => {
  const set = Object.entries(narrowing).filter(
    ([, value]) => value != null && value !== "" && !(Array.isArray(value) && value.length === 0)
  );
  return set.length > 0 ? JSON.stringify(Object.fromEntries(set)) : undefined;
};

export type ToolIndexPageProps = {
  tool: Tool;
  /** The initiative this list belongs to. Required: a tool's entities are only
   *  ever browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

type ToolIndexBodyProps = ToolIndexPageProps & { entry: ToolIndexEntry };

const ToolIndexBody = ({ tool, entry, fixedInitiativeId, canCreate }: ToolIndexBodyProps) => {
  // The namespace and most of the keys come from the table, so the loose
  // translate signature rather than the statically-typed one.
  const ns = toolCamelPlural(tool) as FlatNamespace;
  const { t: translate } = useTranslation([ns, "common", "tags"]);
  const t = translate as TranslateFn;
  const router = useRouter();
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();
  const unread = useUnreadTree();

  // This person's view of the list. A typed search is for this visit only.
  const viewSpec = useMemo(
    () => toolListViewSpec(tool, communityId, fixedInitiativeId, Boolean(entry.reorder)),
    [tool, communityId, fixedInitiativeId, entry.reorder]
  );
  const listView = useListView(viewSpec);
  const [searchText, setSearchText] = useState("");
  const filters = useMemo<ToolListFilters>(
    () => ({ ...listView.filters, ...(searchText ? { search: searchText } : {}) }),
    [listView.filters, searchText]
  );
  const { setFilters: keepFilters } = listView;
  const setFilters = useCallback(
    ({ search: typed, ...rest }: ToolListFilters) => {
      setSearchText(typed ?? "");
      keepFilters(rest);
    },
    [keepFilters]
  );
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(filters.search ?? "", 300).trim();

  const { view, setView, page, pageSize, setPage, setPageSize } = useListPage(tool);
  // How the list is drawn — cards, rows or by tag — remembered per tool.
  const defaultLayout = entry.defaultLayout ?? "grid";
  const layout: ToolIndexLayout = isLayout(listView.layout) ? listView.layout : defaultLayout;
  const setLayout = listView.rememberLayout;
  const tagTree = useTagTreeSelection(layout === "tags");

  // The order a reader picks in a tool's table outlives the visit, and is the
  // list's order in every layout. A tool that keeps the reader's own order
  // opens in it: asked for no order, the server lists in that one.
  const tableState = { sorting: listView.sorting };
  const { setSorting } = listView;
  const [sorted] = tableState.sorting;
  const sort =
    entry.table && sorted && TABLE_SORT_FIELDS.has(sorted.id)
      ? { sort_by: sorted.id, sort_dir: sorted.desc ? ("desc" as const) : ("asc" as const) }
      : {};

  const knownTagIds = useKnownTagIds(filters.tag_ids ?? NO_TAGS);
  const listFilters: ToolIndexFilters["list"] = {
    ...filters,
    search: search || undefined,
    // A tag picked in the tree narrows by it; with none picked, the
    // filter panel's tags still apply.
    tag_ids: tagTree.tagIds.length ? tagTree.tagIds : knownTagIds.length ? knownTagIds : undefined,
    ...(entry.untagged && tagTree.wantsUntagged ? { untagged: true as const } : {}),
  };
  const list = entry.useList(fixedInitiativeId, {
    list: listFilters,
    view: toolViewParams(tool, view),
    sort,
    page,
    pageSize,
  });

  // How much sits in each view, whatever the filters say; and in the tags
  // view, how much carries each tag under the list's own filters, so the tree
  // and the list beside it agree.
  const tagCountFilters = layout === "tags" ? countFilters(listFilters) : undefined;
  const countsQuery = useToolCounts(tool, {
    initiative_id: fixedInitiativeId,
    ...(layout === "tags"
      ? { view, include_tags: true, ...(tagCountFilters ? { filters: tagCountFilters } : {}) }
      : {}),
  });

  // A page past the end (its rows deleted, a link to one that is gone) has
  // nothing on it and no pager to leave by, so the list moves to its last page.
  // A failed read says nothing about where the end is, so it moves nothing.
  const lastPage = Math.max(1, Math.ceil(list.totalCount / pageSize));
  useEffect(() => {
    if (!list.isLoading && !list.isError && list.rows.length === 0 && page > lastPage) {
      setPage(lastPage);
    }
  }, [list.isLoading, list.isError, list.rows.length, page, lastPage, setPage]);

  // Canonical create answer: this initiative's server-computed create flag. An
  // explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateDerived } = useToolCreateAccess(tool, {
    initiativeId: fixedInitiativeId,
  });
  // Nothing is made into the archive: its view offers no way to create.
  const canCreateHere = (canCreate ?? canCreateDerived) && view !== "archived";

  const {
    open: createOpen,
    setOpen: setCreateOpen,
    onOpenChange: handleCreateOpenChange,
  } = useCreateFromSearchParam();

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateHere ? { run: () => setCreateOpen(true), label: t(entry.text.create) } : null
  );

  const selection = useGridSelection<ToolIndexRow>(list.rows);

  const useReorder = entry.reorder?.useReorder ?? useNoReorder;
  const reorder = useReorder();
  // The order the reader just dragged the cards into, shown until the list is
  // read again in it, or the move is refused.
  const [moved, setMoved] = useState<{ from: ToolIndexRow[]; rows: ToolIndexRow[] } | null>(null);
  const orderedRows = moved?.from === list.rows ? moved.rows : list.rows;
  const reorderRows = (orderedIds: number[]) => {
    const byId = new Map(orderedRows.map((row) => [row.id, row]));
    setMoved({ from: list.rows, rows: orderedIds.flatMap((id) => byId.get(id) ?? []) });
    reorder?.mutate(orderedIds, { onError: () => setMoved(null) });
  };
  // Another view or layout must not strand a hidden selection behind the bulk
  // actions — every change starts unselected.
  const exitSelection = selection.exit;
  useEffect(() => {
    exitSelection();
  }, [view, layout, exitSelection]);

  const importAction = useToolImportAction({
    tool,
    canImport: canCreateHere,
    fixedInitiativeId,
  });

  // A file dragged in from the desktop lands wherever the cursor is, in any
  // layout, and opens the create dialog holding it. Off while a dialog is up:
  // those are portalled, and React would carry a drop on one back up to here.
  const [droppedFile, setDroppedFile] = useState<File | null>(null);
  const drop = useFileDrop(
    Boolean(entry.fileDrop) && canCreateHere && !createOpen && !selection.active,
    ([first]) => {
      if (!first) return;
      setDroppedFile(first);
      setCreateOpen(true);
    }
  );
  const onCreateOpenChange = (open: boolean) => {
    if (!open) setDroppedFile(null);
    handleCreateOpenChange(open);
  };
  const openCreated = (created: { id: number }) => {
    void router.navigate({ to: gp(toolDetailRoute(tool, fixedInitiativeId, created.id)) });
  };

  // Counted from the fields as set rather than from the debounced search, so
  // the badge and "Clear all" answer the keystroke instead of trailing it.
  // Each property condition counts as a filter of its own.
  const { property_filters: propertyFilters, ...fields } = filters;
  const activeFilterCount =
    Object.values(fields).filter((value) =>
      Array.isArray(value)
        ? value.length > 0
        : typeof value === "string"
          ? value.trim()
          : value != null
    ).length + parsePropertyFilters(propertyFilters).length;

  // The reader's own order covers the whole list, and a drop sends the list's
  // opening rows: so only the live list, in that order, unnarrowed, on its
  // first page, and not while picking rows out of it. Unnarrowed as asked for
  // and as shown: a cleared search is still the debounced one, and its rows
  // stay on screen until the full list arrives.
  const draggable =
    reorder !== null &&
    view === "active" &&
    !sort.sort_by &&
    page === 1 &&
    activeFilterCount === 0 &&
    !search &&
    !list.isPlaceholderData &&
    tagTree.selectedPaths.size === 0 &&
    !selection.active;

  const ToolIcon = TOOL_ICONS[tool];
  const cardGrid = entry.tiles
    ? layout === "tags"
      ? "grid grid-cols-fill-36/4 gap-4"
      : "grid grid-cols-fill-36/5 gap-4"
    : "grid grid-cols-fill-60/3 gap-4";
  // The list's own marks on a card's top corner, outside the card's link: the
  // bookmark (unless the card draws its own), and the unread dot in the corner
  // itself.
  const cardOf = (row: ToolIndexRow) => (
    <div className="relative">
      {row.card}
      {entry.cardHasBookmark ? null : (
        <BookmarkButton
          tool={tool}
          entityId={row.id}
          name={row.name}
          initiativeId={row.initiative_id}
          iconSize="sm"
          suppressNavigation
          className="absolute top-4 right-6 z-10 bg-card/80 backdrop-blur-sm"
        />
      )}
      {unread.hasResource(communityId, tool, row.id) ? (
        <UnreadDot className="absolute top-3 right-3" />
      ) : null}
    </div>
  );
  // The cards, as the grid and the tags view both draw them.
  const cards = draggable ? (
    <SortableCards
      items={orderedRows.map((row) => ({ id: row.id, card: cardOf(row) }))}
      onReorder={reorderRows}
      className={cardGrid}
    />
  ) : (
    <div className={cardGrid}>
      {orderedRows.map((row) => (
        <SelectableGridItem
          key={row.id}
          active={selection.active}
          selected={selection.selectedIds.has(row.id)}
          onToggle={(options) => selection.toggle(row, options)}
          label={row.name}
        >
          {cardOf(row)}
        </SelectableGridItem>
      ))}
    </div>
  );

  // A narrower list may not reach the page being read.
  const changeFilters = (next: ToolListFilters) => {
    setFilters(next);
    if (page !== 1) setPage(1);
  };

  return (
    <div className="relative space-y-6" {...drop.handlers}>
      {drop.dragging && entry.fileDrop ? (
        <DropOverlay label={t(entry.fileDrop.label)} tall />
      ) : null}
      <ToolListToolbar
        leading={
          <ToolViewFilter
            tool={tool}
            value={view}
            counts={countsQuery.data?.views}
            onChange={setView}
          />
        }
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        actions={
          canCreateHere ? (
            <Button size="sm" className="h-9" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t(entry.text.create)}
            </Button>
          ) : null
        }
        view={{
          value: layout,
          onChange: (next) => {
            setLayout(next);
            setPage(1);
          },
          options: [
            { value: "grid", label: t("common:toolbar.viewGrid"), icon: LayoutGrid },
            { value: "list", label: t("common:toolbar.viewList"), icon: List },
            { value: "tags", label: t("common:toolbar.viewTags"), icon: Tags },
          ],
          label: t("common:toolbar.view"),
        }}
        menuItems={
          (canCreateHere && toolListingKind(tool)) || importAction.menuItem ? (
            <>
              {canCreateHere ? <BrowseMarketplaceMenuItem tool={tool} /> : null}
              {importAction.menuItem}
            </>
          ) : null
        }
        onEnterSelection={!selection.active && list.rows.length > 0 ? selection.enter : undefined}
      />
      {importAction.dialog}

      <ToolFilterPanel
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        onClear={() => changeFilters({})}
        activeCount={activeFilterCount}
      >
        <ToolFilterFields
          tool={tool}
          value={filters}
          onChange={changeFilters}
          initiativeId={fixedInitiativeId}
        />
      </ToolFilterPanel>

      {list.isLoading ? (
        <SkeletonRegion label={t("loading")}>
          <CardGridSkeleton />
        </SkeletonRegion>
      ) : list.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : list.rows.length > 0 ||
        (layout === "tags" && (tagTree.selectedPaths.size > 0 || activeFilterCount > 0)) ? (
        // In the tags view a narrowed list that matches nothing keeps the tree
        // on screen, so another tag can be picked or the pick undone.
        <>
          <BulkAccessSection
            selection={selection}
            tool={tool}
            invalidate={() => invalidate(q.toolList(tool))}
          />
          {layout === "tags" ? (
            <TagBrowseLayout
              allTags={tagTree.allTags}
              tagCounts={countsQuery.data?.tag_counts ?? {}}
              untaggedCount={entry.untagged ? (countsQuery.data?.untagged_count ?? 0) : undefined}
              selectedPaths={tagTree.selectedPaths}
              onToggleTag={(path, ctrlKey) => {
                tagTree.toggle(path, ctrlKey);
                setPage(1);
              }}
            >
              {list.rows.length > 0 ? (
                cards
              ) : (
                <p className="py-8 text-center text-muted-foreground text-sm">
                  {t(entry.text.noMatches)}
                </p>
              )}
            </TagBrowseLayout>
          ) : layout === "list" && entry.table ? (
            <ToolIndexTable
              tool={tool}
              initiativeId={fixedInitiativeId}
              rows={list.rows}
              useColumns={entry.table.useColumns}
              selection={selection}
              sorting={tableState.sorting}
              onSortingChange={(next) => {
                setSorting(next);
                setPage(1);
              }}
              columnVisibility={listView.columns}
              onColumnVisibilityChange={listView.setColumns}
            />
          ) : layout === "list" ? (
            <ul className="divide-y rounded-lg border">
              {list.rows.map((row) => (
                <li key={row.id}>
                  <SelectableGridItem
                    active={selection.active}
                    selected={selection.selectedIds.has(row.id)}
                    onToggle={(options) => selection.toggle(row, options)}
                    label={row.name}
                  >
                    <div className="flex items-center hover:bg-accent/50">
                      <Link
                        to={gp(toolDetailRoute(tool, row.initiative_id, row.id))}
                        className="flex min-w-0 flex-1 items-center gap-3 py-2.5 pl-3"
                      >
                        <ToolIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                        <span className="min-w-0 truncate font-medium text-sm">{row.name}</span>
                        {unread.hasResource(communityId, tool, row.id) ? <UnreadDot /> : null}
                        <span className="flex-1" />
                        {row.tags?.length ? (
                          <TagBadgeList tags={row.tags} limit={3} nested className="shrink-0" />
                        ) : null}
                      </Link>
                      {/* Beside the row's link rather than in it. */}
                      <BookmarkButton
                        tool={tool}
                        entityId={row.id}
                        name={row.name}
                        initiativeId={row.initiative_id}
                        iconSize="sm"
                        className="mx-1.5"
                      />
                    </div>
                  </SelectableGridItem>
                </li>
              ))}
            </ul>
          ) : (
            cards
          )}

          <PaginationBar
            page={page}
            pageSize={pageSize}
            totalCount={list.totalCount}
            hasNext={list.hasNext}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      ) : activeFilterCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t(entry.text.noMatches)}</p>
      ) : view !== "active" ? (
        // Nothing is made here: rows arrive in the archive when they are put
        // away, and a template is made by marking an existing one as one.
        <Card>
          <CardHeader>
            <CardTitle>
              {t(
                view === "archived"
                  ? "common:toolIndex.emptyArchivedTitle"
                  : "common:toolIndex.emptyTemplatesTitle"
              )}
            </CardTitle>
            <CardDescription>
              {t(
                view === "archived"
                  ? "common:toolIndex.emptyArchivedBody"
                  : "common:toolIndex.emptyTemplatesBody"
              )}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t(entry.text.emptyTitle)}</CardTitle>
            <CardDescription>{t(entry.text.emptyBody)}</CardDescription>
          </CardHeader>
          {/* The other ways to end up with one, said where the answer is
              needed: an initiative with none of them yet. Each reads the
              registry and shows nothing for a tool it does not apply to. */}
          <CardContent className="flex flex-wrap gap-2">
            <Button onClick={() => setCreateOpen(true)} disabled={!canCreateHere}>
              <Plus className="h-4 w-4" />
              {t("createFirst")}
            </Button>
            <ToolImportAction
              tool={tool}
              canImport={canCreateHere}
              fixedInitiativeId={fixedInitiativeId}
              variant="button"
            />
            {canCreateHere ? <BrowseMarketplaceButton tool={tool} /> : null}
          </CardContent>
        </Card>
      )}

      {entry.CreateDialog ? (
        <entry.CreateDialog
          open={createOpen}
          onOpenChange={onCreateOpenChange}
          initiativeId={fixedInitiativeId}
          onSuccess={openCreated}
          initialFile={droppedFile}
        />
      ) : (
        <CreateToolDialog
          open={createOpen}
          onOpenChange={handleCreateOpenChange}
          tool={tool}
          text={{ ...entry.text, ns }}
          initiativeId={fixedInitiativeId}
          onSuccess={openCreated}
        />
      )}
    </div>
  );
};

export const ToolIndexPage = ({ tool, ...rest }: ToolIndexPageProps) => {
  const entry = TOOL_INDEX[tool];
  // A tool with a page of its own is never routed here; the table names which
  // those are.
  if (isOwnPage(entry)) return null;

  // Keyed on the tool: the table supplies the list hook, so a different tool is
  // a different set of hooks. Remounting is what makes that sound — and it is
  // also what somebody switching tabs expects, filters and all.
  return <ToolIndexBody key={tool} tool={tool} entry={entry} {...rest} />;
};

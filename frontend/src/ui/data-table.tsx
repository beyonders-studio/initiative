"use client";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  flexRender,
  type GroupingState,
  type PaginationState,
  type RowData,
  type RowSelectionState,
  type SortingState,
  type TableState as TableStateOf,
  useTable,
} from "@tanstack/react-table";
import { ChevronDown, MoreVertical } from "lucide-react";
import {
  Fragment,
  memo,
  type ReactNode,
  type UIEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import {
  type AppColumnDef,
  type AppRow,
  type AppTable,
  type AppTableFeatures,
  appTableFeatures,
} from "@/ui/lib/table";
import { cn } from "@/ui/lib/utils";
import { PaginationBar } from "@/ui/pagination-bar";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";
import { useVirtualRows } from "@/ui/virtual-rows";

type TableState = TableStateOf<AppTableFeatures>;

export interface GroupingOption {
  id: string;
  label: string;
}

interface DataTableProps<TData extends RowData> {
  columns: AppColumnDef<TData>[];
  data: TData[];
  rowWrapper?: (props: DataTableRowWrapperProps<TData>) => ReactNode;
  /** Wraps a group's header row, as ``rowWrapper`` does a row: it renders the
   *  row element around ``children``. */
  groupRowWrapper?: (props: DataTableRowWrapperProps<TData>) => ReactNode;
  enableFilterInput?: boolean;
  filterInputPlaceholder?: string;
  filterInputColumnKey?: string;
  /**
   * Controlled search text. Passing ``onFilterValueChange`` hands the box to
   * the caller: it stops filtering the rows already loaded and reports what
   * was typed instead, which is how a table whose rows arrive a server page at
   * a time searches the whole set rather than the page in hand.
   */
  filterValue?: string;
  onFilterValueChange?: (value: string) => void;
  enableColumnVisibilityDropdown?: boolean;
  /**
   * When provided, the DataTable treats ``columnVisibility`` as controlled
   * state. Use this together with ``onColumnVisibilityChange`` to persist
   * toggles across sessions (in their view, from ``useListView``).
   */
  columnVisibility?: ColumnVisibilityState;
  onColumnVisibilityChange?: (
    updater: ColumnVisibilityState | ((prev: ColumnVisibilityState) => ColumnVisibilityState)
  ) => void;
  enablePagination?: boolean;
  enableResetSorting?: boolean;
  initialSorting?: SortingState;
  initialState?: Partial<TableState>;
  pageSizeOptions?: number[];
  groupingOptions?: GroupingOption[];
  /** Whether the toolbar offers the grouping; false where the caller offers
   *  it somewhere else. */
  groupingControl?: boolean;
  helpText?: ReactNode | ((table: AppTable<TData>) => ReactNode);
  enableRowSelection?: boolean;
  onRowSelectionChange?: (selectedRows: TData[]) => void;
  getRowId?: (row: TData) => string;
  /** The rows nested under a row, drawn under it and folded with it. A row
   *  selects only itself, stays folded across new data, and the filter keeps
   *  a row any of whose nested rows match. */
  getSubRows?: (row: TData) => TData[] | undefined;
  /** A row (by `getRowId`) kept first whatever the sort; the rest sort as
   *  asked beneath it. */
  pinnedRowId?: string;
  onExitSelection?: () => void;
  manualPagination?: boolean;
  pageCount?: number;
  rowCount?: number;
  /**
   * Controlled 0-based page index for manualPagination. When provided, external
   * page changes (e.g. "reset to page 1 on filter change") are reflected in
   * the pagination control. Without this, the table's internal pageIndex would
   * desync from the data being shown.
   */
  pageIndex?: number;
  onPaginationChange?: (pagination: PaginationState) => void;
  /** Warm a page, counted from 1, before it is asked for. */
  onPrefetchPage?: (page: number) => void;
  manualSorting?: boolean;
  /**
   * Controlled sorting, for a caller that keeps the order somewhere of its own
   * (a URL, say) and hands it back. Without it the table owns the order from
   * ``initialSorting`` on, and an order changed from outside — the back button
   * landing on a different one — would leave the headers pointing one way
   * while the rows arrive in another. The same reason ``pageIndex`` exists.
   */
  sorting?: SortingState;
  onSortingChange?: (sorting: SortingState) => void;
  /**
   * Controlled grouping, for a caller that works the grouping out itself (a
   * layout's default where a person never picked) and hands it back. Without
   * it the table owns the grouping from ``initialState.grouping`` on, and one
   * changed from outside would leave the headers on the old grouping while
   * the caller's rows are shaped for the new one.
   */
  grouping?: GroupingState;
  onGroupingChange?: (grouping: GroupingState) => void;
  /** Mounts only the rows near the view, as the page scrolls past them, for
   *  a table too long to draw whole. Its head stays at the top of the page
   *  while its rows go by, and it does not paginate. */
  enableVirtualization?: boolean;
  virtualRowHeight?: number;
  virtualOverscan?: number;
}

export interface DataTableRowWrapperProps<TData extends RowData> {
  row: AppRow<TData>;
  children: ReactNode;
  /** When virtualization is enabled, set this as data-index on the row element. */
  virtualIndex?: number;
  /** When virtualization is enabled, attach this ref to the row element for measurement. */
  measureRef?: (el: HTMLElement | null) => void;
}

const DEFAULT_PAGE_SIZE = 20;
const FIXED_LAYOUT = "table-fixed [&_td]:break-words";
const GROUPING_NONE_VALUE = "__none__";

export function DataTable<TData extends RowData>({
  columns,
  data,
  rowWrapper,
  groupRowWrapper,
  enableFilterInput = false,
  filterInputPlaceholder,
  filterInputColumnKey = "name",
  filterValue,
  onFilterValueChange,
  enableColumnVisibilityDropdown = false,
  columnVisibility: controlledColumnVisibility,
  onColumnVisibilityChange: externalOnColumnVisibilityChange,
  enablePagination = false,
  enableResetSorting: enableClearSorting = false,
  initialSorting,
  initialState,
  pageSizeOptions,
  groupingOptions,
  groupingControl = true,
  helpText,
  enableRowSelection = false,
  onRowSelectionChange,
  getRowId,
  getSubRows,
  pinnedRowId,
  onExitSelection,
  manualPagination = false,
  pageCount: externalPageCount,
  rowCount: externalRowCount,
  pageIndex: externalPageIndex,
  onPaginationChange: externalOnPaginationChange,
  onPrefetchPage,
  manualSorting = false,
  sorting: controlledSorting,
  onSortingChange: externalOnSortingChange,
  grouping: controlledGrouping,
  onGroupingChange: externalOnGroupingChange,
  enableVirtualization = false,
  virtualRowHeight = 48,
  virtualOverscan = 5,
}: DataTableProps<TData>) {
  const { t } = useTranslation("ui");
  const initialStateRef = useRef<Partial<TableState> | undefined>(initialState);
  const initialSortingRef = useRef<SortingState>(initialSorting ? [...initialSorting] : []);
  const groupingEnabled = Boolean(groupingOptions && groupingOptions.length > 0);
  const initialGroupingState = initialStateRef.current?.grouping;
  const initialGroupingRef = useRef<GroupingState>(
    groupingEnabled && Array.isArray(initialGroupingState) ? [...initialGroupingState] : []
  );
  const resolveInitialPagination = (): PaginationState => {
    const paginationState = initialStateRef.current?.pagination as PaginationState | undefined;
    return {
      pageIndex: paginationState?.pageIndex ?? 0,
      pageSize: paginationState?.pageSize ?? DEFAULT_PAGE_SIZE,
    };
  };
  const initialPaginationRef = useRef<PaginationState>(resolveInitialPagination());
  const [internalSorting, setInternalSorting] = useState<SortingState>(
    () => initialSortingRef.current
  );
  const sorting = controlledSorting ?? internalSorting;
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(
    () => (initialStateRef.current?.columnFilters as ColumnFiltersState) ?? []
  );
  const [internalColumnVisibility, setInternalColumnVisibility] = useState<ColumnVisibilityState>(
    () => initialStateRef.current?.columnVisibility ?? {}
  );
  const isColumnVisibilityControlled = controlledColumnVisibility !== undefined;
  const columnVisibility = isColumnVisibilityControlled
    ? controlledColumnVisibility
    : internalColumnVisibility;
  const handleColumnVisibilityChange = useCallback(
    (updater: ColumnVisibilityState | ((prev: ColumnVisibilityState) => ColumnVisibilityState)) => {
      if (isColumnVisibilityControlled) {
        externalOnColumnVisibilityChange?.(updater);
        return;
      }
      setInternalColumnVisibility((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        externalOnColumnVisibilityChange?.(next);
        return next;
      });
    },
    [externalOnColumnVisibilityChange, isColumnVisibilityControlled]
  );
  const [internalGrouping, setGrouping] = useState<GroupingState>(() =>
    groupingEnabled ? initialGroupingRef.current : []
  );
  const grouping = controlledGrouping ?? internalGrouping;
  const [pagination, setPagination] = useState<PaginationState>(() => initialPaginationRef.current);

  // Sync external pageIndex into the table's internal pagination state when
  // manualPagination is true (e.g. so "reset to page 1 on filter change" from
  // the parent hook actually moves the pagination control).
  useEffect(() => {
    if (manualPagination && externalPageIndex !== undefined) {
      setPagination((prev) =>
        prev.pageIndex === externalPageIndex ? prev : { ...prev, pageIndex: externalPageIndex }
      );
    }
  }, [externalPageIndex, manualPagination]);

  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [selectionModeActive, setSelectionModeActive] = useState(false);
  // Anchor for shift+click range selection: the id of the last row toggled
  // individually. shiftKeyRef captures the modifier from the checkbox's onClick
  // (Radix's onCheckedChange doesn't expose the mouse event). rowCheckboxHandlerRef
  // lets the selection column (built before `table` exists) call into a handler
  // that closes over `table` without adding `table` to its memo deps.
  const lastSelectedRowIdRef = useRef<string | null>(null);
  const shiftKeyRef = useRef(false);
  const rowCheckboxHandlerRef = useRef<(rowId: string, value: boolean) => void>(() => {});
  const computedInitialState: Partial<TableState> = {
    sorting: initialSortingRef.current,
    ...(initialStateRef.current ?? {}),
  };
  if (groupingEnabled && computedInitialState.expanded === undefined) {
    computedInitialState.expanded = true;
  }
  if (enablePagination) {
    computedInitialState.pagination = initialPaginationRef.current;
  }
  const columnsWithSelection = useMemo(() => {
    if (!enableRowSelection || !selectionModeActive) {
      return columns;
    }

    const selectionColumn: AppColumnDef<TData> = {
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected() ||
            (table.getIsSomePageRowsSelected() &&
              !table.getIsAllPageRowsSelected() &&
              "indeterminate")
          }
          onCheckedChange={(value) => {
            // Select-all resets the range anchor so a subsequent shift+click
            // starts fresh rather than ranging from a stale individual click.
            lastSelectedRowIdRef.current = null;
            table.toggleAllPageRowsSelected(!!value);
          }}
          aria-label={t("selectAll")}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onClick={(e) => {
            shiftKeyRef.current = e.shiftKey;
          }}
          onCheckedChange={(value) => rowCheckboxHandlerRef.current(row.id, !!value)}
          aria-label={t("table.selectRow")}
        />
      ),
      enableSorting: false,
      enableHiding: false,
    };

    return [selectionColumn, ...columns];
  }, [enableRowSelection, selectionModeActive, columns, t]);

  const handlePaginationChange = useMemo(() => {
    if (!enablePagination) return undefined;
    if (manualPagination && externalOnPaginationChange) {
      return (updater: PaginationState | ((old: PaginationState) => PaginationState)) => {
        const newState = typeof updater === "function" ? updater(pagination) : updater;
        setPagination(newState);
        externalOnPaginationChange(newState);
      };
    }
    return setPagination;
  }, [enablePagination, manualPagination, externalOnPaginationChange, pagination]);

  const handleSortingChange = useMemo(() => {
    if (externalOnSortingChange) {
      return (updater: SortingState | ((old: SortingState) => SortingState)) => {
        const newState = typeof updater === "function" ? updater(sorting) : updater;
        // A controlled caller answers with a new `sorting` prop; setting the
        // internal copy as well would be a second source of the same truth.
        if (controlledSorting === undefined) setInternalSorting(newState);
        externalOnSortingChange(newState);
      };
    }
    return setInternalSorting;
  }, [externalOnSortingChange, sorting, controlledSorting]);

  // The single funnel for grouping changes. `grouping` is controlled state, so
  // setting it directly would move the table without telling the caller — and
  // callers re-shape their rows off this callback (the project task table fans
  // a task out into one row per tag), so they'd end up grouping over data they
  // never rebuilt. Every grouping control routes through here.
  const handleGroupingChange = useCallback(
    (updater: GroupingState | ((old: GroupingState) => GroupingState)) => {
      const next = typeof updater === "function" ? updater(grouping) : updater;
      // A controlled caller answers with a new `grouping` prop.
      if (controlledGrouping === undefined) setGrouping(next);
      externalOnGroupingChange?.(next);
    },
    [externalOnGroupingChange, grouping, controlledGrouping]
  );

  const table = useTable({
    features: appTableFeatures,
    data,
    columns: columnsWithSelection,
    defaultColumn: {
      filterFn: (row, columnId, filterValue: string) => {
        // Exact: a filter keeps rows rather than ranking them, so a near
        // match would keep rows that don't hold what was typed.
        const cellValue = String(row.getValue(columnId) ?? "");
        return cellValue.toLowerCase().includes(filterValue.toLowerCase());
      },
    },
    onSortingChange: handleSortingChange,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: handleColumnVisibilityChange,
    onGroupingChange: groupingEnabled ? handleGroupingChange : undefined,
    onPaginationChange: handlePaginationChange,
    onRowSelectionChange: enableRowSelection ? setRowSelection : undefined,
    enableRowSelection: enableRowSelection,
    getRowId: getRowId,
    getSubRows,
    ...(getSubRows
      ? {
          filterFromLeafRows: true,
          // A row folded stays folded when the rows arrive again, as a list
          // that refreshes in the background does.
          autoResetExpanded: false,
          // A group's header still selects its rows.
          enableSubRowSelection: (row: AppRow<TData>) => row.getIsGrouped(),
        }
      : {}),
    // Row models are registered once in `appTableFeatures`; a stage is turned
    // off per-instance through its `manual*` option, which is where the
    // row-model pipeline short-circuits. Callers that don't paginate need that
    // too — otherwise the paginated row model would slice them to one page.
    manualPagination: manualPagination || !enablePagination,
    manualSorting: manualSorting,
    manualGrouping: !groupingEnabled,
    ...(manualPagination && externalPageCount !== undefined
      ? { pageCount: externalPageCount }
      : {}),
    ...(manualPagination && externalRowCount !== undefined ? { rowCount: externalRowCount } : {}),
    initialState: computedInitialState,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      ...(groupingEnabled ? { grouping } : {}),
      ...(enablePagination ? { pagination } : {}),
      ...(enableRowSelection ? { rowSelection } : {}),
    },
  });
  // `useTable` hands back a fresh object every render (it re-memoizes on the
  // options literal), so the instance is not usable as an effect dependency —
  // listing it would re-run the effect on every render. Effects read the table
  // through this ref and key themselves on the state they actually care about.
  const tableRef = useRef(table);
  tableRef.current = table;

  const normalizedGroupingOptions = useMemo<GroupingOption[]>(() => {
    if (!groupingOptions || groupingOptions.length === 0) {
      return [];
    }
    return groupingOptions.map((option) => ({ ...option }));
  }, [groupingOptions]);
  const groupingChoices = useMemo(() => {
    if (normalizedGroupingOptions.length === 0) {
      return grouping.length > 0 ? grouping.map((id) => ({ id, label: id })) : [];
    }
    const missing = grouping.filter(
      (id) => !normalizedGroupingOptions.some((option) => option.id === id)
    );
    if (missing.length === 0) {
      return normalizedGroupingOptions;
    }
    return [...normalizedGroupingOptions, ...missing.map((id) => ({ id, label: id }))];
  }, [normalizedGroupingOptions, grouping]);
  const hasGroupingOptions = groupingControl && groupingChoices.length > 0;
  const groupingColumnIdSet = useMemo(
    () => new Set(groupingChoices.map((option) => option.id)),
    [groupingChoices]
  );
  const groupingSelectValue = grouping.length > 0 ? grouping[0] : GROUPING_NONE_VALUE;
  if (!groupingEnabled && internalGrouping.length > 0) {
    setGrouping([]);
  }
  useEffect(() => {
    if (!groupingEnabled || grouping.length > 0) {
      return;
    }
    setInternalSorting((previousSorting) => {
      const filtered = previousSorting.filter((sort) => !groupingColumnIdSet.has(sort.id));
      if (
        filtered.length === previousSorting.length ||
        filtered.every(
          (sort, index) =>
            sort.id === previousSorting[index].id && sort.desc === previousSorting[index].desc
        )
      ) {
        return previousSorting;
      }
      return filtered;
    });
  }, [groupingEnabled, grouping, groupingColumnIdSet]);
  useEffect(() => {
    if (!groupingEnabled || grouping.length === 0) {
      return;
    }
    setInternalSorting((previousSorting) => {
      const groupingSet = new Set(grouping);
      const previousSortMap = new Map(previousSorting.map((sort) => [sort.id, sort]));
      let changed = false;
      const rest = previousSorting.filter((sort) => {
        if (groupingSet.has(sort.id)) {
          if (sort.desc) {
            changed = true;
          }
          return false;
        }
        if (groupingColumnIdSet.has(sort.id)) {
          changed = true;
          return false;
        }
        return true;
      });
      const groupingSorting = grouping.map((groupId, index) => {
        const existing = previousSortMap.get(groupId);
        if (!existing) {
          changed = true;
          return { id: groupId, desc: false };
        }
        if (existing.desc) {
          changed = true;
        }
        if (previousSorting.indexOf(existing) !== index) {
          changed = true;
        }
        return existing.desc ? { ...existing, desc: false } : existing;
      });
      const newSorting = [...groupingSorting, ...rest];
      if (
        !changed &&
        newSorting.length === previousSorting.length &&
        newSorting.every(
          (sort, idx) =>
            sort.id === previousSorting[idx].id && sort.desc === previousSorting[idx].desc
        )
      ) {
        return previousSorting;
      }
      return newSorting;
    });
  }, [groupingEnabled, grouping, groupingColumnIdSet]);

  // Handle a row-selection checkbox toggle, applying a shift+click range when an
  // anchor exists. The range spans the currently displayed (sorted/filtered/
  // paginated) rows between the anchor and the clicked row, inclusive, and only
  // ever selects (never deselects) — the standard anchor range-select behavior.
  // Limitation: under pagination the range is scoped to the current page, so a
  // shift+click whose anchor lives on another page falls back to a single toggle.
  rowCheckboxHandlerRef.current = (rowId: string, value: boolean) => {
    const isShift = shiftKeyRef.current;
    shiftKeyRef.current = false;
    const anchorId = lastSelectedRowIdRef.current;
    if (isShift && value && anchorId && anchorId !== rowId) {
      const visibleRows = table.getRowModel().rows;
      const from = visibleRows.findIndex((r) => r.id === anchorId);
      const to = visibleRows.findIndex((r) => r.id === rowId);
      if (from !== -1 && to !== -1) {
        const [lo, hi] = from < to ? [from, to] : [to, from];
        table.setRowSelection((prev) => {
          const next = { ...prev };
          for (let i = lo; i <= hi; i++) {
            const row = visibleRows[i];
            if (!row.getIsGrouped()) {
              next[row.id] = true;
            }
          }
          return next;
        });
        lastSelectedRowIdRef.current = rowId;
        return;
      }
    }
    table.getRow(rowId).toggleSelected(value);
    lastSelectedRowIdRef.current = rowId;
  };

  useEffect(() => {
    if (enableRowSelection && selectionModeActive && onRowSelectionChange) {
      // Report ALL selected rows (not just filter-visible ones) so the reported
      // selection always matches the checked checkboxes — selections persist
      // across filtering. columnFilters and data are deps so reported `.original`
      // references stay fresh when the row model rebuilds — and so a data change
      // that drops or re-keys rows (a refetch, or a consumer re-shaping rows for
      // a new grouping) reports the selection that is actually checked.
      // Limitation: under manualPagination only the current page is in `data`,
      // so selections on other pages remain in rowSelection (by id) but can't be
      // reported as row objects; cross-page selection is out of scope.
      // Every selected row, nested ones included.
      const selectedRows = tableRef.current
        .getSelectedRowModel()
        .flatRows.map((row) => row.original);
      onRowSelectionChange(selectedRows);
    }
  }, [
    rowSelection,
    columnFilters,
    data,
    enableRowSelection,
    selectionModeActive,
    onRowSelectionChange,
  ]);

  // Forget rows the current data no longer holds. Selection is keyed by row id,
  // so a consumer that re-keys its rows (re-shaping them for a new grouping, say)
  // would otherwise leave ids behind that silently re-select those rows the
  // moment the same ids come back. Filtering is unaffected — filtered-out rows
  // stay in the core row model — and group rows, whose ids exist only in the
  // grouped model, are kept so a "select all" keeps its header checkbox.
  // Skipped under manualPagination, where rows of other pages are legitimately
  // absent from `data` and their selection is meant to persist.
  useEffect(() => {
    if (!enableRowSelection || manualPagination) {
      return;
    }
    setRowSelection((previous) => {
      const selectedIds = Object.keys(previous);
      if (selectedIds.length === 0) {
        return previous;
      }
      const dataRows = tableRef.current.getCoreRowModel().rowsById;
      const displayedRows = tableRef.current.getRowModel().rowsById;
      const kept = selectedIds.filter((id) => id in dataRows || id in displayedRows);
      if (kept.length === selectedIds.length) {
        return previous;
      }
      return Object.fromEntries(kept.map((id) => [id, previous[id]]));
    });
  }, [data, grouping, enableRowSelection, manualPagination]);

  useEffect(() => {
    if (!selectionModeActive && Object.keys(rowSelection).length > 0) {
      setRowSelection({});
      lastSelectedRowIdRef.current = null;
      shiftKeyRef.current = false;
    }
  }, [selectionModeActive, rowSelection]);

  const handleExitSelection = useCallback(() => {
    setSelectionModeActive(false);
    setRowSelection({});
    lastSelectedRowIdRef.current = null;
    shiftKeyRef.current = false;
    if (onExitSelection) {
      onExitSelection();
    }
  }, [onExitSelection]);

  const sortedRows = table.getRowModel().rows;
  const rows = useMemo(() => {
    const at = pinnedRowId ? sortedRows.findIndex((row) => row.id === pinnedRowId) : -1;
    return at > 0
      ? [sortedRows[at], ...sortedRows.slice(0, at), ...sortedRows.slice(at + 1)]
      : sortedRows;
  }, [sortedRows, pinnedRowId]);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const {
    virtualizer,
    items: virtualItems,
    paddingTop,
    paddingBottom,
  } = useVirtualRows(bodyRef, {
    count: rows.length,
    estimateSize: () => virtualRowHeight,
    overscan: virtualOverscan,
    enabled: enableVirtualization,
  });
  // A virtualized table's head is drawn apart from its body, so that it stays
  // at the top of the page as the rows go by: the box the body scrolls
  // sideways in would otherwise hold it. It follows the body sideways, and the
  // body follows it where moving focus into it scrolled it.
  const headScrollerRef = useRef<HTMLDivElement>(null);
  const bodyScrollerRef = useRef<HTMLDivElement>(null);
  const followSideways = (event: UIEvent<HTMLDivElement>) => {
    const headScroller = headScrollerRef.current;
    const bodyScroller = bodyScrollerRef.current;
    if (!headScroller || !bodyScroller) return;
    if (event.target === bodyScroller) headScroller.scrollLeft = bodyScroller.scrollLeft;
    else if (event.target === headScroller) bodyScroller.scrollLeft = headScroller.scrollLeft;
  };

  const visibleColCount = table.getVisibleLeafColumns().length || columns.length;

  // When virtualization is enabled, pagination is disabled (mutually exclusive)
  const showPagination = enablePagination && !enableVirtualization;

  // Key that changes when the visible columns change (selection mode toggle,
  // column visibility dropdown). MemoizedVirtualCells compares it by string value
  // to decide when to re-render, so already-rendered virtual rows pick up new
  // columns without waiting to be scrolled out and back in. Computed inline (not
  // memoized) so it always reflects the current visible columns — value equality
  // means recomputing an identical string still won't trigger cell re-renders.
  const visibleColumnKey = table
    .getVisibleLeafColumns()
    .map((c) => c.id)
    .join(",");

  // A virtualized table holds only the rows in view, so the automatic layout
  // algorithm, which sizes columns from the cells it can see, re-measures
  // against different content on every scroll and the columns jump. Fixed
  // layout and a colgroup take the widths from each column's `size` instead,
  // which do not change as rows come and go, and keep the head's columns over
  // the body's. Spare width is shared out in proportion to those sizes, so a
  // column that should take up the slack declares a bigger one.
  const columnWidths = (
    <colgroup>
      {table.getVisibleLeafColumns().map((column) => (
        <col key={column.id} style={{ width: column.getSize() }} />
      ))}
    </colgroup>
  );
  const head = (
    <TableHeader>
      {table.getHeaderGroups().map((headerGroup) => (
        <TableRow key={headerGroup.id}>
          {headerGroup.headers.map((header) => {
            return (
              <TableHead key={header.id}>
                {header.isPlaceholder
                  ? null
                  : flexRender(header.column.columnDef.header, header.getContext())}
              </TableHead>
            );
          })}
        </TableRow>
      ))}
    </TableHeader>
  );
  const body = (
    <TableBody ref={bodyRef}>
      {rows.length ? (
        enableVirtualization ? (
          <>
            {paddingTop > 0 && (
              <tr>
                <td
                  style={{ height: paddingTop, padding: 0, border: "none" }}
                  colSpan={visibleColCount}
                />
              </tr>
            )}
            {virtualItems.map((virtualRow) => {
              const row = rows[virtualRow.index];
              return (
                <VirtualRow
                  key={row.id}
                  row={row}
                  virtualRow={virtualRow}
                  measureElement={virtualizer.measureElement}
                  groupingEnabled={groupingEnabled}
                  colSpan={visibleColCount}
                  rowWrapper={rowWrapper}
                  groupRowWrapper={groupRowWrapper}
                  visibleColumnKey={visibleColumnKey}
                />
              );
            })}
            {paddingBottom > 0 && (
              <tr>
                <td
                  style={{ height: paddingBottom, padding: 0, border: "none" }}
                  colSpan={visibleColCount}
                />
              </tr>
            )}
          </>
        ) : (
          rows.map((row) => {
            if (groupingEnabled && row.getIsGrouped()) {
              return (
                <GroupedRow
                  key={row.id}
                  row={row}
                  colSpan={visibleColCount}
                  wrapper={groupRowWrapper}
                />
              );
            }
            const cells = row
              .getVisibleCells()
              .map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ));
            if (rowWrapper) {
              return (
                <Fragment key={row.id}>
                  {rowWrapper({
                    row,
                    children: cells,
                  })}
                </Fragment>
              );
            }
            return (
              <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                {cells}
              </TableRow>
            );
          })
        )
      ) : (
        <TableRow>
          <TableCell colSpan={visibleColCount} className="h-24 text-center">
            {t("table.noResults")}
          </TableCell>
        </TableRow>
      )}
    </TableBody>
  );

  return (
    <div className="space-y-4">
      {helpText && typeof helpText === "function" ? helpText(table) : helpText}
      {enableRowSelection &&
        selectionModeActive &&
        table.getSelectedRowModel().rows.length > 0 &&
        (() => {
          const selected = table.getSelectedRowModel().rows.length;
          const filteredTotal = table.getFilteredRowModel().rows.length;
          const filteredSelected = table.getFilteredSelectedRowModel().rows.length;
          // When a filter hides any selected row, "X of Y selected" is misleading
          // because X (all selected rows) includes ones not visible in the filtered
          // view — e.g. it would read "2 of 3 selected" when none of the 3 visible
          // rows are checked. Switch to the filter-aware variant whenever the filter
          // hides at least one selected row, not just when selected > filteredTotal.
          const showFilteredVariant = columnFilters.length > 0 && filteredSelected < selected;
          return (
            <div className="text-muted-foreground text-sm">
              {showFilteredVariant
                ? t("table.rowsSelectedFiltered", { selected, total: filteredTotal })
                : t("table.rowsSelected", { selected, total: filteredTotal })}
            </div>
          );
        })()}
      <div
        className={cn(
          // Clipped rather than hidden: a box that hides its overflow is a
          // scroller, which a virtualized table's head would stay at the top
          // of instead of the page's.
          "overflow-clip rounded-md border bg-card",
          selectionModeActive && "border-primary ring-2 ring-primary/20"
        )}
      >
        {enableFilterInput ||
        enableClearSorting ||
        enableColumnVisibilityDropdown ||
        enableRowSelection ? (
          <div className="flex flex-wrap items-center justify-between gap-2 p-4">
            <div className="flex flex-1 items-center gap-2">
              {enableRowSelection && (
                <Button
                  variant={selectionModeActive ? "default" : "outline"}
                  onClick={() => {
                    if (selectionModeActive) {
                      handleExitSelection();
                    } else {
                      setSelectionModeActive(true);
                    }
                  }}
                  className="shrink-0"
                >
                  {selectionModeActive ? t("table.exitSelection") : t("table.select")}
                </Button>
              )}
              {enableFilterInput && (
                <Input
                  placeholder={filterInputPlaceholder ?? t("table.filter")}
                  value={
                    onFilterValueChange
                      ? (filterValue ?? "")
                      : ((table.getColumn(filterInputColumnKey)?.getFilterValue() as string) ?? "")
                  }
                  onChange={(event) =>
                    onFilterValueChange
                      ? onFilterValueChange(event.target.value)
                      : table.getColumn(filterInputColumnKey)?.setFilterValue(event.target.value)
                  }
                  className="min-w-16 flex-1"
                />
              )}
            </div>
            <div className="ml-auto flex items-center justify-end gap-2">
              {/* Desktop: Show controls inline */}
              <div className="canvas-sm:flex hidden flex-wrap items-center justify-end gap-2">
                {enableClearSorting && (
                  <Button variant="ghost" onClick={() => table.resetSorting()}>
                    <span className="text-muted-foreground">{t("table.resetSorting")}</span>
                  </Button>
                )}
                {groupingEnabled && hasGroupingOptions ? (
                  <GroupBySelect
                    options={groupingChoices}
                    value={grouping[0] ?? null}
                    onChange={(id) => handleGroupingChange(id === null ? [] : [id])}
                  />
                ) : null}
                {enableColumnVisibilityDropdown && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" className="ml-auto">
                        {t("table.columns")} <ChevronDown />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="end"
                      className="max-h-[min(70vh,24rem)] overflow-y-auto"
                    >
                      {table
                        .getAllColumns()
                        .filter((column) => column.getCanHide())
                        .map((column) => {
                          const meta = column.columnDef.meta as { label?: string } | undefined;
                          return (
                            <DropdownMenuCheckboxItem
                              key={column.id}
                              className="capitalize"
                              checked={column.getIsVisible()}
                              onCheckedChange={(value) => column.toggleVisibility(!!value)}
                            >
                              {meta?.label ?? column.id}
                            </DropdownMenuCheckboxItem>
                          );
                        })}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>

              {/* Mobile: Show overflow menu */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon" className="canvas-sm:hidden">
                    <MoreVertical className="h-4 w-4" />
                    <span className="sr-only">{t("table.options")}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel>{t("table.options")}</DropdownMenuLabel>
                  <DropdownMenuSeparator />

                  {enableRowSelection && (
                    <>
                      <DropdownMenuItem
                        onSelect={() => {
                          if (selectionModeActive) {
                            handleExitSelection();
                          } else {
                            setSelectionModeActive(true);
                          }
                        }}
                        className="cursor-pointer"
                      >
                        {selectionModeActive
                          ? t("table.exitSelectionMode")
                          : t("table.enableSelectionMode")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                    </>
                  )}

                  {enableClearSorting && (
                    <>
                      <DropdownMenuItem
                        onSelect={() => table.resetSorting()}
                        className="cursor-pointer"
                      >
                        {t("table.resetSorting")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                    </>
                  )}

                  {groupingEnabled && hasGroupingOptions && (
                    <>
                      <DropdownMenuSub>
                        <DropdownMenuSubTrigger>{t("table.groupBy")}</DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                          <DropdownMenuCheckboxItem
                            checked={groupingSelectValue === GROUPING_NONE_VALUE}
                            onCheckedChange={() => handleGroupingChange([])}
                          >
                            {t("table.none")}
                          </DropdownMenuCheckboxItem>
                          {groupingChoices.map((option) => (
                            <DropdownMenuCheckboxItem
                              key={option.id}
                              checked={groupingSelectValue === option.id}
                              onCheckedChange={() => handleGroupingChange([option.id])}
                            >
                              {option.label}
                            </DropdownMenuCheckboxItem>
                          ))}
                        </DropdownMenuSubContent>
                      </DropdownMenuSub>
                      <DropdownMenuSeparator />
                    </>
                  )}

                  {enableColumnVisibilityDropdown && (
                    <>
                      {/*
                        Inline the columns list on mobile rather than opening a
                        nested sub-dropdown — on narrow screens the sub content
                        can't fit next to the parent menu and ends up clipped
                        off the left edge of the viewport. A single scrollable
                        region inside the main menu keeps everything on-screen.
                      */}
                      <DropdownMenuLabel>{t("table.columns")}</DropdownMenuLabel>
                      <div className="max-h-[min(50vh,20rem)] overflow-y-auto">
                        {table
                          .getAllColumns()
                          .filter((column) => column.getCanHide())
                          .map((column) => {
                            const meta = column.columnDef.meta as { label?: string } | undefined;
                            return (
                              <DropdownMenuCheckboxItem
                                key={column.id}
                                className="capitalize"
                                checked={column.getIsVisible()}
                                onCheckedChange={(value) => column.toggleVisibility(!!value)}
                              >
                                {meta?.label ?? column.id}
                              </DropdownMenuCheckboxItem>
                            );
                          })}
                      </div>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        ) : null}

        {enableVirtualization ? (
          // Two tables, one to a screen reader: see `TableRow`.
          <div role="table" onScrollCapture={followSideways}>
            <Table
              role="presentation"
              scrollContainerRef={headScrollerRef}
              scrollContainerClassName="sticky top-0 z-10 overflow-hidden bg-card"
              className={FIXED_LAYOUT}
            >
              {columnWidths}
              {head}
            </Table>
            <Table
              role="presentation"
              scrollContainerRef={bodyScrollerRef}
              className={FIXED_LAYOUT}
            >
              {columnWidths}
              {body}
            </Table>
          </div>
        ) : (
          <Table>
            {head}
            {body}
          </Table>
        )}
        {showPagination && (
          <PaginationBar
            className="p-4"
            page={table.state.pagination.pageIndex + 1}
            pageSize={table.state.pagination.pageSize}
            totalCount={table.getRowCount()}
            hasNext={table.getCanNextPage()}
            onPageChange={(page) => table.setPageIndex(page - 1)}
            onPageSizeChange={(size) => table.setPageSize(size)}
            pageSizeOptions={pageSizeOptions}
            onPrefetchPage={onPrefetchPage}
          />
        )}
      </div>
    </div>
  );
}

/** What a list is grouped by, of `options`, or none. A table's toolbar
 *  holds it, and the board shows the same one above its columns. */
export function GroupBySelect({
  options,
  value,
  onChange,
}: {
  options: readonly GroupingOption[];
  value: string | null;
  onChange: (id: string | null) => void;
}) {
  const { t } = useTranslation("ui");
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor={id} className="font-medium text-muted-foreground text-sm">
        {t("table.groupBy")}
      </Label>
      <Select
        value={value ?? GROUPING_NONE_VALUE}
        onValueChange={(next) => onChange(next === GROUPING_NONE_VALUE ? null : next)}
      >
        <SelectTrigger id={id} className="w-40">
          <SelectValue placeholder={t("table.chooseGrouping")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={GROUPING_NONE_VALUE}>{t("table.none")}</SelectItem>
          {options.map((option) => (
            <SelectItem key={option.id} value={option.id}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function GroupedRow<TData extends RowData>({
  row,
  colSpan,
  wrapper,
  virtualIndex,
  measureRef,
}: {
  row: AppRow<TData>;
  colSpan: number;
  wrapper?: (props: DataTableRowWrapperProps<TData>) => ReactNode;
  virtualIndex?: number;
  measureRef?: (el: HTMLElement | null) => void;
}) {
  const cell = (
    <TableCell colSpan={colSpan} className="font-medium">
      <GroupedRowContent row={row} />
    </TableCell>
  );
  if (wrapper) {
    return <>{wrapper({ row, children: cell, virtualIndex, measureRef })}</>;
  }
  return (
    <TableRow
      data-index={virtualIndex}
      ref={measureRef}
      className="bg-muted/30"
      data-state="grouped"
    >
      {cell}
    </TableRow>
  );
}

/**
 * Memoized cell content for virtual rows. Only re-renders when the underlying
 * row data, its selection, whether it is open or the columns change — NOT on
 * every scroll position update.
 * This is the key performance optimization: cell renderers (Select, Checkbox,
 * TagBadge, etc.) are expensive and shouldn't run on every scroll frame.
 */
const MemoizedVirtualCells = memo(
  function VirtualCells({
    row,
    visibleColumnKey,
    isSelected,
  }: {
    row: AppRow<Record<string, unknown>>;
    visibleColumnKey: string;
    isSelected: boolean;
    /** Read only by the comparison: a row's fold control draws whether it is open. */
    isExpanded: boolean;
    /** Read only by the comparison: the cells draw what the columns say, and
     *  a caller's columns change with what they draw (a project's types
     *  arriving, say). */
    columns: unknown;
  }) {
    return (
      <>
        {row.getVisibleCells().map((cell) => (
          <TableCell key={cell.id}>
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </TableCell>
        ))}
      </>
    );
  },
  (prev, next) =>
    prev.row.original === next.row.original &&
    prev.isSelected === next.isSelected &&
    prev.isExpanded === next.isExpanded &&
    prev.columns === next.columns &&
    prev.visibleColumnKey === next.visibleColumnKey
);

function VirtualRow<TData extends RowData>({
  row,
  virtualRow,
  measureElement,
  groupingEnabled,
  colSpan,
  rowWrapper,
  groupRowWrapper,
  visibleColumnKey,
}: {
  row: AppRow<TData>;
  virtualRow: { index: number; start: number; size: number };
  measureElement: (el: HTMLElement | null) => void;
  groupingEnabled: boolean;
  colSpan: number;
  rowWrapper?: (props: DataTableRowWrapperProps<TData>) => ReactNode;
  groupRowWrapper?: (props: DataTableRowWrapperProps<TData>) => ReactNode;
  visibleColumnKey: string;
}) {
  if (groupingEnabled && row.getIsGrouped()) {
    return (
      <GroupedRow
        row={row}
        colSpan={colSpan}
        wrapper={groupRowWrapper}
        virtualIndex={virtualRow.index}
        measureRef={measureElement}
      />
    );
  }

  const cells = (
    <MemoizedVirtualCells
      row={row as unknown as AppRow<Record<string, unknown>>}
      visibleColumnKey={visibleColumnKey}
      isSelected={row.getIsSelected()}
      isExpanded={row.getIsExpanded()}
      columns={row.table.options.columns}
    />
  );

  if (rowWrapper) {
    return (
      <Fragment>
        {rowWrapper({
          row,
          children: cells,
          virtualIndex: virtualRow.index,
          measureRef: measureElement,
        })}
      </Fragment>
    );
  }

  return (
    <TableRow
      data-index={virtualRow.index}
      ref={measureElement}
      data-state={row.getIsSelected() && "selected"}
    >
      {cells}
    </TableRow>
  );
}

/** A group's header: the toggle that collapses it, named by what the header
 *  shows, then how many rows it holds. */
function GroupedRowContent<TData extends RowData>({ row }: { row: AppRow<TData> }) {
  const labelId = useId();
  const groupedCell = row.getAllCells().find((cell) => cell.getIsGrouped?.());
  const groupContent = groupedCell?.column.columnDef.cell
    ? flexRender(groupedCell.column.columnDef.cell, groupedCell.getContext())
    : ((groupedCell?.getValue() ?? row.id) as ReactNode);
  const toggleExpandHandler = row.getToggleExpandedHandler?.();
  const canToggle = typeof toggleExpandHandler === "function";
  const isExpanded = row.getIsExpanded();
  return (
    <div className="flex items-center gap-2">
      {canToggle ? (
        <button
          type="button"
          onClick={toggleExpandHandler}
          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
          aria-expanded={isExpanded}
          aria-labelledby={labelId}
        >
          <ChevronDown
            className={`h-4 w-4 transition-transform ${isExpanded ? "" : "-rotate-90"}`}
          />
        </button>
      ) : null}
      <span id={labelId}>{groupContent}</span>
      <span className="text-muted-foreground text-sm tabular-nums">{row.subRows.length}</span>
    </div>
  );
}

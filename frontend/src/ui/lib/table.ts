import {
  type Column,
  type ColumnDef,
  columnFilteringFeature,
  columnGroupingFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  createExpandedRowModel,
  createFilteredRowModel,
  createGroupedRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  type Row,
  type RowData,
  rowExpandingFeature,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  type Table,
  tableFeatures,
} from "@tanstack/react-table";

/**
 * The feature set every table in the app is built from.
 *
 * TanStack Table v9 no longer bundles features automatically — a table only has
 * the APIs whose features it registers, and row models are static slots rather
 * than per-instance options. `DataTable` is the single table factory here, so
 * this registry is the union of what any of its callers use.
 *
 * Per-instance behaviour is switched off with the matching `manual*` option
 * instead (see `DataTable`), which is what the row-model pipeline checks.
 */
export const appTableFeatures = tableFeatures({
  columnFilteringFeature,
  columnGroupingFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  rowExpandingFeature,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  filteredRowModel: createFilteredRowModel(),
  groupedRowModel: createGroupedRowModel(),
  sortedRowModel: createSortedRowModel(),
  expandedRowModel: createExpandedRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
  // Only the built-ins referenced by name from a column def need registering;
  // functions passed straight to `sortFn` are used as-is.
  sortFns: { alphanumeric: sortFn_alphanumeric },
});

export type AppTableFeatures = typeof appTableFeatures;

/**
 * Table types pre-bound to {@link appTableFeatures}. Column definitions and row
 * renderers should use these rather than the raw generics, so the feature set
 * stays a single-source-of-truth detail of this module.
 */
export type AppColumnDef<TData extends RowData, TValue = unknown> = ColumnDef<
  AppTableFeatures,
  TData,
  TValue
>;
export type AppColumn<TData extends RowData, TValue = unknown> = Column<
  AppTableFeatures,
  TData,
  TValue
>;
export type AppRow<TData extends RowData> = Row<AppTableFeatures, TData>;
export type AppTable<TData extends RowData> = Table<AppTableFeatures, TData>;

import type { PaginationState, SortingState } from "@tanstack/react-table";
import { useState } from "react";

import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";

/** How long typing settles before the list is asked again. */
const SEARCH_SETTLES_MS = 250;
const FIRST_PAGE_SIZE = 20;

/** The list params a server-searched, -sorted and -paged table asks with. */
export interface ServerTableParams<TSortField extends string> {
  search?: string;
  page: number;
  page_size: number;
  sort_by?: TSortField;
  sort_dir?: "asc" | "desc";
}

/**
 * The state of a table the server searches, sorts and pages: what was typed
 * (and its settled value), the sort, the page and the page size. Holds no
 * query; the caller asks its own list with `params` and hands the answer's
 * total back to `tableProps`.
 *
 * `sortFields` are the columns the server sorts by. A sort on any other
 * column is left out of `params`, and a table with none is not sortable.
 * Any change to the search, sort or page size returns to the first page.
 */
export const useServerTableState = <TSortField extends string = never>(
  sortFields: readonly TSortField[] = []
) => {
  const [draft, setDraft] = useState("");
  const search = useDebouncedValue(draft, SEARCH_SETTLES_MS);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(FIRST_PAGE_SIZE);

  const sort = sorting[0];
  const sortField = sortFields.find((field) => field === sort?.id);
  const params: ServerTableParams<TSortField> = {
    search: search.trim() || undefined,
    page,
    page_size: pageSize,
    ...(sortField ? { sort_by: sortField, sort_dir: sort?.desc ? "desc" : "asc" } : {}),
  };

  /**
   * The DataTable props for the filter box, sort and pager. `answeredPage` is
   * the page the server answered with, where it may differ from the one asked.
   */
  const tableProps = (totalCount: number, answeredPage: number = page) => ({
    filterValue: draft,
    onFilterValueChange: (value: string) => {
      setDraft(value);
      setPage(1);
    },
    ...(sortFields.length > 0
      ? {
          manualSorting: true,
          sorting,
          onSortingChange: (next: SortingState) => {
            setSorting(next);
            setPage(1);
          },
        }
      : {}),
    manualPagination: true,
    pageCount: Math.max(1, Math.ceil(totalCount / pageSize)),
    rowCount: totalCount,
    pageIndex: answeredPage - 1,
    onPaginationChange: (next: PaginationState) => {
      if (next.pageSize !== pageSize) {
        setPageSize(next.pageSize);
        setPage(1);
      } else {
        setPage(next.pageIndex + 1);
      }
    },
  });

  return { params, tableProps };
};

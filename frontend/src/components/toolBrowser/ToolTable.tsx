/**
 * The one tool table. Every tool renders through it — the columns are fixed
 * and the tool only supplies the rows (see `lib/toolRows`), so switching tools
 * swaps the data, not the layout.
 *
 * Rows are read a server page at a time, and the search box and the sortable
 * headers go to the server with them. Nothing here filters or sorts the page
 * already in hand: that would answer "no matches" while page 4 holds matches,
 * and would sort the accident of pagination rather than the work. The columns
 * every tool shares are the ones that sort, because they are the only ones
 * every tool's endpoint can order by; the tool's own column is its own
 * business.
 *
 * Every row addresses its own community, so links are absolute rather than
 * relative to whichever community the reader happens to be in.
 */

import { Link } from "@tanstack/react-router";
import type { PaginationState } from "@tanstack/react-table";
import type { ParseKeys } from "i18next";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { MentionText } from "@/components/user/MentionText";
import { communityPath } from "@/lib/communityUrl";
import { TOOL_HAS_DETAIL, type ToolRow } from "@/lib/toolRows";
import { initiativeRoute, toolCamelPlural } from "@/lib/tools";
import { DataTable } from "@/ui/data-table";
import type { AppColumn, AppColumnDef } from "@/ui/lib/table";
import { RelativeTime } from "@/ui/relative-time";
import { SortHeader } from "@/ui/sort-icon";

/** The leaf keys under `communityHome.columns.detail` — one per tool that has the
 *  column. */
type DetailColumnKey = Extract<ParseKeys<"communityHome">, `columns.detail.${string}`>;

/** communityHome.json header key for a tool's own column, e.g.
 *  `columns.detail.projects` — derived the same way as the nav labels in
 *  `lib/tools`, and pinned for every tool that has one by the tool-registry
 *  drift test. */
const detailColumnKey = (tool: Tool): DetailColumnKey =>
  `columns.detail.${toolCamelPlural(tool)}` as DetailColumnKey;

/** An initiative, wherever it lives: ids repeat across communities, so the
 *  community is half the key. */
const initiativeKey = (communityId: number | null, initiativeId: number) =>
  `${communityId}:${initiativeId}`;

const NameCell = ({ row }: { row: ToolRow }) => (
  <div className="flex min-w-[220px] items-center gap-2 sm:min-w-0">
    {row.glyph}
    <Link
      to={communityPath(row.communityId, row.href)}
      className="truncate font-medium text-primary hover:underline"
    >
      {row.name}
    </Link>
  </div>
);

const CommunityCell = ({
  row,
  communities,
}: {
  row: ToolRow;
  communities: Map<number, string>;
}) => {
  const name = communities.get(row.communityId);
  if (!name) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <Link to={communityPath(row.communityId, "/")} className="text-sm hover:underline">
      {name}
    </Link>
  );
};

const InitiativeCell = ({
  row,
  initiatives,
}: {
  row: ToolRow;
  initiatives: Map<string, InitiativeRead>;
}) => {
  const { t } = useTranslation("communityHome");
  if (row.initiativeId === null) {
    return <span className="text-muted-foreground text-sm">{t("communityWide")}</span>;
  }
  const initiative = initiatives.get(initiativeKey(row.communityId, row.initiativeId));
  if (!initiative) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <Link
      to={communityPath(row.communityId, initiativeRoute(initiative.id))}
      className="text-sm hover:underline"
    >
      {initiative.name}
    </Link>
  );
};

/** The tool's own column. Where it is words, they can mention people, who
 *  read as who they are now in the row's own community. */
const DetailCell = ({ row }: { row: ToolRow }) => {
  if (!row.detail) return <span className="text-muted-foreground">—</span>;
  if (typeof row.detail !== "string") return row.detail;
  return <MentionText text={row.detail} communityId={row.communityId} />;
};

const TagsCell = ({ row }: { row: ToolRow }) => {
  if (row.tags.length === 0) {
    return <span className="text-muted-foreground text-sm">—</span>;
  }
  return (
    <TagBadgeList
      tags={row.tags}
      tagHref={(tag) => communityPath(row.communityId, `/tags/${tag.id}`)}
    />
  );
};

/** The columns a tool's list endpoint can order by, as it names them. */
export const TOOL_SORT_FIELDS = ["name", "initiative", "updated_at"] as const;
export type ToolSortField = (typeof TOOL_SORT_FIELDS)[number];

/**
 * What a cross-community list can order by. One short of the full set: ordering by
 * initiative means ordering by its name, which a merged list — assembled in
 * Python from summaries that carry an initiative id and not its name — has no
 * way to do. So that header does not sort on My Tools.
 */
export const CROSS_COMMUNITY_TOOL_SORT_FIELDS = ["name", "updated_at"] as const;

/** Table column id → the field name the endpoints take, and back. */
const SORT_FIELD_BY_COLUMN: Record<string, ToolSortField> = {
  name: "name",
  initiative: "initiative",
  updated: "updated_at",
};
const COLUMN_BY_SORT_FIELD: Record<ToolSortField, string> = {
  name: "name",
  initiative: "initiative",
  updated_at: "updated",
};

/** Whether `value` names a field the given set can order by — how a page reads
 *  the order out of its own address bar. */
export const isToolSortField = (
  value: unknown,
  fields: readonly ToolSortField[] = TOOL_SORT_FIELDS
): value is ToolSortField =>
  typeof value === "string" && (fields as readonly string[]).includes(value);

interface ToolTableProps {
  tool: Tool;
  rows: ToolRow[];
  /** Every initiative the rows might name, from however many communities. */
  initiatives: InitiativeRead[];
  /**
   * Community id → name. Passing it adds the community column, which is what a
   * cross-community table needs and a single community's own page does not.
   */
  communities?: Map<number, string>;
  totalCount: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  /** The search text, as it is in the address bar. */
  search: string;
  onSearchChange: (search: string) => void;
  /** One of {@link TOOL_SORT_FIELDS}, and which way. */
  sortBy: ToolSortField;
  sortDir: "asc" | "desc";
  onSortChange: (sortBy: ToolSortField, sortDir: "asc" | "desc") => void;
  /** Which headers offer to sort. Defaults to every column that can. */
  sortFields?: readonly ToolSortField[];
}

export const ToolTable = ({
  tool,
  rows,
  initiatives,
  communities,
  totalCount,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  search,
  onSearchChange,
  sortBy,
  sortDir,
  onSortChange,
  sortFields = TOOL_SORT_FIELDS,
}: ToolTableProps) => {
  const { t } = useTranslation("communityHome");

  const pageCount = Math.max(1, Math.ceil(totalCount / pageSize));
  // A bookmarked page outlives the rows it pointed at, and a hand-typed one may
  // never have had any. There are still rows, so land back on the first page
  // rather than showing an empty table over them.
  useEffect(() => {
    if (totalCount > 0 && page > pageCount) onPageChange(1);
  }, [totalCount, page, pageCount, onPageChange]);

  const initiativesByKey = useMemo(
    () =>
      new Map(
        initiatives.map((initiative) => [
          initiativeKey(initiative.community_id, initiative.id),
          initiative,
        ])
      ),
    [initiatives]
  );

  const columns = useMemo<AppColumnDef<ToolRow>[]>(() => {
    /** A header that sorts where the page allows it, and plain text where it
     *  does not — a control that cannot act would only mislead. */
    const header = (field: ToolSortField, label: string) =>
      sortFields.includes(field)
        ? ({ column }: { column: AppColumn<ToolRow> }) => (
            <SortHeader column={column} label={label} />
          )
        : () => <span className="px-3 font-medium">{label}</span>;

    return [
      {
        accessorKey: "name",
        header: header("name", t("columns.name")),
        cell: ({ row }) => <NameCell row={row.original} />,
        enableSorting: sortFields.includes("name"),
        enableHiding: false,
      },
      ...(communities
        ? [
            {
              id: "community",
              header: t("columns.community"),
              cell: ({ row }) => <CommunityCell row={row.original} communities={communities} />,
            } satisfies AppColumnDef<ToolRow>,
          ]
        : []),
      {
        id: "initiative",
        header: header("initiative", t("columns.initiative")),
        cell: ({ row }) => <InitiativeCell row={row.original} initiatives={initiativesByKey} />,
        enableSorting: sortFields.includes("initiative"),
      },
      ...(TOOL_HAS_DETAIL[tool]
        ? [
            {
              id: "detail",
              // Each tool names this column in its own terms ("Progress",
              // "Type", …), and each means something different by it, so there
              // is no one ordering for the endpoints to agree on. It does not
              // sort.
              header: t(detailColumnKey(tool)),
              cell: ({ row }) => (
                <span className="text-sm">
                  <DetailCell row={row.original} />
                </span>
              ),
            } satisfies AppColumnDef<ToolRow>,
          ]
        : []),
      {
        id: "tags",
        header: t("columns.tags"),
        cell: ({ row }) => <TagsCell row={row.original} />,
        size: 150,
      },
      {
        id: "updated",
        header: header("updated_at", t("columns.updated")),
        cell: ({ row }) => (
          <RelativeTime date={row.original.updatedAt} className="text-muted-foreground text-sm" />
        ),
        enableSorting: sortFields.includes("updated_at"),
      },
    ];
  }, [t, tool, initiativesByKey, communities, sortFields]);

  return (
    <DataTable
      columns={columns}
      data={rows}
      // Ids repeat across communities, so the community is half the row key.
      getRowId={(row: ToolRow) => `${row.communityId}:${row.id}`}
      enableFilterInput
      filterInputPlaceholder={t("searchPlaceholder")}
      filterValue={search}
      onFilterValueChange={onSearchChange}
      enableColumnVisibilityDropdown
      manualSorting
      // Controlled, not seeded: the order lives in the address, so the back
      // button can change it after this mounts and the headers have to follow.
      sorting={[{ id: COLUMN_BY_SORT_FIELD[sortBy], desc: sortDir === "desc" }]}
      onSortingChange={(sorting) => {
        // Clearing the sort altogether lands back on the page's own default
        // rather than on whatever each endpoint would do unsorted.
        const next = sorting[0];
        const field = next ? SORT_FIELD_BY_COLUMN[next.id] : undefined;
        if (!field) {
          onSortChange("updated_at", "desc");
          return;
        }
        onSortChange(field, next.desc ? "desc" : "asc");
      }}
      enablePagination
      manualPagination
      pageCount={pageCount}
      rowCount={totalCount}
      pageIndex={page - 1}
      onPaginationChange={(pagination: PaginationState) => {
        if (pagination.pageSize !== pageSize) {
          onPageSizeChange(pagination.pageSize);
        } else {
          onPageChange(pagination.pageIndex + 1);
        }
      }}
    />
  );
};

/**
 * One tab of a tag's page: everything of one tool carrying the tag. The tool's
 * own rows come first, in the table every tool list draws, and under them a
 * table per kind of thing the tool holds that can carry a tag too — a
 * project's tasks, a wiki's pages.
 *
 * Every table is read a server page at a time, so a tag on thousands of things
 * costs the page in view and nothing more. Each section is only drawn when the
 * tag's counts say it holds something.
 */

import { keepPreviousData } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type InitiativeRead,
  type TaggedEntity,
  TagTarget,
  type TaskListRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { sharedTaskColumns } from "@/components/tasks/globalTaskColumns";
import { type ToolSortField, ToolTable } from "@/components/toolBrowser/ToolTable";
import { MentionText } from "@/components/user/MentionText";
import { useCommunityToolRows } from "@/hooks/useCommunityToolRows";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useServerTableState } from "@/hooks/useServerTableState";
import { useTagEntities } from "@/hooks/useTags";
import { useTasks } from "@/hooks/useTasks";
import { useCommunityPath } from "@/lib/communityUrl";
import { taskSortFields } from "@/lib/filters/taskFilters";
import { fieldColumn } from "@/lib/layouts/columns";
import { LAYOUT_NAMESPACES, type LayoutEnv } from "@/lib/layouts/fields";
import { taskFields } from "@/lib/layouts/tasks";
import { hitIcon, searchHitPath } from "@/lib/searchResults";
import {
  type ChildKind,
  entityRefRoute,
  initiativeRoute,
  PARENT_TOOL,
  TOOLS,
  taskRoute,
  toolDetailRoute,
  toolNavLabelKey,
} from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";
import { DataTable } from "@/ui/data-table";
import type { AppColumnDef } from "@/ui/lib/table";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { TableSkeleton } from "@/ui/page-skeletons";
import { RelativeTime } from "@/ui/relative-time";
import { StatusMessage } from "@/ui/status-message";

/** What a tool holds that can carry a tag, by tool: every child kind the
 *  bulk tag edit can address. Derived, so a newly taggable kind gets its
 *  table by being one. */
type TaggedChild = ChildKind & `${TagTarget}`;
const TAGGABLE: ReadonlySet<string> = new Set(Object.values(TagTarget));
export const TAGGED_CHILDREN = Object.fromEntries(
  TOOLS.map((tool) => [
    tool,
    (Object.keys(PARENT_TOOL) as ChildKind[]).filter(
      (kind): kind is TaggedChild => PARENT_TOOL[kind] === tool && TAGGABLE.has(kind)
    ),
  ])
) as Record<Tool, TaggedChild[]>;

/** How many things of a tool's tab carry the tag: its own rows and its
 *  children's, from the tag's counts. */
export const toolTabCount = (tool: Tool, counts: Record<string, number>): number =>
  (counts[tool] ?? 0) + TAGGED_CHILDREN[tool].reduce((sum, kind) => sum + (counts[kind] ?? 0), 0);

const FIRST_PAGE_SIZE = 20;
/** A child kind's table has no sort control of its own: rows come by name. */
const NO_SORT_FIELDS: readonly never[] = [];

interface TagToolTabProps {
  tool: Tool;
  tagId: number;
  counts: Record<string, number>;
}

export const TagToolTab = ({ tool, tagId, counts }: TagToolTabProps) => {
  const { t } = useTranslation(["tags", "nav"]);
  const { data: initiatives = [] } = useInitiatives();
  const sections = TAGGED_CHILDREN[tool].filter((kind) => (counts[kind] ?? 0) > 0);

  return (
    <div className="space-y-8">
      {(counts[tool] ?? 0) > 0 ? (
        <section className="space-y-3">
          <h2 className="font-semibold text-lg">
            {t("detail.toolTab", {
              tool: t(toolNavLabelKey(tool), { ns: "nav" }),
              count: counts[tool],
            })}
          </h2>
          <TagToolTable tool={tool} tagId={tagId} initiatives={initiatives} />
        </section>
      ) : null}
      {sections.map((kind) => (
        <section key={kind} className="space-y-3">
          <h2 className="font-semibold text-lg">
            {t("detail.toolTab", { tool: t(`detail.children.${kind}`), count: counts[kind] })}
          </h2>
          {kind === "task" ? (
            <TagTasksTable tagId={tagId} />
          ) : (
            <TagEntityTable kind={kind} tagId={tagId} initiatives={initiatives} />
          )}
        </section>
      ))}
    </div>
  );
};

/** The tool's own rows carrying the tag, from its community-wide list. */
const TagToolTable = ({
  tool,
  tagId,
  initiatives,
}: {
  tool: Tool;
  tagId: number;
  initiatives: InitiativeRead[];
}) => {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(FIRST_PAGE_SIZE);
  const [draft, setDraft] = useState("");
  const search = useDebouncedValue(draft, 250).trim();
  const [sortBy, setSortBy] = useState<ToolSortField>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const { rows, totalCount, isLoading, isError, refetch } = useCommunityToolRows(
    tool,
    page,
    pageSize,
    {
      search,
      sortBy,
      sortDir,
      tagIds: [tagId],
    }
  );

  if (isLoading) return <TableSkeleton rows={4} columns={5} />;
  if (isError && rows.length === 0) return <StatusMessage onRetry={refetch} />;

  return (
    <ToolTable
      tool={tool}
      rows={rows}
      initiatives={initiatives}
      totalCount={totalCount}
      page={page}
      pageSize={pageSize}
      onPageChange={setPage}
      onPageSizeChange={(size) => {
        setPageSize(size);
        setPage(1);
      }}
      search={draft}
      onSearchChange={(value) => {
        setDraft(value);
        setPage(1);
      }}
      sortBy={sortBy}
      sortDir={sortDir}
      onSortChange={(field, direction) => {
        setSortBy(field);
        setSortDir(direction);
        setPage(1);
      }}
    />
  );
};

/** The tasks carrying the tag, across every project the reader can open.
 *
 * Read-only, as a task embed is: these rows come from many projects, and a
 * row does not say which of them the reader may change, so a control here
 * could only offer what the server then refuses. A task is changed on its
 * own page, a click away. */
const TagTasksTable = ({ tagId }: { tagId: number }) => {
  const { t } = useTranslation("tasks");
  const { t: viewT } = useTranslation(LAYOUT_NAMESPACES);
  const communityPath = useCommunityPath();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(FIRST_PAGE_SIZE);
  const [sorting, setSorting] = useState<SortingState>([]);

  const sort = taskSortFields(sorting);
  const { data, isLoading, isError, isPlaceholderData, refetch } = useTasks(
    {
      conditions: [{ field: "tag_ids", op: "in_", value: [tagId] }],
      page,
      page_size: pageSize,
      ...(sort.length > 0 ? { sorting: sort } : {}),
    },
    { placeholderData: keepPreviousData }
  );
  const tasks = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total_count ?? 0;

  // Fewer pages than the reader was on — something was untagged while they
  // looked — and the server answers with its last page: follow it.
  useEffect(() => {
    if (data && !isPlaceholderData && data.page !== page) setPage(data.page);
  }, [data, isPlaceholderData, page]);

  // Properties are an initiative's own, and these rows span initiatives, so
  // the table shows the fields every task has.
  const fields = useMemo(() => taskFields([]), []);
  const env = useMemo<LayoutEnv>(
    () => ({
      t: viewT as TranslateFn,
      communityPath: (to: string) => communityPath(to),
      itemHref: (task: TaskListRead) =>
        communityPath(
          task.initiative_id != null
            ? taskRoute(task.initiative_id, task.project_id, task.id)
            : entityRefRoute("task", task.id)
        ),
    }),
    [viewT, communityPath]
  );
  const columns = useMemo<AppColumnDef<TaskListRead>[]>(() => {
    const shared = sharedTaskColumns<TaskListRead>({
      fields,
      env,
      isPriorityDisabled: () => true,
    });
    const priority = fields.get("priority");
    return [
      shared.title,
      {
        id: "path",
        header: () => <span className="font-medium">{t("columns.projectPath")}</span>,
        cell: ({ row }) => {
          const task = row.original;
          return (
            <div className="flex min-w-72 flex-wrap items-center gap-2 text-sm">
              {task.initiative_id != null && task.initiative_name ? (
                <>
                  <Link
                    to={communityPath(initiativeRoute(task.initiative_id))}
                    className="text-muted-foreground hover:underline"
                  >
                    {task.initiative_name}
                  </Link>
                  <span className="text-muted-foreground" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              <Link
                to={communityPath(
                  toolDetailRoute(Tool.project, task.initiative_id ?? null, task.project_id)
                )}
                className="font-medium text-primary hover:underline"
              >
                {task.project_name ?? t("projectFallback", { id: task.project_id })}
              </Link>
            </div>
          );
        },
      },
      {
        id: "status",
        header: () => <span className="font-medium">{t("columns.status")}</span>,
        cell: ({ row }) => <span className="text-sm">{row.original.task_status.name}</span>,
        enableSorting: false,
      },
      // Priority reads as what it is, without the picker.
      ...(priority ? [fieldColumn<TaskListRead>(priority, env, { size: 140 })] : []),
      shared.startDate,
      shared.dueDate,
      shared.tags,
    ];
  }, [t, fields, env, communityPath]);

  const onPaginationChange = useCallback(
    (next: { pageIndex: number; pageSize: number }) => {
      if (next.pageSize !== pageSize) {
        setPageSize(next.pageSize);
        setPage(1);
      } else {
        setPage(next.pageIndex + 1);
      }
    },
    [pageSize]
  );

  if (isLoading) return <TableSkeleton rows={4} columns={6} />;
  if (isError && !data) return <StatusMessage onRetry={refetch} />;

  return (
    <DataTable
      columns={columns}
      data={tasks}
      getRowId={(task) => String(task.id)}
      enableColumnVisibilityDropdown
      manualSorting
      sorting={sorting}
      onSortingChange={(next) => {
        setSorting(next);
        setPage(1);
      }}
      enablePagination
      manualPagination
      pageIndex={page - 1}
      pageCount={Math.max(1, Math.ceil(total / pageSize))}
      rowCount={total}
      onPaginationChange={onPaginationChange}
    />
  );
};

/** The things of one kind inside a tool carrying the tag — a wiki's pages, a
 *  calendar's events — by name, each beside the tool it lives in. */
const TagEntityTable = ({
  kind,
  tagId,
  initiatives,
}: {
  kind: TaggedChild;
  tagId: number;
  initiatives: InitiativeRead[];
}) => {
  const { t } = useTranslation(["tags", "communityHome"]);
  const communityPath = useCommunityPath();
  const { params, tableProps } = useServerTableState(NO_SORT_FIELDS);
  const { data, isLoading, isError, refetch } = useTagEntities(tagId, {
    kind: kind as TagTarget,
    page: params.page,
    page_size: params.page_size,
  });
  const initiativeNames = useMemo(
    () => new Map(initiatives.map((initiative) => [initiative.id, initiative.name])),
    [initiatives]
  );

  const columns = useMemo<AppColumnDef<TaggedEntity>[]>(
    () => [
      {
        id: "name",
        header: t("communityHome:columns.name"),
        cell: ({ row }) => {
          const entity = row.original;
          const Icon = hitIcon(entity);
          const path = searchHitPath(entity);
          const title = <MentionText text={entity.title} disableLink />;
          return (
            <div className="flex min-w-[220px] items-center gap-2 sm:min-w-0">
              <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
              {path ? (
                <Link
                  to={communityPath(path)}
                  className="truncate font-medium text-primary hover:underline"
                >
                  {title}
                </Link>
              ) : (
                <span className="truncate font-medium">{title}</span>
              )}
            </div>
          );
        },
        enableHiding: false,
      },
      {
        id: "tool",
        header: t("detail.columns.in"),
        cell: ({ row }) => {
          const entity = row.original;
          return entity.tool && entity.tool_id != null ? (
            <Link
              to={communityPath(
                toolDetailRoute(entity.tool, entity.initiative_id ?? null, entity.tool_id)
              )}
              className="text-sm hover:underline"
            >
              {entity.tool_title}
            </Link>
          ) : (
            <span className="text-sm">{entity.tool_title}</span>
          );
        },
      },
      {
        id: "initiative",
        header: t("communityHome:columns.initiative"),
        cell: ({ row }) => {
          const { initiative_id: initiativeId } = row.original;
          if (initiativeId == null) {
            return (
              <span className="text-muted-foreground text-sm">
                {t("communityHome:communityWide")}
              </span>
            );
          }
          const name = initiativeNames.get(initiativeId);
          return name ? (
            <Link
              to={communityPath(initiativeRoute(initiativeId))}
              className="text-sm hover:underline"
            >
              {name}
            </Link>
          ) : (
            <span className="text-muted-foreground text-sm">—</span>
          );
        },
      },
      {
        id: "updated",
        header: t("communityHome:columns.updated"),
        cell: ({ row }) =>
          row.original.updated_at ? (
            <RelativeTime
              date={row.original.updated_at}
              className="text-muted-foreground text-sm"
            />
          ) : (
            <span className="text-muted-foreground text-sm">—</span>
          ),
      },
    ],
    [t, communityPath, initiativeNames]
  );

  if (isLoading) return <TableSkeleton rows={4} columns={4} />;
  if (isError && !data) return <StatusMessage onRetry={refetch} />;

  return (
    <DataTable
      columns={columns}
      data={data?.items ?? []}
      getRowId={(entity) => `${entity.entity_type}:${entity.entity_id}`}
      enablePagination
      {...tableProps(data?.total_count ?? 0, data?.page)}
    />
  );
};

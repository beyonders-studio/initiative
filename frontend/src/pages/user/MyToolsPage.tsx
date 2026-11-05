/**
 * My Tools: pick a tool from the rail, see everything of that kind that reaches you —
 * across every community you're in, not one at a time. It replaced the
 * separate My Projects and My Files pages, which were the same table twice
 * for two of the six tools.
 *
 * Two things set it apart from a plain list of each tool:
 *
 * - **A tab only appears for a tool you have something of.** `/me/tools/counts`
 *   answers for every tool in one request; a reader who has never touched a
 *   wiki is not offered an empty wiki table.
 * - **Two views of the same list.** "Everything" is what reaches you — what was
 *   shared with you, with a role you hold, or with an initiative you're in.
 *   "Made by me" is what you wrote. The toggle is in the address, like the
 *   tool, the page and the order, so either view is a link.
 */

import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import {
  getListInitiativesQueryKey,
  listInitiatives,
} from "@/api/generated/initiatives/initiatives";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { NodeRail, TRAY_SURFACE } from "@/components/toolBrowser/NodeRail";
import { CROSS_COMMUNITY_TOOL_SORT_FIELDS, ToolTable } from "@/components/toolBrowser/ToolTable";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useCommunities } from "@/hooks/useCommunities";
import { toolsWithContent, useMyToolCounts, useMyToolRows } from "@/hooks/useMyTools";
import { useToolBrowserSearch } from "@/hooks/useToolBrowserSearch";
import { TOOL_ICONS, toolNavLabelKey, toolRouteSegment } from "@/lib/tools";
import { cn } from "@/lib/utils";

const ROUTE = "/my-tools";

/** The address bar's `communities=1,2` as ids, dropping anything unreadable. */
const parseCommunities = (raw: string | undefined): number[] =>
  (raw ?? "")
    .split(",")
    .map(Number)
    .filter((id) => Number.isFinite(id) && id > 0);

export function MyToolsPage() {
  const { t } = useTranslation("myTools");
  const { t: tNav } = useTranslation("nav");
  const { communities } = useCommunities();
  const { search, setSearch, selectTool, query, table } = useToolBrowserSearch<{
    made?: string;
    communities?: string;
  }>(CROSS_COMMUNITY_TOOL_SORT_FIELDS);

  // "Made by me" is the narrower of the two views, so it is the one the address
  // has to say; a bare /my-tools is everything.
  const createdByMe = search.made === "me";
  const communityFilters = useMemo(
    () => parseCommunities(search.communities),
    [search.communities]
  );

  // Which tabs exist. The counts follow the view — the made-by-me list of a
  // tool you have never authored is empty, and a tab onto an empty table is
  // the thing this page is meant to avoid — but not the community filter:
  // narrowing the table should not make the reader's tools come and go.
  const countsQuery = useMyToolCounts({ created_by_me: createdByMe || undefined });
  const tools = useMemo(() => toolsWithContent(countsQuery.data), [countsQuery.data]);

  const selected = selectTool(tools);
  const toolNodes = useMemo(
    () =>
      tools.map((tool) => ({
        segment: toolRouteSegment(tool),
        icon: TOOL_ICONS[tool],
        label: tNav(toolNavLabelKey(tool)),
      })),
    [tools, tNav]
  );

  const { rows, totalCount, isLoading, isError } = useMyToolRows(
    selected,
    table.page,
    table.pageSize,
    {
      communityIds: communityFilters,
      search: query || undefined,
      createdByMe,
      sortBy: table.sortBy,
      sortDir: table.sortDir,
    }
  );

  const communityNames = useMemo(
    () => new Map(communities.map((community) => [community.id, community.name])),
    [communities]
  );

  // The initiative column names a row's initiative, and each community answers
  // for its own. Only the communities on this page of rows are asked, and the
  // answers are the same cache entries the sidebar and the community pages
  // already fill.
  const rowCommunityIds = useMemo(
    () => [...new Set(rows.map((row) => row.communityId))].sort((a, b) => a - b),
    [rows]
  );
  const initiatives = useQueries({
    queries: rowCommunityIds.map((communityId) => ({
      queryKey: getListInitiativesQueryKey(communityId),
      queryFn: () => listInitiatives(communityId),
      staleTime: 60_000,
    })),
    // `combine` rather than a `useMemo` over the results: the results array is
    // a fresh identity every render, so a memo keyed on it would never hit and
    // the table's columns would rebuild under it each time.
    combine: (results): InitiativeRead[] => results.flatMap((result) => result.data ?? []),
  });

  const emptyDescription = createdByMe ? t("empty.descriptionMine") : t("empty.description");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>

        <div className="flex flex-wrap items-end gap-4">
          {/* Only worth offering to somebody who is in more than one community
              — with a single one, the filter can only say what the page
              already says. */}
          {communities.length > 1 ? (
            <div className="w-full sm:w-56">
              <Label
                htmlFor="my-tools-communities"
                className="mb-2 block font-medium text-muted-foreground text-xs"
              >
                {t("communities.label")}
              </Label>
              <MultiSelect
                selectedValues={communityFilters.map(String)}
                options={communities.map((community) => ({
                  value: String(community.id),
                  label: community.name,
                }))}
                onChange={(values) => {
                  const ids = values.map(Number).filter(Number.isFinite);
                  setSearch({
                    communities: ids.length > 0 ? ids.join(",") : undefined,
                    page: undefined,
                  });
                }}
                placeholder={t("communities.all")}
                emptyMessage={t("communities.none")}
              />
            </div>
          ) : null}

          <ToggleGroup
            type="single"
            variant="outline"
            value={createdByMe ? "mine" : "all"}
            aria-label={t("view.label")}
            // A segmented control has no "neither" state to fall into: an
            // attempt to unset the active half leaves it where it was.
            onValueChange={(value) => {
              if (!value) return;
              setSearch({ made: value === "mine" ? "me" : undefined, page: undefined });
            }}
          >
            <ToggleGroupItem value="all">{t("view.everything")}</ToggleGroupItem>
            <ToggleGroupItem value="mine">{t("view.createdByMe")}</ToggleGroupItem>
          </ToggleGroup>
        </div>
      </div>

      {countsQuery.isLoading ? (
        <SkeletonRegion label={t("loading")}>
          <TableSkeleton rows={5} columns={5} pagination />
        </SkeletonRegion>
      ) : tools.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("noTools.title")}</CardTitle>
            <CardDescription>
              {createdByMe ? t("noTools.descriptionMine") : t("noTools.description")}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        // The rail and the table are one tray: the circles are its top edge
        // rising, and everything a tool has to say sits in the same surface
        // underneath them.
        <div>
          <NodeRail
            nodes={toolNodes}
            selected={toolRouteSegment(selected)}
            to={ROUTE}
            param="tool"
            label={t("toolRail")}
          />
          <div className={cn("rounded-b-2xl px-3 pt-1 pb-3 sm:px-4 sm:pb-4", TRAY_SURFACE)}>
            {/* A search that found nothing still renders the table: the box
                that found nothing is in its toolbar, and taking it away would
                leave no way to unsay the search. */}
            {isLoading ? (
              <SkeletonRegion label={t("loading")}>
                <TableSkeleton rows={5} columns={5} pagination />
              </SkeletonRegion>
            ) : isError ? (
              <p className="p-2 text-destructive text-sm">{t("loadError")}</p>
            ) : totalCount === 0 && !query ? (
              <Card>
                <CardHeader>
                  <CardTitle>{t("empty.title")}</CardTitle>
                  <CardDescription>{emptyDescription}</CardDescription>
                </CardHeader>
              </Card>
            ) : (
              <ToolTable
                tool={selected}
                rows={rows}
                initiatives={initiatives}
                communities={communityNames}
                totalCount={totalCount}
                {...table}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

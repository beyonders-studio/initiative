/**
 * Community-wide search results.
 *
 * Tabs by KIND of thing rather than one per tool, and no counts on any of
 * them: a tab is a place to look, not a reported quantity. Per-tool tabs would
 * privilege projects and files — an artifact of them being the two core
 * tools — and would reflow every time a tool is added.
 *
 * A tab is a differently scoped query, not a filter over one, so the tab a
 * reader is on is the only scope that runs. The others are asked for a single
 * row, which is enough to show a tab with nothing behind it as disabled rather
 * than let the reader click through to an empty page.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { Search, SearchX, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MemberResultRow } from "@/components/search/MemberResultRow";
import { SearchCategoryTabs } from "@/components/search/SearchCategoryTabs";
import { SearchResultList } from "@/components/search/SearchResultRow";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunitySearch } from "@/hooks/useSearch";
import { useUserSearch } from "@/hooks/useUsers";
import {
  categoryEntityTypes,
  DEFAULT_SEARCH_CATEGORY,
  isSearchCategory,
  SEARCH_CATEGORIES,
  type SearchCategory,
  TOOL_ENTITY_TYPES,
} from "@/lib/searchResults";
import { Input } from "@/ui/input";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { PaginationBar } from "@/ui/pagination-bar";
import { StatusMessage } from "@/ui/status-message";
import { Switch } from "@/ui/switch";
import { Tabs, TabsContent } from "@/ui/tabs";

/** A page of one category. */
const PAGE_SIZE = 20;

export function SearchPage() {
  const { t } = useTranslation(["search", "common"]);
  const navigate = useNavigate();
  const { activeCommunity } = useCommunities();
  const search = useSearch({ strict: false }) as {
    q?: string;
    tab?: string;
    page?: number;
    archived?: true;
  };

  const query = (search.q ?? "").trim();
  const tab: SearchCategory = isSearchCategory(search.tab) ? search.tab : DEFAULT_SEARCH_CATEGORY;
  const page = search.page && search.page >= 1 ? search.page : 1;
  const includeArchived = search.archived === true;

  // The URL is the query's home — a result page has to be linkable. The input
  // is local so typing stays responsive, and the two are reconciled through the
  // last value committed: without that, a commit landing mid-word would put the
  // older query back in the box.
  const [input, setInput] = useState(search.q ?? "");
  const committed = useRef(query);
  const debounced = useDebouncedValue(input.trim(), 250);

  useEffect(() => {
    if (query === committed.current) return;
    committed.current = query;
    setInput(query);
  }, [query]);

  useEffect(() => {
    if (debounced === committed.current) return;
    committed.current = debounced;
    void navigate({
      to: ".",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        q: debounced || undefined,
        page: undefined,
      }),
      replace: true,
    });
  }, [debounced, navigate]);

  const setTab = (next: string) => {
    void navigate({
      to: ".",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        tab: isSearchCategory(next) && next !== DEFAULT_SEARCH_CATEGORY ? next : undefined,
        page: undefined,
      }),
    });
  };

  // Archived work is out of the way by default; asking for it is a different
  // question, so it resets the page rather than paging into a longer answer.
  const setIncludeArchived = (next: boolean) => {
    void navigate({
      to: ".",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        archived: next ? (true as const) : undefined,
        page: undefined,
      }),
    });
  };

  const setPage = useCallback(
    (next: number, replace = false) => {
      void navigate({
        to: ".",
        search: (prev: Record<string, unknown>) => ({ ...prev, page: next > 1 ? next : undefined }),
        replace,
      });
    },
    [navigate]
  );

  const enabled = query.length > 0;
  // `null` for members, who are not in the index: they are asked for from the
  // roster instead, a tab further down.
  const indexTypes = categoryEntityTypes(tab);
  const results = useCommunitySearch(
    {
      search: query,
      types: indexTypes ?? TOOL_ENTITY_TYPES,
      page,
      page_size: PAGE_SIZE,
      ...(includeArchived ? { include_archived: true } : {}),
    },
    { enabled: enabled && indexTypes !== null }
  );
  const members = useUserSearch({
    search: query,
    page,
    pageSize: PAGE_SIZE,
    enabled: enabled && indexTypes === null,
  });

  // A page past the end of the answer — a link from before the content moved,
  // or a query that has since narrowed. Left alone it reads as "nothing
  // matched", which is the opposite of what happened, so it corrects itself
  // back onto the last page that has results.
  const total = indexTypes === null ? settledMemberTotal(members) : settledTotal(results);
  const lastPage = total === undefined ? undefined : Math.max(1, Math.ceil(total / PAGE_SIZE));
  const outOfRange = lastPage !== undefined && page > lastPage;
  useEffect(() => {
    if (!outOfRange || lastPage === undefined) return;
    setPage(lastPage, true);
  }, [outOfRange, lastPage, setPage]);

  const items = results.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <h1 className="font-semibold text-3xl tracking-tight">
          {activeCommunity
            ? t("search:titleInCommunity", { communityName: activeCommunity.name })
            : t("search:title")}
        </h1>
        <div className="relative max-w-2xl">
          <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            className="pl-9"
            autoFocus
            aria-label={t("search:title")}
            placeholder={t("search:placeholder", {
              communityName: activeCommunity?.name ?? t("common:appName"),
            })}
          />
        </div>
      </div>

      {!enabled ? (
        <StatusMessage
          icon={<Search />}
          title={t("search:prompt.title")}
          description={t("search:prompt.description")}
        />
      ) : (
        <Tabs value={tab} onValueChange={setTab} className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <SearchCategoryTabs />
            {tab !== "member" && (
              <div className="flex items-center gap-2">
                <Switch
                  id="search-include-archived"
                  checked={includeArchived}
                  onCheckedChange={setIncludeArchived}
                />
                <label htmlFor="search-include-archived" className="text-muted-foreground text-sm">
                  {t("search:includeArchived")}
                </label>
              </div>
            )}
          </div>

          {SEARCH_CATEGORIES.map((category) => (
            <TabsContent key={category} value={category} className="space-y-1">
              {category === "member" ? (
                <MemberResults
                  members={members}
                  query={query}
                  page={page}
                  outOfRange={outOfRange}
                  onPageChange={setPage}
                />
              ) : results.isLoading || outOfRange ? (
                <Loading />
              ) : results.isError ? (
                <SearchFailed />
              ) : items.length === 0 ? (
                <NoResults query={query} />
              ) : (
                <>
                  {results.data?.fuzzy && (
                    <p className="px-3 pb-2 text-muted-foreground text-sm">
                      {t("search:closeMatches", { query })}
                    </p>
                  )}
                  <SearchResultList hits={items} />
                  <PaginationBar
                    className="pt-2"
                    page={page}
                    pageSize={PAGE_SIZE}
                    totalCount={results.data?.total_count ?? 0}
                    hasNext={results.data?.has_next ?? false}
                    onPageChange={setPage}
                  />
                </>
              )}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}

/**
 * How many things this query matched, or `undefined` while that isn't known
 * yet.
 *
 * The previous query's results stay on screen while a new one is in flight, so
 * that a reader typing isn't left staring at an empty page. Their total belongs
 * to the query that is leaving: it says nothing about how many pages the
 * arriving one has, or whether its tab holds anything. Anything drawing a
 * conclusion from a total reads it through here.
 */
function settledTotal(query: ReturnType<typeof useCommunitySearch>): number | undefined {
  if (query.isPlaceholderData || !query.isFetched) return undefined;
  return query.data?.total_count;
}

function Loading() {
  return (
    <SkeletonRegion className="py-2">
      <ListSkeleton rows={6} />
    </SkeletonRegion>
  );
}

/**
 * The question never got an answer.
 *
 * Distinct from nothing having matched: that is something the index said, and
 * this is the index not having been reached. Told apart so the page does not
 * report a community as empty on the strength of a request that failed.
 */
function SearchFailed() {
  const { t } = useTranslation("search");
  return (
    <StatusMessage
      icon={<TriangleAlert />}
      title={t("failed.title")}
      description={t("failed.description")}
    />
  );
}

function NoResults({ query }: { query: string }) {
  const { t } = useTranslation("search");
  return (
    <StatusMessage
      icon={<SearchX />}
      title={t("empty.title", { query })}
      description={t("empty.description")}
    />
  );
}

/** The member roster's own total, once it belongs to this query. */
function settledMemberTotal(members: ReturnType<typeof useUserSearch>): number | undefined {
  if (members.isPlaceholderData || !members.isFetched) return undefined;
  return members.data?.total_count;
}

/**
 * The Members tab.
 *
 * A different question from the rest of the page — who is here, rather than
 * what is here — so it asks the roster rather than the index, and shows people
 * rather than results. Its own component so that difference is visible rather
 * than buried in a branch.
 */
function MemberResults({
  members,
  query,
  page,
  outOfRange,
  onPageChange,
}: {
  members: ReturnType<typeof useUserSearch>;
  query: string;
  page: number;
  outOfRange: boolean;
  onPageChange: (page: number) => void;
}) {
  const items = members.data?.items ?? [];
  if (members.isLoading || outOfRange) return <Loading />;
  if (members.isError) return <SearchFailed />;
  if (items.length === 0) return <NoResults query={query} />;
  return (
    <>
      {items.map((member) => (
        <MemberResultRow key={member.id} member={member} />
      ))}
      <PaginationBar
        className="pt-2"
        page={page}
        pageSize={PAGE_SIZE}
        totalCount={members.data?.total_count ?? 0}
        hasNext={Boolean(members.data?.has_next)}
        onPageChange={onPageChange}
      />
    </>
  );
}

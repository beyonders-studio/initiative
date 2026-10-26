/**
 * The hooks every tool repeats, written once.
 *
 * Nine tools ask the API the same six questions — list me, read one of me,
 * create, update, delete, share —
 * over endpoints that differ only in their names. Each `use<Tool>s.ts` used to
 * spell all six out; they are built here from the generated client instead,
 * and that file re-exports them under the names its callers already use.
 *
 * Cache keys come from the generated key builders and invalidation from the
 * `q.*` descriptions in `@/api/query-keys`, so a tool's queries are named in
 * exactly one place however they are reached.
 *
 * `TOOL_HOOKS` below is the table, keyed by `Tool`, and it says tool by tool
 * which of the six come from here. A hook that genuinely differs — a list
 * that walks every page, a create that also links the new row to a project —
 * is absent from that tool's entry and stays hand-written in its own file,
 * rather than being reached by a flag here.
 *
 * Two questions are asked for EVERY tool, however its hook is written: one
 * page of me in this community, one page of me across all of them. Those two
 * are in the table as query options rather than hooks, because the surfaces that ask them ask every tool at once and
 * hand the lot to `useQueries` — a hook cannot be called in a loop. A tool
 * whose hook is hand-written still declares its options here, so the query is
 * described once and the hand-written hook wraps these rather than repeating
 * the key.
 */

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createCalendar,
  deleteCalendar,
  duplicateCalendar,
  getListCalendarsQueryKey,
  getReadCalendarQueryKey,
  listCalendars,
  readCalendar,
  setCalendarGrants,
  updateCalendar,
} from "@/api/generated/calendars/calendars";
import {
  createCatalog,
  deleteCatalog,
  duplicateCatalog,
  getListCatalogsQueryKey,
  getReadCatalogQueryKey,
  listCatalogs,
  readCatalog,
  setCatalogGrants,
  updateCatalog,
} from "@/api/generated/catalogs/catalogs";
import {
  createCounterGroup,
  deleteCounterGroup,
  duplicateCounterGroup,
  getListCounterGroupsQueryKey,
  getReadCounterGroupQueryKey,
  listCounterGroups,
  readCounterGroup,
  setCounterGroupGrants,
  updateCounterGroup,
} from "@/api/generated/counters/counters";
import {
  createDashboard,
  deleteDashboard,
  duplicateDashboard,
  getListDashboardsQueryKey,
  getReadDashboardQueryKey,
  listDashboards,
  readDashboard,
  setDashboardGrants,
  updateDashboard,
} from "@/api/generated/dashboards/dashboards";
import {
  createFile,
  deleteFile,
  duplicateFile,
  getListFilesQueryKey,
  getReadFileQueryKey,
  listFiles,
  readFile,
  setFileGrants,
  updateFile,
} from "@/api/generated/files/files";
import type {
  ListFilesParams,
  ResourceGrantSchema,
  ToolDuplicateRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  getListMyCalendarsQueryKey,
  getListMyCatalogsQueryKey,
  getListMyCounterGroupsQueryKey,
  getListMyDashboardsQueryKey,
  getListMyFilesQueryKey,
  getListMyPostsQueryKey,
  getListMyProjectsQueryKey,
  getListMyQueuesQueryKey,
  getListMyWikisQueryKey,
  listMyCalendars,
  listMyCatalogs,
  listMyCounterGroups,
  listMyDashboards,
  listMyFiles,
  listMyPosts,
  listMyProjects,
  listMyQueues,
  listMyWikis,
} from "@/api/generated/my-tools/my-tools";
import {
  createPost,
  deletePost,
  duplicatePost,
  getListPostsQueryKey,
  getReadPostQueryKey,
  listPosts,
  readPost,
  setPostGrants,
  updatePost,
} from "@/api/generated/posts/posts";
import {
  createProject,
  deleteProject,
  duplicateProject,
  getListProjectsQueryKey,
  getReadProjectQueryKey,
  listProjects,
  readProject,
  setProjectGrants,
  updateProject,
} from "@/api/generated/projects/projects";
import {
  createQueue,
  deleteQueue,
  duplicateQueue,
  getListQueuesQueryKey,
  getReadQueueQueryKey,
  listQueues,
  readQueue,
  setQueueGrants,
  updateQueue,
} from "@/api/generated/queues/queues";
import {
  createWiki,
  deleteWiki,
  duplicateWiki,
  getListWikisQueryKey,
  getReadWikiQueryKey,
  listWikis,
  readWiki,
  setWikiGrants,
  updateWiki,
} from "@/api/generated/wikis/wikis";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { toolCamelPlural } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** A cache key, as the generated key builders return one. */
type CacheKey = readonly unknown[];

/** Copies one into an initiative: `POST /{tool}/{id}/duplicate`, one route shape for every tool. */
type Duplicate = (
  communityId: number,
  id: number,
  data: ToolDuplicateRequest
) => Promise<Duplicated>;

/** What a duplicate answers with: the copy's id and where it went. */
type Duplicated = { id: number; initiative_id: number | null };

/**
 * The narrowing every tool's community-wide list understands.
 *
 * The nine endpoints accept far more than this between them — a file has
 * tags and a type, a calendar has a scope — but these are the terms they ALL
 * take, which is what lets one caller drive every tool from one params object.
 * A tool's own list hook keeps its own generated params type and can ask for
 * the rest.
 */
export interface ToolListParams {
  page?: number;
  page_size?: number;
  search?: string | null;
  sort_by?: string | null;
  sort_dir?: string | null;
  archived?: boolean | null;
  initiative_id?: number | null;
  /** A templates view's switch, for the tools that have one (`toolViewParams`). */
  is_template?: boolean | null;
  /** Rows carrying any of these tags. */
  tag_ids?: number[] | null;
}

/**
 * The same, for the cross-community `/me` twin: no initiative (there is no order
 * across communities to put one in), a set of communities instead, and the
 * "only what I wrote" view.
 */
export interface ToolMyListParams {
  community_ids?: number[] | null;
  search?: string | null;
  created_by_me?: boolean;
  sort_by?: string | null;
  sort_dir?: string | null;
  page?: number;
  page_size?: number;
}

/**
 * What every tool's list answers with — what a caller can count on before it
 * knows which tool it is holding.
 */
interface ToolListPage {
  items: unknown[];
  total_count: number;
  has_next: boolean;
}

// ── The six, each built from the endpoints that answer it ──────────────────
// Every builder takes the tool's endpoint record and reads only the fields it
// needs, so a tool that has no standard version of one hook simply leaves those
// fields out of its record and never calls that builder.

/**
 * One page of the tool's list, in this community and across every one at once.
 *
 * Options rather than hooks: the two tables that show one tool at a time ask
 * all nine and hand the lot to `useQueries`, and a hook cannot be called in a
 * loop. Both are declared for every tool, including the ones whose own
 * list hook is hand-written — those wrap these, so the key and the fetch are
 * written once wherever the list is reached from.
 */
const listQueries = <TList, TMyList, TParams, TMyParams>(endpoints: {
  listKey: (communityId: number, params?: TParams) => CacheKey;
  list: (communityId: number, params?: TParams) => Promise<TList>;
  myListKey: (params?: TMyParams) => CacheKey;
  myList: (params?: TMyParams) => Promise<TMyList>;
}) => ({
  listQuery: (communityId: number, params?: TParams) => ({
    queryKey: endpoints.listKey(communityId, params),
    queryFn: () => endpoints.list(communityId, params),
  }),
  myListQuery: (params?: TMyParams) => ({
    queryKey: endpoints.myListKey(params),
    queryFn: () => endpoints.myList(params),
  }),
});

/**
 * One page of the tool's community-wide list.
 *
 * `keepPreviousData` keeps the rows on screen while a changed page, search or
 * order is in flight, rather than replacing the table with a loading line on
 * every keystroke.
 */
const listHook = <TList, TParams>(endpoints: {
  listKey: (communityId: number, params?: TParams) => CacheKey;
  list: (communityId: number, params?: TParams) => Promise<TList>;
}) => {
  return (params?: TParams, options?: QueryOpts<TList>) => {
    const communityId = useActiveCommunityId();
    return useQuery<TList>({
      queryKey: endpoints.listKey(communityId, params),
      queryFn: () => endpoints.list(communityId, params),
      placeholderData: keepPreviousData,
      ...options,
    });
  };
};

/**
 * One row, as query options: for a caller that holds the tool as a value
 * rather than calling that tool's own hook — the page title reads whichever
 * tool the route is in. The same key and fetch `useDetail` uses, so the two
 * share one cache entry.
 */
const detailQueryOf =
  <TRead>(endpoints: {
    detailKey: (communityId: number, id: number) => CacheKey;
    detail: (communityId: number, id: number) => Promise<TRead>;
  }) =>
  (communityId: number, id: number) => ({
    queryKey: endpoints.detailKey(communityId, id),
    queryFn: () => endpoints.detail(communityId, id),
  });

/**
 * One row. `null` for an id the route has not resolved yet, which holds the
 * request rather than firing it at nothing; a caller's own `enabled` narrows
 * further and never widens.
 *
 * Never the previous row while another loads: a detail page that stays
 * mounted across a switch would render, and save, the last row under the new
 * one's id. It shows its loading state instead.
 */
const detailHook = <TRead>(endpoints: {
  detailKey: (communityId: number, id: number) => CacheKey;
  detail: (communityId: number, id: number) => Promise<TRead>;
}) => {
  const detailQuery = detailQueryOf(endpoints);
  return (id: number | null, options?: QueryOpts<TRead>) => {
    const communityId = useActiveCommunityId();
    const { enabled: userEnabled = true, ...rest } = options ?? {};
    return useQuery<TRead>({
      ...detailQuery(communityId, id!),
      enabled: id !== null && Number.isFinite(id) && userEnabled,
      placeholderData: undefined,
      ...rest,
    });
  };
};

const createHook = <TRead, TCreate>(
  endpoints: {
    create: (communityId: number, data: TCreate) => Promise<TRead>;
    tool: Tool;
  },
  errorKey: string
) => {
  return (options?: MutationOpts<TRead, TCreate>) =>
    useCommunityMutation<TRead, TCreate>(
      {
        mutationFn: (communityId, data) => endpoints.create(communityId, data),
        invalidate: () => invalidate(q.toolList(endpoints.tool)),
        errorKey,
      },
      options
    );
};

interface ToolWriteOptions {
  /**
   * Whether the update seeds the detail cache with what the PATCH answered.
   *
   * The response is the row a refetch would fetch, so seeding it beats leaving
   * the cache on the pre-save copy until the refetch lands. Without it a canvas
   * that drops its local draft the moment a save succeeds renders the *old*
   * server layout for a beat — a dragged widget visibly snaps back to where it
   * came from, then jumps forward again when the refetch arrives.
   */
  seedsDetailOnUpdate?: boolean;
  /**
   * Whether a save refreshes the relationship graph: a body save rewrites
   * what the body refers to, which is what the other end's "linked from"
   * panel reads.
   */
  refreshesRelationships?: boolean;
}

const updateHook = <TRead, TUpdate>(
  endpoints: {
    update: (communityId: number, id: number, data: TUpdate) => Promise<TRead>;
    detailKey: (communityId: number, id: number) => CacheKey;
    tool: Tool;
  },
  errorKey: string,
  { seedsDetailOnUpdate = false, refreshesRelationships = false }: ToolWriteOptions = {}
) => {
  return (id: number, options?: MutationOpts<TRead, TUpdate>) => {
    const communityId = useActiveCommunityId();
    const client = useQueryClient();
    return useCommunityMutation<TRead, TUpdate>(
      {
        mutationFn: (community, data) => endpoints.update(community, id, data),
        invalidate: (updated) => {
          if (seedsDetailOnUpdate) {
            client.setQueryData(endpoints.detailKey(communityId, id), updated);
          }
          return refreshesRelationships
            ? invalidate(q.tool(endpoints.tool, id), q.relationships())
            : invalidate(q.tool(endpoints.tool, id));
        },
        errorKey,
      },
      options
    );
  };
};

const deleteHook = (
  endpoints: {
    remove: (communityId: number, id: number) => Promise<void>;
    tool: Tool;
  },
  errorKey: string
) => {
  return (options?: MutationOpts<void, number>) =>
    useCommunityMutation<void, number>(
      {
        mutationFn: (communityId, id) => endpoints.remove(communityId, id),
        invalidate: () => invalidate(q.toolList(endpoints.tool)),
        errorKey,
      },
      options
    );
};

/** The whole non-owner sharing state at once (unified resource sharing). */
const grantsHook = <TRead>(
  endpoints: {
    setGrants: (communityId: number, id: number, grants: ResourceGrantSchema[]) => Promise<TRead>;
    tool: Tool;
  },
  errorKey: string
) => {
  return (id: number, options?: MutationOpts<TRead, ResourceGrantSchema[]>) =>
    useCommunityMutation<TRead, ResourceGrantSchema[]>(
      {
        mutationFn: (communityId, grants) => endpoints.setGrants(communityId, id, grants),
        invalidate: () => invalidate(q.tool(endpoints.tool, id)),
        errorKey,
      },
      options
    );
};

/** Everything the generated client offers for a tool with no exceptions. */
interface ToolEndpoints<TRead, TList, TMyList, TCreate, TUpdate, TParams> {
  listKey: (communityId: number, params?: TParams) => CacheKey;
  list: (communityId: number, params?: TParams) => Promise<TList>;
  myListKey: (params?: ToolMyListParams) => CacheKey;
  myList: (params?: ToolMyListParams) => Promise<TMyList>;
  detailKey: (communityId: number, id: number) => CacheKey;
  detail: (communityId: number, id: number) => Promise<TRead>;
  create: (communityId: number, data: TCreate) => Promise<TRead>;
  update: (communityId: number, id: number, data: TUpdate) => Promise<TRead>;
  remove: (communityId: number, id: number) => Promise<void>;
  setGrants: (communityId: number, id: number, grants: ResourceGrantSchema[]) => Promise<TRead>;
  duplicate: Duplicate;
  /** Which tool this is — what its writes make stale follows from it. */
  tool: Tool;
}

/**
 * All six, for a tool whose list and whose four writes are the standard ones.
 * Their failures read the tool's own `error` string.
 */
const makeToolHooks = <TRead, TList, TMyList, TCreate, TUpdate, TParams>(
  endpoints: ToolEndpoints<TRead, TList, TMyList, TCreate, TUpdate, TParams>,
  options?: ToolWriteOptions
) => {
  const errorKey = `${toolCamelPlural(endpoints.tool)}:error`;
  return {
    ...listQueries(endpoints),
    detailQuery: detailQueryOf(endpoints),
    create: endpoints.create,
    duplicate: endpoints.duplicate,
    remove: endpoints.remove,
    useList: listHook(endpoints),
    useDetail: detailHook(endpoints),
    useCreate: createHook(endpoints, errorKey),
    useUpdate: updateHook(endpoints, errorKey, options),
    useDelete: deleteHook(endpoints, errorKey),
    useSetGrants: grantsHook(endpoints, errorKey),
  };
};

// ── One record per tool ──────────────────────────────────────────────────────

const calendarEndpoints = {
  listKey: getListCalendarsQueryKey,
  list: listCalendars,
  myListKey: getListMyCalendarsQueryKey,
  myList: listMyCalendars,
  detailKey: getReadCalendarQueryKey,
  detail: readCalendar,
  create: createCalendar,
  update: updateCalendar,
  remove: deleteCalendar,
  setGrants: setCalendarGrants,
  duplicate: duplicateCalendar,
  tool: Tool.calendar,
};

const counterGroupEndpoints = {
  listKey: getListCounterGroupsQueryKey,
  list: listCounterGroups,
  myListKey: getListMyCounterGroupsQueryKey,
  myList: listMyCounterGroups,
  detailKey: getReadCounterGroupQueryKey,
  detail: readCounterGroup,
  create: createCounterGroup,
  update: updateCounterGroup,
  remove: deleteCounterGroup,
  setGrants: setCounterGroupGrants,
  duplicate: duplicateCounterGroup,
  tool: Tool.counter_group,
};

const dashboardEndpoints = {
  listKey: getListDashboardsQueryKey,
  list: listDashboards,
  myListKey: getListMyDashboardsQueryKey,
  myList: listMyDashboards,
  detailKey: getReadDashboardQueryKey,
  detail: readDashboard,
  create: createDashboard,
  update: updateDashboard,
  remove: deleteDashboard,
  setGrants: setDashboardGrants,
  duplicate: duplicateDashboard,
  tool: Tool.dashboard,
};

// Only a file's create is hand-written (`useFiles.ts`): it copies a
// template client-side and can link the new row to a project.
const fileEndpoints = {
  listKey: getListFilesQueryKey,
  // `page_size: 0` asks for the complete set, which the server serves in
  // windows; this walks them. A positive page size passes straight through.
  list: (communityId: number, params?: ListFilesParams) =>
    fetchAllPages((p) => listFiles(communityId, p), params ?? {}),
  myListKey: getListMyFilesQueryKey,
  myList: listMyFiles,
  detailKey: getReadFileQueryKey,
  detail: readFile,
  update: updateFile,
  remove: deleteFile,
  setGrants: setFileGrants,
  tool: Tool.file,
};

const fileHooks = {
  ...listQueries(fileEndpoints),
  detailQuery: detailQueryOf(fileEndpoints),
  create: createFile,
  duplicate: duplicateFile,
  remove: fileEndpoints.remove,
  useList: listHook(fileEndpoints),
  useDetail: detailHook(fileEndpoints),
  useUpdate: updateHook(fileEndpoints, "files:error", {
    seedsDetailOnUpdate: true,
    refreshesRelationships: true,
  }),
  useDelete: deleteHook(fileEndpoints, "files:error"),
  useSetGrants: grantsHook(fileEndpoints, "files:settings.updateAccessError"),
};

const catalogEndpoints = {
  listKey: getListCatalogsQueryKey,
  list: listCatalogs,
  myListKey: getListMyCatalogsQueryKey,
  myList: listMyCatalogs,
  detailKey: getReadCatalogQueryKey,
  detail: readCatalog,
  create: createCatalog,
  update: updateCatalog,
  remove: deleteCatalog,
  setGrants: setCatalogGrants,
  duplicate: duplicateCatalog,
  tool: Tool.catalog,
};

const postEndpoints = {
  listKey: getListPostsQueryKey,
  list: listPosts,
  myListKey: getListMyPostsQueryKey,
  myList: listMyPosts,
  detailKey: getReadPostQueryKey,
  detail: readPost,
  create: createPost,
  update: updatePost,
  remove: deletePost,
  setGrants: setPostGrants,
  duplicate: duplicatePost,
  tool: Tool.post,
};

const projectEndpoints = {
  listKey: getListProjectsQueryKey,
  list: listProjects,
  myListKey: getListMyProjectsQueryKey,
  myList: listMyProjects,
  detailKey: getReadProjectQueryKey,
  detail: readProject,
  create: createProject,
  update: updateProject,
  remove: deleteProject,
  setGrants: setProjectGrants,
  duplicate: duplicateProject,
  tool: Tool.project,
};

const queueEndpoints = {
  listKey: getListQueuesQueryKey,
  list: listQueues,
  myListKey: getListMyQueuesQueryKey,
  myList: listMyQueues,
  detailKey: getReadQueueQueryKey,
  detail: readQueue,
  create: createQueue,
  update: updateQueue,
  remove: deleteQueue,
  setGrants: setQueueGrants,
  duplicate: duplicateQueue,
  tool: Tool.queue,
};

const wikiEndpoints = {
  listKey: getListWikisQueryKey,
  list: listWikis,
  myListKey: getListMyWikisQueryKey,
  myList: listMyWikis,
  detailKey: getReadWikiQueryKey,
  detail: readWiki,
  create: createWiki,
  update: updateWiki,
  remove: deleteWiki,
  setGrants: setWikiGrants,
  duplicate: duplicateWiki,
  tool: Tool.wiki,
};

/**
 * What every tool's entry carries, whatever else it has. The cross-tool loops
 * read this and nothing more, and `Record<Tool, …>` means a new `Tool` member
 * fails to compile here until it has them.
 *
 * The two list entries are stated in the common terms — a tool's own params
 * type is richer, and its own hook still takes that — so the constraint below
 * is also the check that every tool's list really does accept the narrowing
 * one caller drives all nine with.
 */
interface ToolQueries {
  listQuery: (
    communityId: number,
    params?: ToolListParams
  ) => { queryKey: CacheKey; queryFn: () => Promise<ToolListPage> };
  myListQuery: (params?: ToolMyListParams) => {
    queryKey: CacheKey;
    queryFn: () => Promise<ToolListPage>;
  };
  /** Reads one — what the page title asks of whichever tool the route is in. */
  detailQuery: (
    communityId: number,
    id: number
  ) => { queryKey: CacheKey; queryFn: () => Promise<{ name: string }> };
  /** Makes one from a name and its initiative — what `useCreateTool` sends every tool. */
  create: (
    communityId: number,
    data: { name: string; initiative_id: number }
  ) => Promise<{ id: number }>;
  /** Copies one into an initiative — what the settings page's duplicate card sends. */
  duplicate: Duplicate;
  /** Deletes one — what a list's bulk delete sends, once a row. */
  remove: (communityId: number, id: number) => Promise<void>;
}

/**
 * Which of the six each tool takes from here.
 *
 * A tool listed with `makeToolHooks` takes all six; one written out takes the
 * ones it names and keeps the rest hand-written, for the reason stated above
 * its endpoint record.
 */
export const TOOL_HOOKS = {
  [Tool.project]: makeToolHooks(projectEndpoints, { seedsDetailOnUpdate: true }),
  [Tool.file]: fileHooks,
  [Tool.queue]: makeToolHooks(queueEndpoints),
  [Tool.counter_group]: makeToolHooks(counterGroupEndpoints),
  [Tool.calendar]: makeToolHooks(calendarEndpoints, { seedsDetailOnUpdate: true }),
  [Tool.dashboard]: makeToolHooks(dashboardEndpoints, { seedsDetailOnUpdate: true }),
  [Tool.post]: makeToolHooks(postEndpoints, {
    seedsDetailOnUpdate: true,
    refreshesRelationships: true,
  }),
  [Tool.catalog]: makeToolHooks(catalogEndpoints, { seedsDetailOnUpdate: true }),
  [Tool.wiki]: makeToolHooks(wikiEndpoints),
} satisfies Record<Tool, ToolQueries>;

/**
 * One tool's community-wide list query, typed as any tool's: for a caller that
 * holds the tool as a value and only needs what every list answers with.
 */
export const toolListQuery = (tool: Tool, communityId: number, params?: ToolListParams) => {
  const listQuery: ToolQueries["listQuery"] = TOOL_HOOKS[tool].listQuery;
  return listQuery(communityId, params);
};

/** One row of a tool, typed as any tool's: for a caller that holds the tool
 *  as a value and only needs what every row carries. */
export const toolDetailQuery = (tool: Tool, communityId: number, id: number) => {
  const detailQuery: ToolQueries["detailQuery"] = TOOL_HOOKS[tool].detailQuery;
  return detailQuery(communityId, id);
};

/**
 * Copy one of `tool` into an initiative, its own unless `data` names another.
 * The new one is in that tool's lists, so they refetch.
 */
export const useDuplicateTool = (
  tool: Tool,
  options?: MutationOpts<Duplicated, { id: number; data: ToolDuplicateRequest }>
) =>
  useCommunityMutation<Duplicated, { id: number; data: ToolDuplicateRequest }>(
    {
      mutationFn: (communityId, { id, data }) => TOOL_HOOKS[tool].duplicate(communityId, id, data),
      invalidate: () => invalidate(q.toolList(tool)),
      errorKey: "common:toolSettings.duplicate.error",
    },
    options
  );

/**
 * Every request of a bulk action, run to the end. When some fail, the list is
 * refreshed anyway — the ones that landed are real — and the first failure is
 * what the action reports.
 */
const settleAll = async <T>(tool: Tool, requests: Promise<T>[]): Promise<T[]> => {
  const results = await Promise.allSettled(requests);
  const failed = results.find((result) => result.status === "rejected");
  if (failed) {
    void invalidate(q.toolList(tool));
    throw failed.reason;
  }
  return results.map((result) => (result as PromiseFulfilledResult<T>).value);
};

/** A copy of each of `ids` beside its original, named as the server names one. */
export const useDuplicateTools = (tool: Tool, options?: MutationOpts<Duplicated[], number[]>) =>
  useCommunityMutation<Duplicated[], number[]>(
    {
      mutationFn: (communityId, ids) =>
        settleAll(
          tool,
          ids.map((id) => TOOL_HOOKS[tool].duplicate(communityId, id, {}))
        ),
      invalidate: () => invalidate(q.toolList(tool)),
      errorKey: "common:bulkActions.duplicateError",
    },
    options
  );

/** Delete every one of `ids`. */
export const useDeleteTools = (tool: Tool, options?: MutationOpts<void, number[]>) =>
  useCommunityMutation<void, number[]>(
    {
      mutationFn: async (communityId, ids) => {
        await settleAll(
          tool,
          ids.map((id) => TOOL_HOOKS[tool].remove(communityId, id))
        );
      },
      invalidate: () => invalidate(q.toolList(tool)),
      errorKey: "common:bulkActions.deleteError",
    },
    options
  );

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { loadDashboardData } from "@/api/generated/dashboards/dashboards";
import type {
  DashboardDataResponse,
  DashboardWidgetData,
  QueryResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { runQuery } from "@/api/generated/query/query";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { busyRetryDelay, inQueryLane, retryWhileBusy } from "@/lib/queryLane";
import type { QueryOpts } from "@/types/query";

/**
 * Run one statement and cache what it returned.
 *
 * A read that happens to be spelled as a POST — a statement is too long for a
 * query string and would be logged everywhere one goes. So the caching this
 * needs is stated here rather than taken from the generated mutation hook,
 * which has none: two tiles running the same statement share one request, and a
 * canvas of them re-runs on the same terms as every other list on the page.
 *
 * The key carries the statement itself, because the statement *is* the request
 * — and the initiative beside it, because the same statement asked about two
 * initiatives is two different answers.
 */
export const sqlQueryKey = (communityId: number, sql: string, initiativeId?: number) =>
  ["query", communityId, sql, initiativeId ?? null] as const;

/** A canvas's widgets, answered together. Keyed by the dashboard rather than
 *  by what its widgets ask, because the statements and a plug-in widget's
 *  parameters are the server's to look up — the whole point of the endpoint
 *  behind it. */
export const dashboardDataKey = (communityId: number, dashboardId: number) =>
  ["query", "dashboard", communityId, dashboardId] as const;

/**
 * `initiativeId` narrows the answer to one initiative.
 *
 * A statement names datasets, not a scope, so a surface that belongs to an
 * initiative has to say which one or it gets every initiative its reader is in.
 * The narrowing is applied by the policies on the tables the statement reads,
 * so it removes rows and never adds any.
 */
export const useSqlQuery = (
  sql: string | null,
  initiativeId: number | undefined,
  options?: QueryOpts<QueryResponse>
) => {
  const communityId = useActiveCommunityId();
  return useQuery<QueryResponse>({
    queryKey: sqlQueryKey(communityId, sql ?? "", initiativeId),
    queryFn: () =>
      inQueryLane(communityId, () =>
        runQuery(communityId, { sql: sql ?? "", initiative_id: initiativeId })
      ),
    // Not retried: a statement either resolves against the registry or it does
    // not, and a refused one is refused the same way every time. A community with
    // no free slot is the one failure that says nothing about the statement,
    // so it — and only it — comes back.
    retry: retryWhileBusy,
    retryDelay: busyRetryDelay,
    ...options,
    enabled: Boolean(sql) && (options?.enabled ?? true),
  });
};

/**
 * What one widget of one dashboard reads, as its canvas answered it: a
 * statement's rows in `data`, or a plug-in widget's rows and values in `plugin`.
 *
 * A canvas is read as a whole: one request answers every widget on it that
 * reads data, its statements run by the server as one statement, so the tiles
 * read the same moment and share the work. Each tile selects its own entry from
 * that answer. The request names the dashboard and nothing else: what runs is
 * each widget's stored statement, and each plug-in widget's endpoint with its
 * stored parameters, looked up server-side. That is what lets a dashboard show
 * rows a reader could not otherwise reach — the question is the one somebody
 * published, and a reader has no way to ask a different one of the same grants.
 */
export const useWidgetQuery = (
  dashboardId: number | null,
  widgetId: string | null,
  options?: { enabled?: boolean }
) => {
  const communityId = useActiveCommunityId();
  const addressed = Boolean(dashboardId && widgetId);
  const canvas = useQuery<DashboardDataResponse, Error, DashboardWidgetData | null>({
    queryKey: dashboardDataKey(communityId, dashboardId ?? 0),
    queryFn: () => loadDashboardData(communityId, dashboardId as number),
    select: (data) => data.widgets[widgetId ?? ""] ?? null,
    // Not retried, for the same reason: a statement either resolves against the
    // registry or it does not — except for a community with no free slot, which a
    // canvas can still meet while somebody else's is loading.
    retry: retryWhileBusy,
    retryDelay: busyRetryDelay,
    // A canvas re-renders with its dashboard momentarily unknown — while its
    // own read is in flight, or on the way back from one. Without this the key
    // changes under the tile and it blanks to a fresh entry with nothing in it,
    // so a dashboard that was showing figures shows none for a beat and then
    // shows them again. The last answer stays on screen until the next one is
    // ready.
    placeholderData: keepPreviousData,
    enabled: addressed && (options?.enabled ?? true),
  });
  const entry = canvas.data;
  return {
    data: entry?.result ?? undefined,
    plugin: entry?.plugin ?? undefined,
    isLoading: canvas.isLoading,
    // A widget the answer has nothing for has nothing stored to read, and one
    // with an error was refused on its own: both read as this tile's failure,
    // not the canvas's.
    isError: canvas.isError || (canvas.isSuccess && (entry === null || Boolean(entry?.error))),
    refetch: canvas.refetch,
  };
};

/** One change the realtime channel reported, as far as a canvas cares. */
export type CanvasChange = {
  resource?: { type: string; id: number };
  initiative_id?: number | null;
};

/**
 * Whether a canvas's answer is stale after these changes: one of them is to a
 * table a widget on it read, in the canvas's initiative or in the community's own.
 */
export const canvasIsStale = (
  data: DashboardDataResponse | undefined,
  changes: readonly CanvasChange[]
): boolean => {
  if (!data) return false;
  const read = new Set(
    Object.values(data.widgets).flatMap((entry) => entry.result?.relations ?? [])
  );
  return changes.some(
    (change) =>
      change.resource !== undefined &&
      read.has(change.resource.type) &&
      (change.initiative_id == null || change.initiative_id === data.initiative_id)
  );
};

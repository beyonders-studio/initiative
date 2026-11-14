/**
 * Resolve a widget's binding into the data envelope it renders from.
 *
 * The security shape of this file matters more than its size. A binding names a
 * *source*, never an endpoint — and each is fetched here through the same
 * ordinary hook the rest of the app uses, so the request is the viewer's own and
 * the six gates decide what comes back. A dashboard shared with someone who
 * cannot read the bound rows therefore shows them an empty widget, not the
 * author's data. Nothing a definition can say reaches a URL.
 *
 * Two bindings: a statement, which answers with columns and rows, and a
 * plug-in widget's endpoint, which answers with the plug-in's own rows and
 * values. A placed widget of either kind is answered with its canvas; the
 * config dialog's preview asks for its own. Every hook below is called
 * on every render with `enabled` gating rather than conditionally, because
 * hooks must be unconditional. Disabled queries cost nothing, and the ones that
 * do run share React Query's cache — two widgets running the same statement
 * issue one request between them, which is what keeps a dense canvas from
 * becoming a request storm.
 */

import { useCallback, useMemo, useRef } from "react";

import { resolvePluginBinding } from "@/api/pluginData";
import { usePluginData, usePluginWidgetCatalog } from "@/hooks/usePluginData";
import { useSqlQuery, useWidgetQuery } from "@/hooks/useSqlQuery";
import type { DataMeta, WidgetData, WidgetSource } from "@/lib/widgets/dataShapes";
import { WidgetErrorCode } from "@/lib/widgets/errors";
import { emptyDataFor, normalizeQueryRows } from "@/lib/widgets/normalize";

/** A normalized definition binding. Everything past `source` is the fetcher's
 *  to interpret — the backend deliberately does not re-declare these, so that
 *  each parameter lives with the code that consumes it.
 *
 *  The initiative is *not* among them: it comes from the dashboard the widget
 *  sits on, and the backend normalizer drops it from a stored binding. */
export interface WidgetBinding {
  source: WidgetSource;
  /** `query`: the statement to read. Checked and rewritten by the server before
   *  it runs — what is stored is what the author built, and what reaches
   *  Postgres is what the validator produced from it. */
  sql?: string | null;
  /** What was clicked to produce `sql`, so the builder reopens on it rather
   *  than leaving somebody to read their own statement back. Absent for a
   *  statement that did not come from the builder. */
  spec?: unknown;
  /** `plugin`: which installed plug-in, which of its sources, and the arguments the
   *  source declared. The binding names a listing and a source id — never an
   *  address. Where the plug-in lives comes from the deployment's registration, and
   *  only the server ever reads it. */
  plugin_uid?: string | null;
  endpoint_id?: string | null;
  params?: Record<string, unknown> | null;
}

export interface WidgetDataResult {
  data: WidgetData;
  /** A binding whose parameters the instance config has not filled in yet — the
   *  widget renders its own empty state rather than an error. */
  isUnbound: boolean;
  isLoading: boolean;
  /** The binding names a target, the fetch resolved, and the target is not
   *  there: deleted, or hidden from this viewer by the gates.
   *
   *  Deliberately distinct from {@link isUnbound}. They are opposite
   *  instructions — one asks the author to finish configuring a widget, the
   *  other says this viewer is not the person who can see the answer — and
   *  telling a reader to "configure this" invites them to repoint a binding
   *  that was never wrong. What the tile may *say* about it is bounded:
   *  absence, never the name or id of the thing that is absent. */
  isRestricted: boolean;
  /** Rows this viewer's own query matched, and whether the rows in `data` are a
   *  leading slice of them. Mirrors `data.meta`, hoisted for the tile chrome. */
  meta?: DataMeta;
  /** Re-run this binding's own queries. Lives here because this is the only
   *  place that knows which ones a source uses. */
  refetch: () => void;
  /** Set when the tile should draw an error instead of running the widget. */
  errorCode?: WidgetErrorCode;
}

/**
 * Resolve one widget's binding.
 *
 * `initiativeId` is the dashboard's own — every fetch below is scoped to it, and
 * a binding cannot say otherwise: dashboards are an initiative's tool, so a
 * widget reads that initiative and nothing else. Without an initiative nothing
 * is fetched at all (unbound, not community-wide), and a file fetched by id is
 * held against the initiative afterwards, so an id pointing into another one
 * resolves to absent — the same rendering as a deleted or unshared target.
 *
 * A statement is held against it the same way, but at the database rather than
 * afterwards: the initiative goes with the request, and the policies on the
 * tables the statement reads answer for that initiative alone. So a widget
 * cannot show another initiative's rows even to a reader who is in both.
 *
 * `widgetId` says which widget on that dashboard is asking, and only to have
 * what it *stores* read: its statement, or its plug-in's endpoint with its
 * parameters. Nothing here says what to run.
 *
 * `dashboardId` is the row the widget sits on. A widget not placed yet names it
 * too: a plug-in widget's preview is read for that dashboard.
 */
export function useWidgetData(
  binding: WidgetBinding,
  initiativeId: number | undefined,
  dashboardId?: number,
  widgetId?: string
): WidgetDataResult {
  const source = binding.source;
  const isPlugin = source === "plugin";
  const scoped = typeof initiativeId === "number" && Number.isFinite(initiativeId);

  // The statement is the request: no ids to resolve first. What it does not
  // say is *whose* — a statement names datasets, and the reader belongs to
  // however many initiatives they belong to — so the dashboard's own
  // initiative goes with it and the rows come back narrowed to it.
  // A widget already on a dashboard is read by naming it: the server looks the
  // statement up rather than being handed one. That is what carries a published
  // view — the rows a dashboard's own grants reach are shown through the
  // question somebody published, and there is no way to ask another of them.
  // A widget that is not placed yet — the config dialog's preview — has no
  // stored statement to look up, so it sends the one being written.
  // A widget nobody has pointed anywhere yet has no statement for the server to
  // look up, and asking for one is a request that can only come back empty
  // handed. The binding here is the effective one — the definition with the
  // instance config over it, which is what the server reads too — so this asks
  // the same question the lookup would.
  // A plug-in widget is placed the same way: the server reads its endpoint with
  // the parameters it stores.
  const bound = isPlugin
    ? Boolean(binding.plugin_uid && binding.endpoint_id)
    : Boolean(binding.sql);
  const addressed = typeof dashboardId === "number" && Boolean(widgetId) && bound;
  // Placed once is placed for good. A canvas re-renders with its dashboard
  // momentarily unknown, and a widget that flipped back to sending its own
  // statement for those renders would read a hook that has nothing retained —
  // so the tile would still blink empty, through the other of the two paths.
  // A widget does not move from a canvas to a dialog while it is mounted, so
  // remembering which of them it is costs nothing and settles it.
  const wasPlaced = useRef(false);
  if (addressed) wasPlaced.current = true;
  const placed = addressed || wasPlaced.current;
  const widgetQuery = useWidgetQuery(
    placed ? (dashboardId ?? null) : null,
    placed ? (widgetId ?? null) : null,
    { enabled: scoped && placed }
  );
  const sqlQuery = useSqlQuery(
    source === "query" && !placed ? (binding.sql ?? null) : null,
    scoped ? initiativeId : undefined,
    { enabled: scoped && source === "query" && !placed }
  );
  const answering = placed ? widgetQuery : sqlQuery;

  // The plug-in palette is one request per community, shared by every plug-in widget on the
  // canvas. It is what turns a binding's `plugin_uid` into an install id and tells
  // us what freshness the source asks for.
  const pluginCatalogQuery = usePluginWidgetCatalog(scoped && isPlugin);
  const pluginBinding = resolvePluginBinding(
    pluginCatalogQuery.data,
    binding.plugin_uid,
    binding.endpoint_id
  );
  // Only a plug-in widget that is not placed yet, the config dialog's preview,
  // reads its endpoint itself, with the parameters on the form.
  const pluginQuery = usePluginData({
    pluginId: pluginBinding?.entry.plugin_id,
    endpointId: binding.endpoint_id ?? undefined,
    dashboardId,
    params: binding.params ?? undefined,
    cacheTtlSeconds: pluginBinding?.source.cache_ttl_seconds,
    enabled: scoped && isPlugin && !placed,
  });

  // A placed widget is answered by its canvas entry, a refusal included, as a
  // statement's tile is; the preview's query keeps its last good body for its
  // key.
  const pluginAnswer = placed ? widgetQuery.plugin : pluginQuery.data;
  const pluginLoading = placed ? widgetQuery.isLoading : pluginQuery.isLoading;
  const pluginFailed = placed ? widgetQuery.isError : pluginQuery.isError;

  const refetch = useCallback(() => {
    if (placed || source === "query") void answering.refetch();
    else if (isPlugin) void pluginQuery.refetch();
  }, [placed, source, isPlugin, answering.refetch, pluginQuery.refetch]);

  return useMemo<WidgetDataResult>(() => {
    const unbound = (): WidgetDataResult => ({
      data: emptyDataFor(source),
      isLoading: false,
      isUnbound: true,
      isRestricted: false,
      refetch,
    });

    /**
     * The binding named a target and the fetch came back without it.
     *
     * Three outcomes, and they must not be collapsed: still in flight; the
     * request failed, which says nothing at all about what this viewer may
     * see; or it succeeded and the target genuinely is not there for them.
     * Only the third is an access outcome, and only it says so.
     */
    const absent = (query: { isLoading: boolean; isError: boolean }): WidgetDataResult => ({
      data: emptyDataFor(source),
      isLoading: query.isLoading,
      isUnbound: false,
      isRestricted: !query.isLoading && !query.isError,
      errorCode: query.isError ? WidgetErrorCode.DATA_UNAVAILABLE : undefined,
      refetch,
    });

    // No initiative, no data — fail closed rather than fan out.
    if (!scoped) return unbound();

    switch (source) {
      case "query": {
        if (!binding.sql) return unbound();
        // A statement the server would not run — a name the registry does not
        // have, a shape this surface does not accept, a cost ceiling — is the
        // author's to fix rather than this viewer's, so it reads as an error
        // and not as absence. Rows this viewer may not see are simply not
        // returned: the statement runs under their own session.
        if (answering.isError) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            errorCode: WidgetErrorCode.DATA_UNAVAILABLE,
            refetch,
          };
        }
        const answered = answering.data;
        const { columns, rows } = normalizeQueryRows(answered?.columns ?? [], answered?.rows ?? []);
        const meta: DataMeta = { total: rows.length, truncated: Boolean(answered?.truncated) };
        return {
          data: { source: "rows", columns, rows, meta },
          isLoading: answering.isLoading,
          isUnbound: false,
          isRestricted: false,
          refetch,
          meta,
        };
      }

      case "plugin": {
        // A definition that never had the plug-in filled in, or a preview with no
        // dashboard behind it. Neither is an error.
        if (
          !binding.plugin_uid ||
          !binding.endpoint_id ||
          (!placed && typeof dashboardId !== "number")
        ) {
          return unbound();
        }
        if (pluginCatalogQuery.isLoading) {
          return {
            data: emptyDataFor(source),
            isLoading: true,
            isUnbound: false,
            isRestricted: false,
            refetch,
          };
        }
        // A catalog that failed to load says nothing about whether this plug-in is
        // installed, so it must not be read as "not installed" — that would
        // render every plug-in widget on the dashboard as unconfigured and invite
        // someone to repoint bindings that were never wrong.
        if (pluginCatalogQuery.isError) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            refetch,
            errorCode: WidgetErrorCode.PLUGIN_UNAVAILABLE,
          };
        }
        // The catalog answered and the plug-in is not in it: uninstalled, or
        // switched off. Said plainly rather than rendered as an access outcome
        // — the definition is the community's and stays stored, and the tile
        // becomes the surface that asks for the plug-in to be reconnected.
        const pluginInstalled = (pluginCatalogQuery.data?.items ?? []).some(
          (item) => item.plugin_uid === binding.plugin_uid
        );
        if (!pluginInstalled) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            refetch,
            errorCode: WidgetErrorCode.PLUGIN_NOT_INSTALLED,
          };
        }
        // Installed, but its pinned version stopped offering this source —
        // the catalog answered, so this is absence rather than a failure.
        if (!pluginBinding) return absent({ isLoading: false, isError: false });
        // The preview's last good rows are more useful than nothing, so the
        // error tile is for when there is genuinely nothing to draw.
        if (pluginFailed && !pluginAnswer) {
          return {
            data: emptyDataFor(source),
            isLoading: false,
            isUnbound: false,
            isRestricted: false,
            refetch,
            errorCode: WidgetErrorCode.PLUGIN_UNAVAILABLE,
          };
        }
        const rows = pluginAnswer?.rows ?? [];
        const values = pluginAnswer?.values ?? {};
        const meta: DataMeta = { total: rows.length };
        return {
          // Already read through the endpoint's declared returns on the way
          // here. Nothing on this side looks inside either half; the sandbox is
          // handed them as values.
          data: { source, rows, values, meta },
          isLoading: pluginLoading,
          isUnbound: false,
          isRestricted: false,
          refetch,
          meta,
        };
      }

      default:
        return unbound();
    }
  }, [
    source,
    initiativeId,
    binding.sql,
    answering.data,
    answering.isLoading,
    answering.isError,
    scoped,
    placed,
    dashboardId,
    binding.plugin_uid,
    binding.endpoint_id,
    pluginBinding,
    pluginCatalogQuery.data,
    pluginCatalogQuery.isLoading,
    pluginCatalogQuery.isError,
    pluginAnswer,
    pluginLoading,
    pluginFailed,
    refetch,
  ]);
}

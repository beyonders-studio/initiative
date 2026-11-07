/**
 * Reading an installed plug-in's widgets, and the rows behind one.
 *
 * Two queries with deliberately different shapes.
 *
 * The **catalog** is per community and shared by every widget on the canvas: one
 * request tells the page which plug-ins contribute widgets and read endpoints,
 * which module draws each widget, and what each source declares. It changes only
 * when a plug-in is installed, upgraded, or turned off, so it is cached
 * generously.
 *
 * The **data** query is a plug-in widget's preview in its config dialog, read
 * with the parameters on the form; a placed widget is answered with its canvas.
 * It names the dashboard the widget is configured for. Its `staleTime`
 * comes from the plug-in's own `cache_ttl_seconds`, capped here as well as on the
 * server: a plug-in asking for a day of freshness would otherwise decide how stale
 * a dashboard may look, and the number crossing the wire is a request rather
 * than a promise.
 */

import { useQuery } from "@tanstack/react-query";

import {
  getPluginData,
  getPluginParamOptions,
  getPluginWidgetCatalog,
  type PluginDataResponse,
  type PluginParamOptionsResponse,
  type PluginWidgetCatalogResponse,
} from "@/api/pluginData";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunities } from "@/hooks/useCommunities";

/** The client's own ceiling on how long a plug-in's rows are reused, in seconds.
 *  Mirrors the proxy's `MAX_CACHE_TTL_SECONDS`; both exist because a listing
 *  must not be the thing that decides. */
export const MAX_PLUGIN_STALE_SECONDS = 300;

export const pluginWidgetCatalogKey = (communityId: number) =>
  ["plugin-widget-catalog", communityId] as const;

export const pluginDataKey = (
  communityId: number,
  pluginId: number,
  endpointId: string,
  dashboardId: number,
  params: Record<string, unknown> | undefined
) =>
  [
    "plugin-data",
    communityId,
    pluginId,
    endpointId,
    dashboardId,
    // Canonical, so the same parameters answered in a different order are
    // one request. Parameter values are scalars, so a sorted entry list is the
    // whole of it.
    JSON.stringify(Object.entries(params ?? {}).sort(([a], [b]) => (a < b ? -1 : 1))),
  ] as const;

/** Which widgets and read endpoints this community's installed plug-ins contribute.
 *  Enabled installs only — a disabled plug-in's widgets have nothing to draw. */
export const usePluginWidgetCatalog = (enabled = true) => {
  const communityId = useActiveCommunityId();
  // A guest reaches no plug-in of the community's.
  const communityWide = Boolean(useCommunities().activeCommunity?.can.community_wide);
  return useQuery<PluginWidgetCatalogResponse>({
    queryKey: pluginWidgetCatalogKey(communityId),
    queryFn: () => getPluginWidgetCatalog(communityId),
    enabled: enabled && communityWide && Number.isFinite(communityId) && communityId > 0,
    // Installing or upgrading a plug-in invalidates this explicitly; between those
    // it is effectively static for the page's lifetime.
    staleTime: 5 * 60_000,
  });
};

export interface PluginDataQuery {
  pluginId: number | undefined;
  endpointId: string | undefined;
  dashboardId: number | undefined;
  params?: Record<string, unknown>;
  /** The source's declared freshness, in seconds. Capped before use. */
  cacheTtlSeconds?: number;
  enabled?: boolean;
}

/** One plug-in data source, for this viewer, previewed for this dashboard. */
export const usePluginData = ({
  pluginId,
  endpointId,
  dashboardId,
  params,
  cacheTtlSeconds,
  enabled = true,
}: PluginDataQuery) => {
  const communityId = useActiveCommunityId();
  // Fail closed: without a community, an install, a source *and* the dashboard the
  // widget is configured for, there is nothing to ask for. A widget not on a
  // dashboard yet has none, which is how it issues no request at all.
  const ready =
    enabled &&
    Number.isFinite(communityId) &&
    communityId > 0 &&
    typeof pluginId === "number" &&
    typeof dashboardId === "number" &&
    typeof endpointId === "string" &&
    endpointId.length > 0;

  const staleSeconds = Math.max(0, Math.min(cacheTtlSeconds ?? 0, MAX_PLUGIN_STALE_SECONDS));

  return useQuery<PluginDataResponse>({
    queryKey: pluginDataKey(communityId, pluginId ?? 0, endpointId ?? "", dashboardId ?? 0, params),
    queryFn: () =>
      getPluginData({
        communityId,
        pluginId: pluginId as number,
        endpointId: endpointId as string,
        dashboardId: dashboardId as number,
        params,
      }),
    enabled: ready,
    staleTime: staleSeconds * 1000,
    // A plug-in that is down is not asked again straight away, and the preview
    // has something useful to draw meanwhile: React Query keeps serving the last
    // good rows for the stale window while the error is shown.
    retry: false,
  });
};

/** One parameter's menu, keyed by the answers it was resolved against — a
 *  sibling changing is a different question, so it is a different entry. */
export const pluginParamOptionsKey = (
  communityId: number,
  pluginId: number,
  endpointId: string,
  param: string,
  params: Record<string, unknown> | undefined
) =>
  [
    "plugin-param-options",
    communityId,
    pluginId,
    endpointId,
    param,
    JSON.stringify(Object.entries(params ?? {}).sort(([a], [b]) => (a < b ? -1 : 1))),
  ] as const;

export interface PluginParamOptionsQuery {
  pluginId: number | undefined;
  endpointId: string | undefined;
  param: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
}

/**
 * The values one of a plug-in endpoint's parameters permits.
 *
 * Fetched while a form is open rather than with the canvas, because it is only
 * a form that needs it — and only for the parameters that declared a source.
 * The answer is cached briefly: a menu is re-read when somebody reopens the
 * dialog, which is roughly how often the set behind it changes.
 *
 * It never throws a form into an unusable state. A source that will not
 * resolve comes back as `unavailable` with no options, and the caller draws a
 * text field — the same ending as an outright network failure here, which is
 * why `retry` is off and an error is treated as "no menu" rather than surfaced.
 */
export const usePluginParamOptions = ({
  pluginId,
  endpointId,
  param,
  params,
  enabled = true,
}: PluginParamOptionsQuery) => {
  const communityId = useActiveCommunityId();
  const ready =
    enabled &&
    Number.isFinite(communityId) &&
    communityId > 0 &&
    typeof pluginId === "number" &&
    typeof endpointId === "string" &&
    endpointId.length > 0;

  return useQuery<PluginParamOptionsResponse>({
    queryKey: pluginParamOptionsKey(communityId, pluginId ?? 0, endpointId ?? "", param, params),
    queryFn: () =>
      getPluginParamOptions({
        communityId,
        pluginId: pluginId as number,
        endpointId: endpointId as string,
        param,
        params,
      }),
    enabled: ready,
    staleTime: 60_000,
    retry: false,
  });
};

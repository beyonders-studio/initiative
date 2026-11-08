/**
 * A plug-in's widget on a dashboard: where its module comes from, and what happens
 * when the plug-in behind it does not answer.
 *
 * Three things are pinned here.
 *
 * **A preview issues zero requests.** A marketplace listing that is not
 * installed must render from what the manifest shipped — its own module over its
 * own sample rows — and reach nothing at all. The assertion is on the transport:
 * not "it used samples", but "no request was made".
 *
 * **The module comes from the pinned definition.** A plug-in widget's code is not in
 * this build's registry; it arrives with the install and is handed to the same
 * sandbox a built-in runs in. `WidgetTile.source` is that seam, and this checks
 * it is actually threaded rather than falling back to the registry (which would
 * silently render "this widget needs a newer version").
 *
 * **A placed widget reads its canvas.** The canvas read answers every widget on
 * the dashboard, a plug-in widget with its endpoint's rows read with the
 * parameters it stores; the plug-in's own data route is only the config
 * dialog's preview.
 *
 * **An unreachable plug-in costs one tile.** Not a crash, not a blank, not a
 * misleading "no data" — a localized error tile, with the rest of the canvas
 * untouched.
 */
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { DefinitionWidget } from "@/lib/widgets/definition";
import { WidgetErrorCode } from "@/lib/widgets/errors";

// The generated client calls the client itself, with the URL in its config, and
// the hand-written one calls `get`. Both land in `apiGet`, by URL.
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({
  apiClient: Object.assign((config: { url: string }) => apiGet(config.url, config), {
    get: apiGet,
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  }),
  API_BASE_URL: "http://test/api/v1",
}));

const renderWidget = vi.hoisted(() => vi.fn());
const readWidgetMeta = vi.hoisted(() => vi.fn());
vi.mock("@/lib/widgets/runtime/host", () => ({ renderWidget, readWidgetMeta }));

import { DashboardWidget } from "./DashboardWidget";

const PLUGIN_UID = "SHOPAPP0000001";
const WIDGET_TYPE = `plugin:${PLUGIN_UID}:summary`;
const MODULE = "export const render = () => ({ scene: { kind: 'empty' } });";

const binding: WidgetBinding = {
  source: "plugin",
  plugin_uid: PLUGIN_UID,
  endpoint_id: "plugin.acme.shop.orders-summary",
};
const widget: DefinitionWidget = {
  id: "w1",
  type: WIDGET_TYPE,
  grid: { x: 0, y: 0, w: 6, h: 4 },
  binding,
};

const CATALOG = {
  items: [
    {
      plugin_id: 3,
      plugin_uid: PLUGIN_UID,
      name: "Shop",
      enabled: true,
      widgets: [
        {
          type: WIDGET_TYPE,
          id: "summary",
          meta: { name: { en: "Summary" } },
          module_source: MODULE,
          endpoints: ["plugin.acme.shop.orders-summary"],
          sample_data: {
            "plugin.acme.shop.orders-summary": {
              rows: [{ days: "mon", totals: 4 }],
              values: { total: 4 },
            },
          },
        },
      ],
      endpoints: [
        {
          id: "plugin.acme.shop.orders-summary",
          cache_ttl_seconds: 60,
          params: [],
        },
      ],
    },
  ],
};

const catalogUrl = (url: string) => url.endsWith("/plugins/widget-catalog");
const canvasUrl = (url: string) => url.endsWith("/dashboards/11/data");
const dataUrl = (url: string) => url.includes("/endpoints/");

/** The plug-in catalog, and the canvas with this widget's entry in it. Nothing
 *  else is answered. */
const serve = (entry: Record<string, unknown>) =>
  apiGet.mockImplementation((url: string) => {
    if (catalogUrl(url)) return Promise.resolve({ data: CATALOG });
    if (canvasUrl(url)) {
      return Promise.resolve({ data: { initiative_id: 7, widgets: { w1: entry } } });
    }
    return Promise.reject(new Error(`not served: ${url}`));
  });

beforeEach(() => {
  apiGet.mockReset();
  renderWidget.mockReset();
  readWidgetMeta.mockReset();
  renderWidget.mockResolvedValue({ ok: true, spec: { scene: { kind: "empty" } } });
  readWidgetMeta.mockResolvedValue({ name: { en: "Summary" } });
});

const mount = (props: { sampleData?: boolean; dashboardId?: number } = {}) =>
  renderWithProviders(
    <DashboardWidget
      widget={widget}
      binding={binding}
      initiativeId={props.sampleData ? undefined : 7}
      dashboardId={props.dashboardId}
      canEdit={false}
      sampleData={props.sampleData}
    />,
    { communities: { activeCommunityId: 2 } }
  );

describe("DashboardWidget with a plug-in source", () => {
  it("runs the module the install pinned, over the rows its canvas answered", async () => {
    serve({
      plugin: {
        rows: [{ days: "mon", totals: 9 }],
        values: { total: 9 },
        fetched_at: "",
        cached: false,
      },
    });

    mount({ dashboardId: 11 });

    await waitFor(() => expect(renderWidget).toHaveBeenCalled());
    const call = renderWidget.mock.calls.at(-1)?.[0];
    // The seam: the module comes from the pinned definition, not the registry.
    expect(call.source).toBe(MODULE);
    // Both halves verbatim, plus the host's own count of the rows — nothing on
    // this side reads inside either.
    expect(call.data).toEqual({
      source: "plugin",
      rows: [{ days: "mon", totals: 9 }],
      values: { total: 9 },
      meta: { total: 1 },
    });
  });

  it("reads the canvas it sits on, not the plug-in's own route", async () => {
    serve({ plugin: { rows: [], values: {}, fetched_at: "", cached: false } });

    mount({ dashboardId: 11 });

    await waitFor(() => expect(apiGet.mock.calls.some(([url]) => canvasUrl(url))).toBe(true));
    expect(apiGet.mock.calls.find(([url]) => canvasUrl(url))?.[0]).toBe(
      "/api/v1/c/2/dashboards/11/data"
    );
    expect(apiGet.mock.calls.some(([url]) => dataUrl(url))).toBe(false);
  });

  it("draws an error tile when the plug-in is not answering", async () => {
    serve({ error: "PLUGIN_SERVICE_UNAVAILABLE" });

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/not responding/i)).toBeInTheDocument();
    // The module is never run: it has nothing to draw, and running it over an
    // empty array would claim "no data" rather than "the plug-in is down".
    expect(renderWidget).not.toHaveBeenCalled();
  });

  it("previews from the manifest's own samples and issues zero requests", async () => {
    apiGet.mockImplementation((url: string) =>
      catalogUrl(url)
        ? Promise.resolve({ data: CATALOG })
        : Promise.reject(new Error("a preview must not fetch data"))
    );

    mount({ sampleData: true });

    await waitFor(() => expect(renderWidget).toHaveBeenCalled());
    const call = renderWidget.mock.calls.at(-1)?.[0];
    expect(call.source).toBe(MODULE);
    expect(call.data).toEqual({
      source: "plugin",
      rows: [{ days: "mon", totals: 4 }],
      values: { total: 4 },
    });
    // The catalogs are declarations; the data plane is never touched.
    expect(apiGet.mock.calls.every(([url]) => url.endsWith("/widget-catalog"))).toBe(true);
  });

  it("has a localized message for the failure it can produce", () => {
    expect(WidgetErrorCode.PLUGIN_UNAVAILABLE).toBe("WIDGET_PLUGIN_UNAVAILABLE");
  });

  it("asks for the plug-in to be reconnected when the catalog no longer lists it", async () => {
    // The definition is kept as-is when its plug-in goes away; the tile is the
    // surface that says so. Distinct from both the restricted state (this is
    // not an access outcome) and the unavailable state (the catalog answered).
    apiGet.mockImplementation((url: string) => {
      if (catalogUrl(url)) return Promise.resolve({ data: { items: [] } });
      return Promise.reject(new Error("nothing should be fetched for it"));
    });

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/no longer installed/i)).toBeInTheDocument();
    expect(renderWidget).not.toHaveBeenCalled();
    // The plug-in itself was never asked.
    expect(apiGet.mock.calls.some(([url]) => dataUrl(url))).toBe(false);
  });

  it("says the plug-in is unavailable when its catalog will not load", async () => {
    // A catalog that failed says nothing about whether the plug-in is installed.
    // Reading it as "not installed" would mark every plug-in widget on the board
    // unconfigured and invite someone to repoint bindings that were never wrong.
    apiGet.mockImplementation(() => Promise.reject(new Error("503")));

    mount({ dashboardId: 11 });

    expect(await screen.findByText(/not responding/i)).toBeInTheDocument();
    expect(screen.queryByText(/not configured/i)).toBeNull();
  });
});

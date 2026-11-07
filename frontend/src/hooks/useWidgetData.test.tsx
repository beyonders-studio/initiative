/**
 * How a binding becomes a request.
 *
 * The load-bearing case is scope. A dashboard reads the initiative it lives on,
 * and without one nothing is fetched at all — a widget on no initiative must
 * fail closed rather than fan out community-wide. That difference is invisible on a
 * canvas (a chart with plausible-looking numbers), so it is pinned here on the
 * request itself rather than on what gets drawn.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPluginCatalogEntry } from "@/__tests__/factories";
import { useWidgetData, type WidgetBinding } from "@/hooks/useWidgetData";
import { WidgetErrorCode } from "@/lib/widgets/errors";

/** The slice of a query result the hook under test reads. `plugin` is a canvas
 *  entry's answer for a plug-in widget. */
type QueryState = { data: unknown; plugin?: unknown; isLoading: boolean; isError: boolean };
type QueryHook = (...args: unknown[]) => QueryState;

const idle: QueryState = { data: undefined, isLoading: false, isError: false };
const useSqlQuery = vi.fn<QueryHook>(() => idle);
const useWidgetQuery = vi.fn<QueryHook>(() => idle);
const usePluginData = vi.fn<QueryHook>(() => idle);
const usePluginWidgetCatalog = vi.fn<QueryHook>(() => idle);

vi.mock("@/hooks/useSqlQuery", () => ({
  useSqlQuery: (...args: unknown[]) => useSqlQuery(...args),
  useWidgetQuery: (...args: unknown[]) => useWidgetQuery(...args),
}));
// Mocked like every other sibling: this file is about how a binding becomes a
// request, and the app hooks reach for community context a bare renderHook has no
// provider for.
vi.mock("@/hooks/usePluginData", () => ({
  usePluginData: (...args: unknown[]) => usePluginData(...args),
  usePluginWidgetCatalog: (...args: unknown[]) => usePluginWidgetCatalog(...args),
}));

/** The statement the query hook was actually asked for. */
const asked = (): unknown => useSqlQuery.mock.calls.at(-1)?.[0];
/** The initiative it was asked to narrow the answer to. */
const scopedTo = (): unknown => useSqlQuery.mock.calls.at(-1)?.[1];
const enabled = (): boolean =>
  Boolean((useSqlQuery.mock.calls.at(-1)?.[2] as { enabled?: boolean } | undefined)?.enabled);

const run = (binding: WidgetBinding, initiativeId: number | undefined) =>
  renderHook(() => useWidgetData(binding, initiativeId));

beforeEach(() => {
  useSqlQuery.mockClear();
  useWidgetQuery.mockReset();
  useWidgetQuery.mockReturnValue(idle);
  usePluginData.mockReset();
  usePluginData.mockReturnValue(idle);
  usePluginWidgetCatalog.mockReset();
  usePluginWidgetCatalog.mockReturnValue(idle);
});

describe("a query binding", () => {
  it("asks for the statement it was given", () => {
    run({ source: "query", sql: "SELECT title FROM tasks" }, 4);
    expect(asked()).toBe("SELECT title FROM tasks");
    expect(enabled()).toBe(true);
  });

  it("asks about the dashboard's own initiative", () => {
    // A statement names datasets, not a scope, so the dashboard's own
    // initiative is what decides which rows the answer is about.
    run({ source: "query", sql: "SELECT title FROM tasks" }, 4);
    expect(scopedTo()).toBe(4);
  });

  it("asks for nothing without an initiative", () => {
    // Fail closed: a widget with no initiative behind it is unbound, not
    // community-wide.
    run({ source: "query", sql: "SELECT title FROM tasks" }, undefined);
    expect(enabled()).toBe(false);
  });

  it("asks for nothing when the binding has no statement yet", () => {
    const { result } = run({ source: "query" }, 4);
    expect(asked()).toBeNull();
    expect(result.current.isUnbound).toBe(true);
  });

  it("reads a refused statement as the author's problem, not the viewer's", () => {
    // A name the registry does not have is the author's to fix; it is not an
    // access outcome, so it must not render as one.
    useSqlQuery.mockReturnValue({ ...idle, isError: true });
    const { result } = run({ source: "query", sql: "SELECT nope FROM tasks" }, 4);
    expect(result.current.isRestricted).toBe(false);
    expect(result.current.errorCode).toBeDefined();
    useSqlQuery.mockReturnValue(idle);
  });

  it("reports what came back as columns and rows", () => {
    useSqlQuery.mockReturnValue({
      ...idle,
      data: {
        columns: [
          { name: "title", type: "text" },
          { name: "n", type: "number" },
        ],
        rows: [["Ship it", 3]],
        truncated: true,
      },
    });
    const { result } = run({ source: "query", sql: "SELECT title, count(*) FROM tasks" }, 4);
    expect(result.current.data).toMatchObject({
      source: "rows",
      columns: [
        { name: "title", type: "text" },
        { name: "n", type: "number" },
      ],
      rows: [["Ship it", 3]],
    });
    expect(result.current.meta?.truncated).toBe(true);
    useSqlQuery.mockReturnValue(idle);
  });
});

describe("a widget already on a dashboard", () => {
  /** A placed widget names itself and lets the server look the statement up.
   *  Nothing about the request says what to run, which is what lets a
   *  dashboard show rows the reader could not otherwise reach. */
  const placed = () =>
    renderHook(() =>
      useWidgetData({ source: "query", sql: "SELECT 1 AS n FROM tasks" }, 7, 11, "w1")
    );

  it("is read by naming it, not by sending its statement", () => {
    placed();
    expect(useWidgetQuery).toHaveBeenCalled();
    expect(useWidgetQuery.mock.calls.at(-1)?.slice(0, 2)).toEqual([11, "w1"]);
    // The statement hook is not the one asking.
    expect(
      Boolean((useSqlQuery.mock.calls.at(-1)?.[2] as { enabled?: boolean } | undefined)?.enabled)
    ).toBe(false);
  });

  it("asks for nothing where nobody has pointed it anywhere", () => {
    // A placed widget with no statement has none for the server to look up,
    // and the tile already draws this as unconfigured rather than as a
    // failure. Asking would be a request that can only come back empty
    // handed — and one that reads as a broken tile if anything downstream
    // treats a refusal as an error.
    renderHook(() => useWidgetData({ source: "query" }, 7, 11, "w1"));
    const asked = useWidgetQuery.mock.calls.at(-1);
    expect(asked?.slice(0, 2)).toEqual([null, null]);
    expect(Boolean((asked?.[2] as { enabled?: boolean } | undefined)?.enabled)).toBe(false);
  });

  it("stays placed when its dashboard goes momentarily unknown", () => {
    // The retained answer lives on the widget read. Falling back to sending
    // the statement for those renders would read a hook holding nothing, and
    // the tile would blink empty through the other path.
    const binding = { source: "query" as const, sql: "SELECT 1 AS n FROM tasks" };
    const { rerender } = renderHook(
      ({ id }: { id?: number }) => useWidgetData(binding, 7, id, "w1"),
      { initialProps: { id: 11 as number | undefined } }
    );
    rerender({ id: undefined });

    // Still the widget read that is asking, disabled rather than replaced.
    expect(
      Boolean((useSqlQuery.mock.calls.at(-1)?.[2] as { enabled?: boolean } | undefined)?.enabled)
    ).toBe(false);
  });

  it("sends the statement while it is still being written", () => {
    // No dashboard and no widget: the config dialog's preview, which has
    // nothing stored yet for the server to look up.
    renderHook(() => useWidgetData({ source: "query", sql: "SELECT 1 AS n FROM tasks" }, 7));
    expect(
      Boolean((useSqlQuery.mock.calls.at(-1)?.[2] as { enabled?: boolean } | undefined)?.enabled)
    ).toBe(true);
  });
});

describe("a plug-in widget", () => {
  const entry = buildPluginCatalogEntry();
  const binding: WidgetBinding = {
    source: "plugin",
    plugin_uid: entry.plugin_uid,
    endpoint_id: "plugin.acme.shop.orders",
    params: { range: "30d" },
  };
  const answer = {
    rows: [{ status: "open", total: 3 }],
    values: { count: 1 },
    fetched_at: "2026-11-07T00:00:00Z",
  };
  const installed = () =>
    usePluginWidgetCatalog.mockReturnValue({ ...idle, data: { items: [entry] } });
  const previewEnabled = (): boolean =>
    Boolean((usePluginData.mock.calls.at(-1)?.[0] as { enabled?: boolean } | undefined)?.enabled);

  it("reads its canvas entry once it is placed", () => {
    // The server reads the endpoint with the parameters the widget stores, so
    // nothing about the request says what to read.
    installed();
    useWidgetQuery.mockReturnValue({ ...idle, plugin: answer });
    const { result } = renderHook(() => useWidgetData(binding, 7, 11, "w1"));

    expect(useWidgetQuery.mock.calls.at(-1)?.slice(0, 2)).toEqual([11, "w1"]);
    expect(previewEnabled()).toBe(false);
    expect(result.current.data).toEqual({
      source: "plugin",
      rows: answer.rows,
      values: answer.values,
      meta: { total: 1 },
    });
  });

  it("reads its endpoint itself while it is being configured", () => {
    // No widget id: the config dialog's preview, with the form's parameters.
    installed();
    renderHook(() => useWidgetData(binding, 7, 11));

    expect(useWidgetQuery.mock.calls.at(-1)?.slice(0, 2)).toEqual([null, null]);
    expect(previewEnabled()).toBe(true);
    expect(usePluginData.mock.calls.at(-1)?.[0]).toMatchObject({
      pluginId: entry.plugin_id,
      endpointId: "plugin.acme.shop.orders",
      dashboardId: 11,
      params: { range: "30d" },
    });
  });

  it("draws the error tile when its canvas entry is refused, as a statement's tile does", () => {
    // Saved with different parameters and refused: the rows it had answered a
    // different question.
    installed();
    useWidgetQuery.mockReturnValue({ ...idle, plugin: answer });
    const { result, rerender } = renderHook(
      ({ params }: { params: Record<string, unknown> }) =>
        useWidgetData({ ...binding, params }, 7, 11, "w1"),
      { initialProps: { params: { range: "30d" } } }
    );

    useWidgetQuery.mockReturnValue({ ...idle, isError: true });
    rerender({ params: { range: "7d" } });
    expect(result.current.errorCode).toBe(WidgetErrorCode.PLUGIN_UNAVAILABLE);
  });

  it("asks for the plug-in to be reconnected when the catalog no longer lists it", () => {
    usePluginWidgetCatalog.mockReturnValue({ ...idle, data: { items: [] } });
    useWidgetQuery.mockReturnValue({ ...idle, isError: true });
    const { result } = renderHook(() => useWidgetData(binding, 7, 11, "w1"));
    expect(result.current.errorCode).toBe(WidgetErrorCode.PLUGIN_NOT_INSTALLED);
  });
});

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildPropertyOption, buildPropertySummary, buildTask } from "@/__tests__/factories";
import i18n from "@/__tests__/helpers/i18n-test";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { MetadataType, type TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { numberFormat } from "@/lib/intl";
import {
  fieldsInParts,
  pluginFieldId,
  pluginFields,
  pluginsOnItems,
  shippedPluginParts,
} from "@/lib/layouts/plugins";
import { TASK_LAYOUT, taskFields } from "@/lib/layouts/tasks";
import { type LayoutNode, LayoutTree } from "@/lib/layouts/tree";
import type { TranslateFn } from "@/types/i18n";

const definition = {
  endpoints: [
    {
      id: "plugin.acme.ci.rerun",
      direction: "write",
      params: [{ key: "reason", type: "string", label: { en: "Reason" }, required: true }],
    },
  ],
  fields: [
    { key: "ci.state", name: { en: "CI" }, kind: "badge", on: ["task"], tone: "positive" },
    { key: "ci.url", name: { en: "Build" }, kind: "link", on: ["task"] },
    {
      key: "ci.runs",
      name: { en: "Runs" },
      kind: "link",
      list: true,
      on: ["task"],
      actions: ["cancel-run"],
      states: {
        status: {
          name: { en: "Status" },
          values: { queued: { label: { en: "Queued" }, tone: "warning" } },
        },
      },
    },
    { key: "event.only", name: { en: "Elsewhere" }, kind: "text", on: ["calendar_event"] },
  ],
  parts: [
    {
      id: "builds",
      name: { en: "Builds" },
      on: ["task"],
      tree: {
        type: "section",
        props: { title: { en: "Builds" } },
        children: [
          { type: "text", props: { text: { en: "Name a branch {settings.prefix}-{item.id}." } } },
          { type: "field", props: { field: "ci.url" } },
          { type: "field", props: { field: "ci.runs" } },
          { type: "button", props: { action: "rerun" } },
          { type: "button", props: { action: "purge" } },
        ],
      },
    },
  ],
  actions: [
    {
      id: "rerun",
      name: { en: "Run again" },
      on: ["task"],
      confirm: { en: "Run the build again?" },
      endpoint: "plugin.acme.ci.rerun",
      params: ["reason"],
    },
    { id: "cancel-run", name: { en: "Cancel run" }, on: ["task"] },
    { id: "purge", name: { en: "Purge" }, on: ["task"] },
  ],
};

const install = {
  id: 3,
  name: "CI",
  enabled: true,
  definition,
  item_initiatives: [7],
  item_fields: ["ci.state", "ci.url", "ci.runs", "event.only"],
  item_parts: ["builds"],
  item_actions: ["rerun", "cancel-run"],
  setting_values: { prefix: "acme" },
};

const task = buildTask({
  id: 41,
  properties: [
    buildPropertySummary({ install_id: 3, key: "ci.state", value: { text: "passing" } }),
    buildPropertySummary({
      install_id: 3,
      key: "ci.url",
      value: { url: "https://ci.example/41", text: "#41" },
    }),
    buildPropertySummary({
      install_id: 3,
      key: "ci.runs",
      value: [
        { ref: "r1", url: "https://ci.example/r/1", text: "run 1", state: { status: "queued" } },
        { ref: "r2", url: "javascript:alert(1)", text: "run 2" },
      ],
    }),
  ],
});

const draw = (
  card: LayoutNode,
  item: TaskListRead = task,
  installs: Parameters<typeof pluginsOnItems>[0] = [install]
) => {
  const plugins = pluginsOnItems(installs, 7);
  const view = {
    fields: taskFields([], pluginFields(plugins, "en")),
    plugins,
    variant: "card" as const,
    env: {
      t: i18n.getFixedT(null, ["projects", "dates", "relations"]) as TranslateFn,
      communityPath: (path: string) => path,
      taskHref: ({ id }: TaskListRead) => `/tasks/${id}`,
    },
  };
  return renderWithProviders(<LayoutTree node={card} item={item} view={view} />);
};

describe("pluginsOnItems", () => {
  it("keeps what an install declares on tasks, of what the server offers the reader", () => {
    const plugins = pluginsOnItems(
      [
        install,
        { ...install, id: 4, enabled: false },
        { ...install, id: 5, item_initiatives: [8] },
        // Its connection holds nothing, so the server offers less of it.
        { ...install, id: 6, item_fields: ["ci.url"], item_parts: [], item_actions: [] },
      ],
      7
    );

    expect([...plugins.keys()]).toEqual([3, 6]);
    const [plugin, unmet] = [plugins.get(3), plugins.get(6)];
    expect([...(plugin?.fields.keys() ?? [])]).toEqual(["ci.state", "ci.url", "ci.runs"]);
    expect([...(plugin?.parts.keys() ?? [])]).toEqual(["builds"]);
    expect([...(plugin?.actions.keys() ?? [])]).toEqual(["rerun", "cancel-run"]);
    expect(plugin?.endpoints.get("plugin.acme.ci.rerun")?.map((param) => param.key)).toEqual([
      "reason",
    ]);
    expect(plugin?.settings).toEqual({ prefix: "acme" });
    expect([...(unmet?.fields.keys() ?? [])]).toEqual(["ci.url"]);
    expect(unmet?.parts.size).toBe(0);
    expect(unmet?.actions.size).toBe(0);
  });
});

describe("a plug-in on a task's page", () => {
  it("shows its fields, then its parts, at the end of a side not saved", () => {
    const more = shippedPluginParts(pluginsOnItems([install], 7));
    const side = (stored: Parameters<typeof TASK_LAYOUT.root>[0]) =>
      TASK_LAYOUT.root(stored, more).children?.[2]?.children;

    expect(more).toEqual([
      { type: "field", props: { field: pluginFieldId(3, "ci.state") } },
      { type: "field", props: { field: pluginFieldId(3, "ci.url") } },
      { type: "field", props: { field: pluginFieldId(3, "ci.runs") } },
      { type: "plugin", props: { plugin: 3, part: "builds" } },
    ]);
    expect(side(null)?.slice(-more.length)).toEqual(more);
    // A saved side holds what it holds.
    expect(side({ header: [], main: [], side: [] })).toEqual([]);
  });

  it("draws a field once where a part it draws shows it, at any depth", () => {
    const plugins = pluginsOnItems([install], 7);
    const page = (...side: LayoutNode[]): LayoutNode => ({
      type: "layout",
      children: [{ type: "side", children: side }],
    });
    const builds = { type: "plugin", props: { plugin: 3, part: "builds" } };

    // The builds part shows ci.url and ci.runs inside its section.
    expect(fieldsInParts(page({ type: "section", children: [builds] }), plugins)).toEqual(
      new Set([pluginFieldId(3, "ci.url"), pluginFieldId(3, "ci.runs")])
    );
    // Taken off, or not offered to the reader, a part hides nothing.
    expect(fieldsInParts(page(), plugins)).toEqual(new Set());
    expect(
      fieldsInParts(page(builds), pluginsOnItems([{ ...install, item_parts: [] }], 7))
    ).toEqual(new Set());
  });
});

describe("a plug-in on a card", () => {
  it("draws the fields and parts the card places, and nothing it does not", async () => {
    draw({
      type: "card",
      children: [
        { type: "field", props: { field: pluginFieldId(3, "ci.state") } },
        { type: "plugin", props: { plugin: 3, part: "builds" } },
        { type: "plugin", props: { plugin: 9, part: "builds" } },
      ],
    });

    expect(screen.getByText("passing")).toBeInTheDocument();
    expect(screen.getByText("Builds")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /#41/ })).toHaveAttribute(
      "href",
      "https://ci.example/41"
    );
    expect(screen.getByRole("button", { name: "Run again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Purge" })).toBeNull();
  });

  it("draws a property type's value as a property's, with the options and currency it carries", () => {
    const kinds = {
      ...install,
      id: 8,
      definition: {
        fields: [
          {
            key: "deal.price",
            name: { en: "Price" },
            kind: "currency",
            currency: "EUR",
            on: ["task"],
          },
          { key: "deal.site", name: { en: "Site" }, kind: "url", on: ["task"] },
          { key: "deal.stage", name: { en: "Stage" }, kind: "select", on: ["task"] },
          { key: "deal.areas", name: { en: "Areas" }, kind: "multi_select", on: ["task"] },
          { key: "deal.owner", name: { en: "Owner" }, kind: "user_reference", on: ["task"] },
          { key: "deal.picks", name: { en: "Picks" }, kind: "select", list: true, on: ["task"] },
        ],
      },
      item_fields: [
        "deal.price",
        "deal.site",
        "deal.stage",
        "deal.areas",
        "deal.owner",
        "deal.picks",
      ],
      item_parts: [],
      item_actions: [],
    };
    const stages = [
      buildPropertyOption({ value: "won", label: "Gewonnen" }),
      buildPropertyOption({ value: "lost", label: "Verloren" }),
    ];
    const kept = (key: string, type: MetadataType, value: unknown, extra = {}) =>
      buildPropertySummary({ install_id: 8, key, type, value, ...extra });
    draw(
      {
        type: "card",
        children: kinds.item_fields.map((key) => ({
          type: "field",
          props: { field: pluginFieldId(8, key) },
        })),
      },
      buildTask({
        properties: [
          kept("deal.price", MetadataType.currency, 1250, { currency: "EUR" }),
          kept("deal.site", MetadataType.url, "https://shop.example/12"),
          kept("deal.stage", MetadataType.select, { value: "won", state: {} }, { options: stages }),
          kept("deal.areas", MetadataType.multi_select, ["won", "lost"], { options: stages }),
          kept("deal.owner", MetadataType.user_reference, {
            id: 4,
            display_name: "Ada Lovelace",
          }),
          kept(
            "deal.picks",
            MetadataType.select,
            [
              { ref: "a", value: "lost" },
              { ref: "b", value: "won" },
            ],
            { options: stages }
          ),
        ],
      }),
      [kinds]
    );

    expect(
      screen.getByText(numberFormat(undefined, { style: "currency", currency: "EUR" }).format(1250))
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /shop\.example\/12/ })).toHaveAttribute(
      "href",
      "https://shop.example/12"
    );
    // The stage, both areas, and each of the two picks, labelled as the
    // reader reads them.
    expect(screen.getAllByText("Gewonnen")).toHaveLength(3);
    expect(screen.getAllByText("Verloren")).toHaveLength(2);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("draws a scale as a bar of its figure, kept with or without a state", () => {
    const coverage = {
      ...install,
      id: 8,
      definition: {
        fields: [{ key: "ci.coverage", name: { en: "Coverage" }, kind: "scale", on: ["task"] }],
      },
      item_fields: ["ci.coverage"],
      item_parts: [],
      item_actions: [],
    };
    const card: LayoutNode = {
      type: "card",
      children: [{ type: "field", props: { field: pluginFieldId(8, "ci.coverage") } }],
    };
    const percent = (figure: number) =>
      numberFormat("en", { style: "percent" }).format(figure / 100);
    const { unmount } = draw(
      card,
      buildTask({
        properties: [buildPropertySummary({ install_id: 8, key: "ci.coverage", value: 80 })],
      }),
      [coverage]
    );

    expect(screen.getByRole("img", { name: percent(80) }).firstElementChild).toHaveStyle({
      width: "80%",
    });
    unmount();
    draw(
      card,
      buildTask({
        properties: [
          buildPropertySummary({
            install_id: 8,
            key: "ci.coverage",
            value: { value: 35, state: { run: "late" } },
          }),
        ],
      }),
      [coverage]
    );
    expect(screen.getByRole("img", { name: percent(35) })).toBeInTheDocument();
  });

  it("draws nothing for a value of the wrong shape or a link that is not the web", () => {
    draw(
      {
        type: "card",
        children: [
          { type: "field", props: { field: pluginFieldId(3, "ci.state") } },
          { type: "field", props: { field: pluginFieldId(3, "ci.url") } },
        ],
      },
      buildTask({
        properties: [
          buildPropertySummary({ install_id: 3, key: "ci.state", value: "passing" }),
          buildPropertySummary({
            install_id: 3,
            key: "ci.url",
            value: { url: "javascript:alert(1)" },
          }),
        ],
      })
    );

    expect(screen.queryByText("CI")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("asks what the action needs, then runs it on the task with the answer", async () => {
    let ran: unknown = null;
    server.use(
      http.post("/api/v1/c/1/plugins/3/actions/rerun", async ({ request }) => {
        ran = await request.json();
        return HttpResponse.json({ values: {} });
      })
    );
    draw({ type: "card", children: [{ type: "plugin", props: { plugin: 3, part: "builds" } }] });

    await userEvent.click(screen.getByRole("button", { name: "Run again" }));
    expect(await screen.findByText("Run the build again?")).toBeInTheDocument();
    const run = screen.getAllByRole("button", { name: "Run again" }).at(-1) as HTMLElement;
    // The reason is required, so nothing runs until it is given.
    expect(run).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Reason/), "flaky");
    expect(ran).toBeNull();
    await userEvent.click(run);

    await waitFor(() =>
      expect(ran).toEqual({ entity_type: "task", entity_id: 41, params: { reason: "flaky" } })
    );
  });

  it("draws a list's elements with their states, and runs an action from one", async () => {
    let ran: unknown = null;
    server.use(
      http.post("/api/v1/c/1/plugins/3/actions/cancel-run", async ({ request }) => {
        ran = await request.json();
        return HttpResponse.json({ values: {} });
      })
    );
    draw({ type: "card", children: [{ type: "plugin", props: { plugin: 3, part: "builds" } }] });

    expect(screen.getByRole("link", { name: /run 1/ })).toHaveAttribute(
      "href",
      "https://ci.example/r/1"
    );
    expect(screen.getByText("Queued")).toBeInTheDocument();
    // An element its kind does not draw is left out, with its actions.
    expect(screen.queryByText("run 2")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Cancel run" }));

    await waitFor(() => expect(ran).toEqual({ entity_type: "task", entity_id: 41, element: "r1" }));
  });

  it("fills a part's text with the item and the install's settings", () => {
    draw({ type: "card", children: [{ type: "plugin", props: { plugin: 3, part: "builds" } }] });

    expect(screen.getByText("Name a branch acme-41.")).toBeInTheDocument();
  });
});

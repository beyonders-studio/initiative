/**
 * What a new statement leaves out, and when it is decided again.
 *
 * Driven through the component's own props rather than its dataset picker: the
 * thing under test is when the conditions are seeded, and the picker does
 * nothing but hand back a spec with the new dataset and its filters cleared —
 * which is exactly what re-rendering with that spec does.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPluginCatalogEntry } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  QueryBuildRequest,
  QueryPluginDescription,
  QuerySheetDescription,
} from "@/api/generated/initiativeAPI.schemas";
import { type QueryablePlugin, queryablePlugins } from "@/api/pluginData";

import { QueryBuilder } from "./QueryBuilder";

const COUNT_ALL = { field: "*", aggregate: "count", alias: "count" };
const NONE: { id: number; name: string }[] = [];
const NO_PLUGINS: QueryablePlugin[] = [];

const DEFAULTS: Record<string, { field: string; op: string; value: unknown }[]> = {
  tasks: [
    { field: "archived_at", op: "is_null", value: true },
    { field: "project.is_template", op: "eq", value: false },
  ],
  projects: [
    { field: "archived_at", op: "is_null", value: true },
    { field: "is_template", op: "eq", value: false },
  ],
  members: [],
};

beforeEach(() => {
  server.use(
    communityHttp.get("/fields/:dataset", ({ params }) => {
      const dataset = String(params.dataset);
      return HttpResponse.json({
        dataset,
        fields: [
          {
            name: "title",
            type: "text",
            kind: "text",
            ops: ["eq"],
            multiple: false,
            sortable: true,
            options: [],
          },
        ],
        relations: [],
        default_filters: DEFAULTS[dataset] ?? [],
      });
    })
  );
});

const spec = (dataset: string): QueryBuildRequest =>
  ({ dataset, columns: [COUNT_ALL], where: [], group_by: [] }) as QueryBuildRequest;

/** The builder, re-rendered with whatever it last asked for — which is what
 *  the dialog around it does. */
function mount() {
  const onChange = vi.fn();
  const view = renderWithProviders(
    <QueryBuilder
      spec={spec("tasks")}
      onChange={onChange}
      initiativeId={7}
      spreadsheets={NONE}
      plugins={NO_PLUGINS}
    />
  );
  const show = (next: QueryBuildRequest) =>
    view.rerender(
      <QueryBuilder
        spec={next}
        onChange={onChange}
        initiativeId={7}
        spreadsheets={NONE}
        plugins={NO_PLUGINS}
      />
    );
  const seeded = () =>
    (onChange.mock.calls.at(-1)?.[0] as QueryBuildRequest | undefined)?.where?.map(
      (condition) => (condition as { field: string }).field
    );
  return { onChange, show, seeded };
}

describe("seeding a new statement", () => {
  it("leaves out archived work and templates, again on a dataset the author comes back to", async () => {
    // The bug this pins: choosing a dataset clears the filters, so a trip
    // through another dataset and back left a statement reporting on work
    // that is not live.
    const { show, seeded, onChange } = mount();
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "project.is_template"]));

    show(spec("projects"));
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "is_template"]));

    onChange.mockClear();
    show(spec("tasks"));
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "project.is_template"]));
  });

  it("does not put back conditions the author deleted", async () => {
    // Removing them is how somebody asks about archived work, and the dataset
    // has not changed — so nothing seeds it again.
    const { show, onChange, seeded } = mount();
    await waitFor(() => expect(seeded()).toEqual(["archived_at", "project.is_template"]));

    onChange.mockClear();
    show(spec("tasks"));
    await new Promise((done) => setTimeout(done, 50));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("asks nothing of a dataset with neither lifecycle", async () => {
    const { show, onChange } = mount();
    onChange.mockClear();
    show(spec("members"));
    await new Promise((done) => setTimeout(done, 50));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("a tool plug-in's dataset", () => {
  it("is offered beside the built-in ones and read once chosen", async () => {
    // The vocabulary lists the community's tool set, so a dataset the
    // generated types never heard of is one a statement may name.
    server.use(
      communityHttp.get("/query/vocabulary", () =>
        HttpResponse.json({ datasets: ["hoard_items", "tasks"], functions: [], tokens: [] })
      )
    );
    const onChange = vi.fn();
    renderWithProviders(
      <QueryBuilder
        spec={spec("tasks")}
        onChange={onChange}
        initiativeId={7}
        spreadsheets={NONE}
        plugins={NO_PLUGINS}
      />
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: "Show data from" }));
    await user.click(await screen.findByRole("option", { name: "hoard_items" }));
    expect(onChange).toHaveBeenCalledWith(spec("hoard_items"));
  });
});

describe("grouping", () => {
  it("groups by every column shown as it is once one is a count", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <QueryBuilder
        spec={{
          ...spec("members"),
          columns: [COUNT_ALL, { field: "title" }, { field: "priority" }],
          group_by: ["title", "priority"],
        }}
        onChange={onChange}
        initiativeId={7}
        spreadsheets={NONE}
        plugins={NO_PLUGINS}
      />
    );
    expect(screen.getByText("One row for each Title and Priority")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getAllByRole("button", { name: /remove this column/i })[2]);
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ columns: [COUNT_ALL, { field: "title" }], group_by: ["title"] })
    );
  });

  it.each([
    // Built before the grouping was worked out: a plain column, grouped. The
    // statement it builds is grouped, so that is what the line says.
    [["title"], "One row for each Title"],
    // Without a count or a total, nothing is grouped.
    [[], "Every row, as it is"],
  ])("says what a saved widget grouped by %j is grouped by", (group_by, line) => {
    renderWithProviders(
      <QueryBuilder
        spec={{ ...spec("members"), columns: [{ field: "title" }], group_by }}
        onChange={vi.fn()}
        initiativeId={7}
        spreadsheets={NONE}
        plugins={NO_PLUGINS}
      />
    );
    expect(screen.getByText(line)).toBeInTheDocument();
  });
});

describe("a running total", () => {
  it("adds a count up along the column beside it", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <QueryBuilder
        spec={{ ...spec("members"), columns: [{ field: "title" }, COUNT_ALL], group_by: ["title"] }}
        onChange={onChange}
        initiativeId={7}
        spreadsheets={NONE}
        plugins={NO_PLUGINS}
      />
    );
    const user = userEvent.setup();
    await user.click(screen.getAllByRole("combobox", { name: /show as/i })[1]);
    await user.click(await screen.findByRole("option", { name: "Running count" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        columns: [{ field: "title" }, { ...COUNT_ALL, alias: null, running: true }],
        group_by: ["title"],
      })
    );
  });

  it("reads back as the running count it was built as", () => {
    renderWithProviders(
      <QueryBuilder
        spec={{
          ...spec("members"),
          columns: [{ field: "title" }, { ...COUNT_ALL, running: true }],
          group_by: ["title"],
        }}
        onChange={vi.fn()}
        initiativeId={7}
        spreadsheets={NONE}
        plugins={NO_PLUGINS}
      />
    );
    expect(screen.getAllByRole("combobox", { name: /show as/i })[1]).toHaveTextContent(
      "Running count"
    );
  });
});

describe("a spreadsheet's range", () => {
  const read: QuerySheetDescription = {
    alias: "sheet",
    sheets: ["Q3 Actuals", "Totals"],
    fields: [
      {
        name: "Region",
        type: "text",
        kind: "text",
        ops: ["ilike"],
        multiple: false,
        sortable: true,
      },
      {
        name: "No. sold",
        type: "number",
        kind: "number",
        ops: ["eq"],
        multiple: false,
        sortable: true,
      },
    ],
  };
  const reading = { sheet: { file: 5 }, columns: [COUNT_ALL], where: [], group_by: [] };

  it("starts with every column, named as its header is, and starts over on another sheet", async () => {
    const onChange = vi.fn();
    const view = renderWithProviders(
      <QueryBuilder
        spec={reading}
        onChange={onChange}
        initiativeId={7}
        spreadsheets={[{ id: 5, name: "Budget" }]}
        plugins={NO_PLUGINS}
        sheet={read}
      />
    );
    const seeded = { ...reading, columns: [{ field: "Region" }, { field: "No. sold" }] };
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(seeded));

    view.rerender(
      <QueryBuilder
        spec={seeded}
        onChange={onChange}
        initiativeId={7}
        spreadsheets={[{ id: 5, name: "Budget" }]}
        plugins={NO_PLUGINS}
        sheet={read}
      />
    );
    expect(screen.getAllByRole("combobox", { name: "Column" })[1]).toHaveTextContent("No. sold");

    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: "Sheet" }));
    await user.click(await screen.findByRole("option", { name: "Q3 Actuals" }));
    expect(onChange).toHaveBeenLastCalledWith({
      sheet: { file: 5, range: "'Q3 Actuals'" },
      columns: [COUNT_ALL],
      where: [],
      group_by: [],
    });
  });
});

describe("a plug-in's endpoint", () => {
  const read: QueryPluginDescription = {
    alias: "plugin",
    fields: [
      { name: "status", type: "text", kind: "text", ops: ["eq"], multiple: false, sortable: true },
      {
        name: "total",
        type: "number",
        kind: "number",
        ops: ["eq"],
        multiple: false,
        sortable: true,
      },
    ],
  };
  const shop = buildPluginCatalogEntry();
  const plugins = queryablePlugins({
    items: [
      {
        ...shop,
        endpoints: [
          ...(shop.endpoints ?? []),
          { id: "plugin.acme.shop.refunds", params: [], returns: [] },
          // Not under the plug-in's own prefix, so no call can name it.
          { id: "plugin.other.feed", params: [], returns: [] },
        ],
      },
      // No public id, so no call can name it either.
      buildPluginCatalogEntry({ public_id: null, name: "Unregistered" }),
    ],
  });
  const reading: QueryBuildRequest = {
    plugin: { plugin: "acme.shop", endpoint: "orders" },
    columns: [COUNT_ALL],
    where: [],
    group_by: [],
  };

  const show = (next: QueryBuildRequest, onChange = vi.fn()) => {
    const view = renderWithProviders(
      <QueryBuilder
        spec={next}
        onChange={onChange}
        initiativeId={7}
        spreadsheets={NONE}
        plugins={plugins}
        plugin={read}
      />
    );
    return { onChange, view };
  };

  it("offers only the installs and endpoints a statement can name", async () => {
    const user = userEvent.setup();
    show(reading);
    await user.click(screen.getByRole("combobox", { name: "Plug-in" }));
    expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
      "Shop",
    ]);
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("combobox", { name: "What it reads" }));
    expect((await screen.findAllByRole("option")).map((option) => option.textContent)).toEqual([
      "orders",
      "refunds",
    ]);
  });

  it("starts over on another endpoint", async () => {
    const user = userEvent.setup();
    const { onChange } = show(reading);
    await user.click(screen.getByRole("combobox", { name: "What it reads" }));
    await user.click(await screen.findByRole("option", { name: "refunds" }));
    expect(onChange).toHaveBeenLastCalledWith({
      plugin: { plugin: "acme.shop", endpoint: "refunds" },
      columns: [COUNT_ALL],
      where: [],
      group_by: [],
    });
  });
});

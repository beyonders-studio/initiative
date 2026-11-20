/**
 * A tool plug-in's rows, drawn from the lists it declared: a grid or wall of
 * its card or a table of its columns, each field in its kind's look, in the
 * order a sort puts them as a view.
 */
import { screen, within } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildToolPlugin, buildToolRow, TOOL_PLUGIN_UID } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { ActorKind } from "@/api/generated/initiativeAPI.schemas";
import { installedTool, type ToolTable } from "@/lib/toolPlugins";
import { shippedLists } from "@/ui/layouts/layoutSet";

import { ToolRows } from "./ToolRows";

const uid = TOOL_PLUGIN_UID.toLowerCase();

const tableOf = (key: string): ToolTable =>
  installedTool(buildToolPlugin())?.tables.get(`${key}.${uid}`) as ToolTable;

const noop = () => {};

describe("ToolRows", () => {
  it("draws each row's card, its name opening the row, tinted and in the declared look", async () => {
    const row = buildToolRow({
      name: "Middlemarch",
      fields: { read: 40, pages: 300, cover: "#336699" },
    });
    const table = tableOf("book");
    renderPage(() => (
      <ToolRows
        table={table}
        list={shippedLists(table.layouts.lists)[0]}
        rows={[row]}
        initiativeId={3}
        sorting={[]}
        onSortingChange={noop}
      />
    ));

    const name = await screen.findByRole("link", { name: "Middlemarch" });
    expect(name).toHaveAttribute("href", `/c/1/i/3/t/book.${uid}/${row.id}`);
    // The layout draws the counter as a bar, bounded by the row's own length.
    expect(screen.getByRole("img", { name: "40 / 300" })).toBeInTheDocument();
    // The card takes the colour its `tint` field holds.
    expect(name.closest("[style]")).toHaveStyle({ backgroundColor: "#336699" });
  });

  it("draws a table of the columns its list names, sorted as a view", async () => {
    const table = tableOf("shelf");
    renderPage(() => (
      <ToolRows
        table={table}
        list={shippedLists(table.layouts.lists)[1]}
        rows={[
          buildToolRow({ name: "Essays", fields: { about: "Short" } }),
          buildToolRow({ name: "Novels", fields: { about: "Long" } }),
        ]}
        initiativeId={3}
        sorting={[{ id: "name", desc: true }]}
        onSortingChange={noop}
      />
    ));

    expect(await screen.findByRole("columnheader", { name: /about/i })).toBeInTheDocument();
    const names = screen
      .getAllByRole("link")
      .map((link) => link.textContent)
      .filter((text) => text === "Essays" || text === "Novels");
    expect(names).toEqual(["Novels", "Essays"]);
  });

  it("draws who added each row where a layout names created_by", async () => {
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({ items: [buildToolPlugin({ id: 9, name: "Shelf keeper" })] })
      )
    );
    const shelf = tableOf("shelf");
    const table: ToolTable = {
      ...shelf,
      layouts: {
        ...shelf.layouts,
        lists: [
          {
            kind: "grid",
            card: {
              type: "card",
              children: [
                { type: "field", props: { field: "name" } },
                { type: "field", props: { field: "created_by" } },
              ],
            },
          },
          { kind: "table", columns: ["name", "created_by"] },
        ],
      },
    };
    const rows = [
      buildToolRow({ name: "Essays", created_by: 7 }),
      buildToolRow({
        name: "Novels",
        created_by: null,
        created_by_kind: ActorKind.plugin,
        created_by_install: 9,
      }),
    ];
    const lists = shippedLists(table.layouts.lists);
    const view = renderPage(() => (
      <ToolRows
        table={table}
        list={lists[0]}
        rows={rows}
        initiativeId={3}
        sorting={[]}
        onSortingChange={noop}
      />
    ));

    // A card names a member by the person field's look, a plug-in by its name.
    expect(await screen.findByText("#7")).toBeInTheDocument();
    expect(await screen.findByText("Shelf keeper")).toBeInTheDocument();
    view.unmount();

    renderPage(() => (
      <ToolRows
        table={table}
        list={lists[1]}
        rows={rows}
        initiativeId={3}
        sorting={[]}
        onSortingChange={noop}
      />
    ));
    expect(await screen.findByRole("columnheader", { name: /added by/i })).toBeInTheDocument();
    const novels = (await screen.findByRole("link", { name: "Novels" })).closest("tr");
    expect(await within(novels as HTMLElement).findByText("Shelf keeper")).toBeInTheDocument();
    const essays = screen.getByRole("link", { name: "Essays" }).closest("tr");
    expect(within(essays as HTMLElement).getByText("#7")).toBeInTheDocument();
  });
});

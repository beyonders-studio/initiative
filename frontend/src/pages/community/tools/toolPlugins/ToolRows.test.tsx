/**
 * A tool plug-in's rows, drawn from the lists it declared: a grid or wall of
 * its card or a table of its columns, each field in its kind's look, in the
 * order a sort puts them as a view.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildToolPlugin,
  buildToolRow,
  buildToolRowRead,
  TOOL_PLUGIN_UID,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { ActorKind, type CardPartInput } from "@/api/generated/initiativeAPI.schemas";
import { type InstalledTool, installedTool, type ToolTable } from "@/lib/toolPlugins";
import { shippedLists } from "@/ui/layouts/layoutSet";

import { ToolRows } from "./ToolRows";

const uid = TOOL_PLUGIN_UID.toLowerCase();

const tool = (): InstalledTool => installedTool(buildToolPlugin()) as InstalledTool;
const tableOf = (key: string): ToolTable => tool().tables.get(`${key}.${uid}`) as ToolTable;

const noop = () => {};

describe("ToolRows", () => {
  it("draws each row's card in its declared look, its name opening the row", async () => {
    const row = buildToolRow({ name: "Middlemarch", fields: { read: 40, pages: 300 } });
    const table = tableOf("book");
    renderPage(() => (
      <ToolRows
        tool={tool()}
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
    // The list's displays, and the counter's bound as the row holds it.
    expect(screen.getByRole("img", { name: "40 / 300" })).toBeInTheDocument();
  });

  it("previews a row's first items on its card, each stepping its counter", async () => {
    const book = buildToolRowRead({ name: "Emma", fields: { read: 3, pages: 10 } });
    const shelf = tableOf("shelf");
    const card: CardPartInput = {
      type: "card",
      children: [
        { type: "field", props: { field: "name" } },
        { type: "items", props: { item: "book", fields: ["name", "read"], limit: 2 } },
      ],
    };
    let stepped: unknown = null;
    server.use(
      communityHttp.post(`/plugin-tools/book.${uid}/${book.id}/step`, async ({ request }) => {
        stepped = await request.json();
        return HttpResponse.json({ ...book, fields: { ...book.fields, read: 4 } });
      })
    );
    renderPage(() => (
      <ToolRows
        tool={tool()}
        table={shelf}
        list={shippedLists([{ kind: "grid", card }])[0]}
        rows={[buildToolRow({ kind: shelf.kind, preview: { [`book.${uid}`]: [book] } })]}
        initiativeId={3}
        sorting={[]}
        onSortingChange={noop}
      />
    ));

    expect(await screen.findByRole("link", { name: "Emma" })).toHaveAttribute(
      "href",
      `/c/1/i/3/t/book.${uid}/${book.id}`
    );
    await userEvent.click(screen.getByRole("button", { name: "Step Read up" }));
    await waitFor(() => expect(stepped).toEqual({ field: "read" }));
  });

  it("draws a table of the columns its list names, sorted as a view", async () => {
    const table = tableOf("shelf");
    renderPage(() => (
      <ToolRows
        tool={tool()}
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
        tool={tool()}
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
        tool={tool()}
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

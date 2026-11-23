/**
 * A tool plug-in's rows, drawn from the lists it declared: a grid of its card
 * or a table of its columns, each field in its kind's look, in the order a
 * sort puts them as a view. A row's card on its parent's page is drawn in
 * `ToolPluginRowPage.test.tsx`; these are the parts no shipped list has.
 */

import type { SortingState } from "@tanstack/react-table";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import {
  buildToolPlugin,
  buildToolRow,
  buildToolRowRead,
  TOOL_PLUGIN_UID,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { ActorKind } from "@/api/generated/initiativeAPI.schemas";
import { type InstalledTool, installedTool, type ToolRow } from "@/lib/toolPlugins";
import { shippedLists } from "@/ui/layouts/layoutSet";

import { ToolRows } from "./ToolRows";

const uid = TOOL_PLUGIN_UID.toLowerCase();
const field = (key: string) => ({ type: "field" as const, props: { field: key } });

/** The shelves as `list` draws them. */
const draw = (
  list: Parameters<typeof shippedLists>[0][number],
  rows: ToolRow[],
  sorting: SortingState = []
) => {
  const tool = installedTool(buildToolPlugin()) as InstalledTool;
  const shelf = tool.tables.get(`shelf.${uid}`);
  if (!shelf) throw new Error("no shelf table");
  renderPage(() => (
    <ToolRows
      tool={tool}
      table={shelf}
      list={shippedLists([list])[0]}
      rows={rows}
      initiativeId={3}
      sorting={sorting}
      onSortingChange={() => {}}
    />
  ));
};

/** Essays, added by member 7, and Novels, added by the shelf's own plug-in. */
const byWhom = (essays: Partial<ToolRow> = {}) => [
  buildToolRow({ name: "Essays", created_by: 7, ...essays }),
  buildToolRow({
    name: "Novels",
    created_by: null,
    created_by_kind: ActorKind.plugin,
    created_by_install: 9,
  }),
];

beforeEach(() => {
  server.use(
    communityHttp.get("/plugins/", () =>
      HttpResponse.json({ items: [buildToolPlugin({ id: 9, name: "Shelf keeper" })] })
    )
  );
});

describe("ToolRows", () => {
  it("draws a card's parts: who added it, and its first items, each stepping", async () => {
    const book = (name: string, cover?: string) =>
      buildToolRowRead({
        kind: `book.${uid}`,
        name,
        fields: { read: 3, pages: 10, cover: cover ?? null },
      });
    const books = [book("Emma", "#C2A35B"), book("Persuasion"), book("Ivanhoe")];
    let stepped: unknown = null;
    server.use(
      communityHttp.post(`/plugin-tools/book.${uid}/${books[0].id}/step`, async ({ request }) => {
        stepped = await request.json();
        return HttpResponse.json({ ...books[0], fields: { ...books[0].fields, read: 4 } });
      })
    );
    draw(
      {
        kind: "grid",
        card: {
          type: "card",
          children: [
            field("name"),
            field("created_by"),
            {
              type: "items",
              props: { item: "book", fields: ["name", "read"], limit: 2, tint: "cover" },
            },
          ],
        },
      },
      // Novels' list read none of its items.
      byWhom({ preview: { [`book.${uid}`]: books } })
    );

    // A member by the person field's look, a plug-in by its name.
    expect(await screen.findByText("#7")).toBeInTheDocument();
    expect(await screen.findByText("Shelf keeper")).toBeInTheDocument();
    // The first two books, each in its cover's colour and opening its page.
    const lines = screen.getAllByRole("listitem").filter((line) => line.closest("li li"));
    expect(screen.getAllByRole("list")).toHaveLength(2);
    expect(lines.map((line) => within(line).getByRole("link").textContent)).toEqual([
      "Emma",
      "Persuasion",
    ]);
    expect(lines[0]).toHaveStyle({ backgroundColor: "#C2A35B" });
    expect(lines[1]).not.toHaveAttribute("style");
    expect(within(lines[0]).getByRole("link")).toHaveAttribute(
      "href",
      `/c/1/i/3/t/book.${uid}/${books[0].id}`
    );
    await userEvent.click(within(lines[0]).getByRole("button", { name: "Step Read up" }));
    await waitFor(() => expect(stepped).toEqual({ field: "read" }));
  });

  it("draws a table of the columns its list names, sorted as a view", async () => {
    draw({ kind: "table", columns: ["name", "about", "created_by"] }, byWhom(), [
      { id: "name", desc: true },
    ]);

    expect(await screen.findByRole("columnheader", { name: /about/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /added by/i })).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("link")[0].textContent)).toEqual([
      "Novels",
      "Essays",
    ]);
    expect(await within(rows[0]).findByText("Shelf keeper")).toBeInTheDocument();
    expect(within(rows[1]).getByText("#7")).toBeInTheDocument();
  });
});

/**
 * A tool plug-in's rows, drawn from the list layout it declared: a grid of its
 * card or a table of its columns, each field in its kind's look.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildToolPlugin, buildToolRow, TOOL_PLUGIN_UID } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { installedTool, type ToolTable } from "@/lib/toolPlugins";

import { ToolRows } from "./ToolRows";

const uid = TOOL_PLUGIN_UID.toLowerCase();

const bookTable = (): ToolTable =>
  installedTool(buildToolPlugin())?.tables.get(`book.${uid}`) as ToolTable;

describe("ToolRows", () => {
  it("draws each row's card, its name opening the row and its counter in the declared look", async () => {
    const row = buildToolRow({ name: "Middlemarch", values: { read: 40, pages: 300 } });
    const table = bookTable();
    renderPage(() => (
      <ToolRows table={table} list={table.layouts.list} rows={[row]} initiativeId={3} />
    ));

    const name = await screen.findByRole("link", { name: "Middlemarch" });
    expect(name).toHaveAttribute("href", `/c/1/i/3/t/book.${uid}/${row.id}`);
    // The layout draws the counter as a bar, bounded by the row's own length.
    expect(screen.getByRole("img", { name: "40 / 300" })).toBeInTheDocument();
  });

  it("draws a table of the columns its layout names", async () => {
    renderPage(() => (
      <ToolRows
        table={bookTable()}
        list={{ kind: "table", columns: ["name", "status", "cover"] }}
        rows={[buildToolRow({ name: "Emma", values: { status: "done", cover: "#336699" } })]}
        initiativeId={3}
      />
    ));

    expect(await screen.findByRole("columnheader", { name: /status/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /cover/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Emma" })).toBeInTheDocument();
    expect(screen.getByText("Read")).toBeInTheDocument();
    expect(screen.getByText("#336699")).toBeInTheDocument();
  });
});

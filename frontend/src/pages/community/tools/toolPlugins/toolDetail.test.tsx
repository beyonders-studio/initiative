/**
 * A tool plug-in's row on its own page, drawn from the detail layout its table
 * declared, and the add dialog drawn from the same layout.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useContext } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildToolPlugin, buildToolRow, TOOL_PLUGIN_UID } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { installedTool, type ToolRow, type ToolTable } from "@/lib/toolPlugins";
import { DetailLayoutView } from "@/ui/layouts/DetailLayoutView";
import { ItemDraftContext, type ItemEdit } from "@/ui/layouts/editing";
import type { ItemSaves } from "@/ui/layouts/fieldEditors";

import { AddToolRowDialog, blankRow } from "./AddToolRowDialog";
import { type ToolRowContext, type ToolRowUpdate, toolDetail } from "./toolDetail";

const uid = TOOL_PLUGIN_UID.toLowerCase();

const bookTable = () => installedTool(buildToolPlugin())?.tables.get(`book.${uid}`) as ToolTable;

/** Saves that take each change, as a page's do: into the draft of a row
 *  being added, and as sent on a row that is there. */
const saves = (): ItemSaves<ToolRow, ToolRowUpdate> => ({
  useSave: () => {
    const draft = useContext(ItemDraftContext);
    return {
      state: "idle",
      retry: () => {},
      save: async (edit) => {
        draft?.edit(edit as ItemEdit<unknown, unknown>);
        return true;
      },
    };
  },
  useShown: (properties) => properties,
});

const context = (readOnly: boolean): ToolRowContext => ({
  readOnly,
  initiativeId: 1,
  saves: saves(),
  actions: null,
});

describe("toolDetail", () => {
  it("draws a row as its declared layout places it, each field in its kind's look", async () => {
    const row = buildToolRow({
      name: "Middlemarch",
      values: { read: 40, pages: 300, status: "done", cover: "#336699" },
    });
    renderPage(() => (
      <DetailLayoutView detail={toolDetail(bookTable(), "en")} item={row} context={context(true)} />
    ));

    expect(await screen.findByRole("heading", { name: "Middlemarch" })).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.getByText("Read", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("#336699")).toBeInTheDocument();
    // Its `notice` part says why nothing can be changed.
    expect(screen.getByText("You can read this, but not change it.")).toBeInTheDocument();
  });

  it("gives each declared field its kind's editor for someone who may change it", async () => {
    const row = buildToolRow({ name: "Emma", values: { pages: 474, status: "unread" } });
    renderPage(() => (
      <DetailLayoutView
        detail={toolDetail(bookTable(), "en")}
        item={row}
        context={context(false)}
      />
    ));

    const pages = await screen.findByRole("group", { name: "Pages" });
    expect(within(pages).getByRole("spinbutton")).toHaveValue(474);
    expect(screen.getByRole("group", { name: "Status" })).toBeInTheDocument();
  });
});

describe("AddToolRowDialog", () => {
  it("starts each field at its default and a counter where it starts", () => {
    const table = bookTable();
    expect(blankRow(table, 4)).toMatchObject({
      initiative_id: 4,
      name: "",
      values: { pages: null, read: 0, status: null },
    });
  });

  it("makes the row from what was filled in", async () => {
    const create = vi.fn(async () => ({ id: 9 }));
    const onAdded = vi.fn();
    renderPage(() => (
      <AddToolRowDialog
        open
        onOpenChange={() => {}}
        table={bookTable()}
        initiativeId={4}
        saves={saves()}
        create={create}
        onAdded={onAdded}
      />
    ));
    const user = userEvent.setup();

    const add = await screen.findByRole("button", { name: "New Book" });
    expect(add).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Persuasion");
    await waitFor(() => expect(add).toBeEnabled());
    await user.click(add);

    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Persuasion", values: expect.objectContaining({ read: 0 }) })
    );
    await waitFor(() => expect(onAdded).toHaveBeenCalledWith({ id: 9 }));
  });
});

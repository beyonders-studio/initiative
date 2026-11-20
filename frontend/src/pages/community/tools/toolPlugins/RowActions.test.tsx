/**
 * What every tool's items have, on a tool plug-in's row: its access settings,
 * archiving, deleting and tags, each offered only where the row's `can`
 * allows it and sent to the universal route with the row's own kind.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildTagSummary,
  buildToolPlugin,
  buildToolRowRead,
  ownerCan,
  readerCan,
  shelfDefinition,
  TOOL_PLUGIN_UID,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { PluginToolRowRead, ToolCan } from "@/api/generated/initiativeAPI.schemas";

import { ToolPluginRowPage } from "./ToolPluginRowPage";

const PICKED = buildTagSummary({ id: 99, name: "Classics" });

// The picker's own UI is not what these tests are about: this stub reports the
// selection it was handed and offers one way to change it.
vi.mock("@/components/tags/TagPicker", () => ({
  TagPicker: ({
    selectedTags,
    onChange,
  }: {
    selectedTags: { id: number; name: string }[];
    onChange: (tags: { id: number; name: string }[]) => void;
  }) => (
    <div>
      <span data-testid="selected-tags">{selectedTags.map((tag) => tag.name).join(",")}</span>
      <button type="button" onClick={() => onChange([PICKED])}>
        pick tag
      </button>
    </div>
  ),
}));

const uid = TOOL_PLUGIN_UID.toLowerCase();
const shelf = `shelf.${uid}`;
const book = `book.${uid}`;

const field = (key: string) => ({ type: "field", props: { field: key } });

/** The shelf, its rows' pages placing their actions (a book's, unless its
 *  layout leaves them out as shipped) and tags, and a book's card its tags. */
const definition = (placeBookActions: boolean) => {
  const made = shelfDefinition();
  made.tool.layouts.detail.main.push(field("tags"));
  const [books] = made.tool.items;
  if (placeBookActions) {
    Object.assign(books.layouts.detail, { header: [field("name"), { type: "actions" }] });
  }
  books.layouts.lists[0].card.children.push(field("tags"));
  return made;
};

/** The page of one row: the shelf's 5, or book 8 on it. */
const show = (
  kind: string,
  overrides: Partial<PluginToolRowRead> = {},
  placeBookActions = true
) => {
  const rowId = kind === shelf ? 5 : 8;
  server.use(
    communityHttp.get("/plugins/", () =>
      HttpResponse.json({
        items: [buildToolPlugin({ definition: definition(placeBookActions) } as never)],
      })
    ),
    communityHttp.get(`/plugin-tools/${kind}/${rowId}`, () =>
      HttpResponse.json(
        buildToolRowRead({
          kind,
          id: rowId,
          initiative_id: 3,
          parent_id: kind === shelf ? null : 5,
          name: kind === shelf ? "Novels" : "Middlemarch",
          ...overrides,
        })
      )
    ),
    communityHttp.get(`/plugin-tools/${book}/`, () =>
      HttpResponse.json({
        items: [],
        total_count: 0,
        page: 1,
        page_size: 0,
        has_next: false,
        has_prev: false,
      })
    )
  );
  return renderPage(ToolPluginRowPage, {
    initialRoute: "/c/$communityId/i/$initiativeId/t/$kind/$rowId",
    routeParams: { communityId: "1", initiativeId: "3", kind, rowId: String(rowId) },
  });
};

/** The names of what the row's menu offers. */
const offered = async (): Promise<string[]> => {
  await userEvent.setup().click(await screen.findByRole("button", { name: "Actions" }));
  const items = await screen.findAllByRole("menuitem");
  return items.map((item) => item.textContent ?? "");
};

describe("a tool plug-in's row", () => {
  it("offers its owner its access settings, archiving and deleting", async () => {
    show(shelf, { can: ownerCan() });

    expect(await offered()).toEqual(["Access settings", "Archive", "Delete"]);
  });

  it.each<[string, ToolCan, string[]]>([
    [
      "a writer, who may archive it but not share or delete it",
      ownerCan({ share: false, delete: false }),
      ["Archive"],
    ],
    [
      "the owner of an archived row, who may take it back out",
      readerCan({ unarchive: true }),
      ["Unarchive"],
    ],
  ])("offers %s only that", async (_who, can, names) => {
    show(shelf, { can, archived_at: names[0] === "Unarchive" ? "2026-11-03T00:00:00Z" : null });

    expect(await offered()).toEqual(names);
  });

  it("offers a reader nothing at all", async () => {
    show(shelf, { can: readerCan() });

    expect((await screen.findAllByText("Novels")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Actions" })).not.toBeInTheDocument();
  });

  it.each([
    ["archive", null, ownerCan()],
    ["unarchive", "2026-11-03T00:00:00Z", readerCan({ unarchive: true })],
  ])("sends %s to the universal route by its kind", async (route, archivedAt, can) => {
    const asked: string[] = [];
    server.use(
      communityHttp.post(`/${route}/:kind/:id`, ({ params }) => {
        asked.push(`${params.kind}/${params.id}`);
        return HttpResponse.json({
          entity_type: params.kind,
          entity_id: 5,
          archived_at: archivedAt ? null : "2026-11-03T00:00:00Z",
        });
      })
    );
    show(shelf, { can, archived_at: archivedAt });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(
      await screen.findByRole("menuitem", { name: route === "archive" ? "Archive" : "Unarchive" })
    );

    await waitFor(() => expect(asked).toEqual([`${shelf}/5`]));
  });

  it("puts it in the trash once asked", async () => {
    const deleted: string[] = [];
    server.use(
      communityHttp.delete("/plugin-tools/:kind/:id", ({ params }) => {
        deleted.push(`${params.kind}/${params.id}`);
        return new HttpResponse(null, { status: 204 });
      })
    );
    show(shelf, { can: ownerCan() });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(deleted).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleted).toEqual([`${shelf}/5`]));
  });

  it("shares it through the bulk route by its kind, with the note", async () => {
    let sent: unknown = null;
    server.use(
      communityHttp.put("/resource-grants/bulk", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          results: [{ resource_type: shelf, resource_id: 5, status: "ok" }],
        });
      })
    );
    show(shelf, {
      can: ownerCan(),
      grants: [{ all_initiative_members: true, level: "read" }],
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Access settings" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByRole("textbox"), "For the club");
    await user.click(within(dialog).getByRole("button", { name: /All initiative members/i }));
    await user.click(await screen.findByRole("button", { name: /Restricted/i }));

    await waitFor(() =>
      expect(sent).toEqual({
        items: [{ resource_type: shelf, resource_id: 5, grants: [] }],
        note: "For the club",
      })
    );
  });

  it("tags it, saved on its own change", async () => {
    let sent: unknown = null;
    show(shelf, { can: ownerCan() });
    const row = (tags = [PICKED]) =>
      buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3, name: "Novels", tags });
    server.use(
      communityHttp.patch(`/plugin-tools/${shelf}/5`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(row());
      }),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(row(sent ? [PICKED] : []))
      )
    );

    await userEvent.setup().click(await screen.findByRole("button", { name: "pick tag" }));

    await waitFor(() => expect(sent).toEqual({ tag_ids: [99] }));
    expect(await screen.findByTestId("selected-tags")).toHaveTextContent("Classics");
  });

  it("shows a reader its tags and no picker", async () => {
    show(shelf, { can: readerCan(), tags: [PICKED] });

    expect(await screen.findByText("Classics")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "pick tag" })).not.toBeInTheDocument();
  });

  it("draws the tags of the items under it on their cards", async () => {
    show(shelf);
    server.use(
      communityHttp.get(`/plugin-tools/${book}/`, () =>
        HttpResponse.json({
          items: [
            buildToolRowRead({ kind: book, id: 8, initiative_id: 3, parent_id: 5, tags: [PICKED] }),
          ],
          total_count: 1,
          page: 1,
          page_size: 0,
          has_next: false,
          has_prev: false,
        })
      )
    );

    expect(await screen.findByRole("link", { name: "Classics" })).toHaveAttribute(
      "href",
      "/c/1/tags/99"
    );
  });
});

describe("an item of a tool plug-in", () => {
  it("is shared as its tool is, so it offers no access settings of its own", async () => {
    show(book, { can: ownerCan() });

    expect(await offered()).toEqual(["Archive", "Delete"]);
  });

  it("offers its actions where its page's layout does not place them", async () => {
    show(book, { can: ownerCan() }, false);

    expect(await offered()).toEqual(["Archive", "Delete"]);
  });

  it("is deleted by whoever may change it, and sent to the trash by its kind", async () => {
    const deleted: string[] = [];
    server.use(
      communityHttp.delete("/plugin-tools/:kind/:id", ({ params }) => {
        deleted.push(`${params.kind}/${params.id}`);
        return new HttpResponse(null, { status: 204 });
      })
    );
    show(book, { can: ownerCan({ delete: false, edit: false }) });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Delete"]);
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" })
    );

    await waitFor(() => expect(deleted).toEqual([`${book}/8`]));
  });

  it("offers nothing to someone who may not add to its tool", async () => {
    show(book, { can: readerCan() });

    expect((await screen.findAllByText("Middlemarch")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Actions" })).not.toBeInTheDocument();
  });
});

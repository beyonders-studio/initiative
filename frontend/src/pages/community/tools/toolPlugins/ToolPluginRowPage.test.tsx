/**
 * A tool plug-in's row on its own page: its table's declared detail, the rows
 * of each item table under it, and what every tool's items have (access
 * settings, archiving, deleting, tags and its declared actions), each offered
 * only where the row's `can` allows it and sent to the universal route with
 * the row's own kind.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse } from "msw";
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

/** The page of `kind`'s row as the URL names it: the shelf's 5, or book 8. */
const open = (kind: string) =>
  renderPage(ToolPluginRowPage, {
    initialRoute: "/c/$communityId/i/$initiativeId/t/$kind/$rowId",
    routeParams: {
      communityId: "1",
      initiativeId: "3",
      kind,
      rowId: String(kind === book ? 8 : 5),
    },
  });

/** The page of one row, the shelf's 5 or book 8 on it, of the shelf as
 *  `definition` declares it, with `tool` over its tool block. */
const show = (
  kind: string,
  overrides: Partial<PluginToolRowRead> = {},
  { placeBookActions = true, tool = {} }: { placeBookActions?: boolean; tool?: object } = {}
) => {
  const rowId = kind === shelf ? 5 : 8;
  const declared = definition(placeBookActions);
  Object.assign(declared.tool, tool);
  server.use(
    communityHttp.get("/plugins/", () =>
      HttpResponse.json({ items: [buildToolPlugin({ definition: declared } as never)] })
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
    communityHttp.get(`/plugin-tools/${book}/`, () => HttpResponse.json(page([])))
  );
  return open(kind);
};

/** A page of rows, as the list route answers. */
const page = (items: PluginToolRowRead[]) => ({
  items,
  total_count: items.length,
  page: 1,
  page_size: 0,
  has_next: false,
  has_prev: false,
});

/** Middlemarch on the shelf, 200 of its 800 pages read. */
const middlemarch = () =>
  buildToolRowRead({
    id: 8,
    initiative_id: 3,
    parent_id: 5,
    name: "Middlemarch",
    fields: { pages: 800, read: 200 },
  });

/** The names of what the row's menu offers. */
const offered = async (): Promise<string[]> => {
  await userEvent.setup().click(await screen.findByRole("button", { name: "Actions" }));
  const items = await screen.findAllByRole("menuitem");
  return items.map((item) => item.textContent ?? "");
};

describe("ToolPluginRowPage", () => {
  it("draws the row from its declared layout and lists the items under it", async () => {
    show(shelf, { fields: { about: "Long ones" } });
    server.use(
      communityHttp.get(`/plugin-tools/${book}/`, ({ request }) =>
        HttpResponse.json(
          page(new URL(request.url).searchParams.get("parent_id") === "5" ? [middlemarch()] : [])
        )
      )
    );

    expect(await screen.findByDisplayValue("Novels")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Long ones")).toBeInTheDocument();
    // Its breadcrumb leads back to the tool's list.
    expect(screen.getByRole("link", { name: "Reading" })).toHaveAttribute(
      "href",
      `/c/1/i/3/t/${shelf}`
    );
    // The books under it, each as the book table's card draws it.
    expect(await screen.findByRole("link", { name: "Middlemarch" })).toHaveAttribute(
      "href",
      `/c/1/i/3/t/${book}/8`
    );
    expect(screen.getByRole("img", { name: "200 / 800" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New Book" })).toBeInTheDocument();
  });

  it("draws the row and its items as the places they are listed in laid them out", async () => {
    const changed = "2026-11-01T00:00:00Z";
    const name = { type: "field", props: { field: "name" } };
    show(shelf, { fields: { about: "Long ones" } });
    server.use(
      communityHttp.get(`/plugin-tools/${book}/`, () => HttpResponse.json(page([middlemarch()]))),
      communityHttp.get("/layouts/", ({ request }) => {
        const params = new URL(request.url).searchParams;
        // The shelves' page, as their initiative changed it: its name alone.
        if (params.get("tool") === shelf && params.get("initiative_id") === "3") {
          return HttpResponse.json({
            can_configure: false,
            layouts: [
              {
                kind: shelf,
                definition: { header: [name], main: [], side: [] },
                updated_at: changed,
              },
            ],
          });
        }
        // The books' grid under this shelf, as it changed it: their names alone.
        if (params.get("tool") === book && params.get("tool_id") === "5") {
          return HttpResponse.json({
            can_configure: false,
            layouts: [
              {
                kind: "grid",
                is_default: true,
                hidden: false,
                definition: { card: { type: "card", children: [name] } },
                updated_at: changed,
              },
            ],
          });
        }
        return HttpResponse.json({ can_configure: false, layouts: [] });
      })
    );

    expect(await screen.findByDisplayValue("Novels")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByDisplayValue("Long ones")).not.toBeInTheDocument());
    expect(await screen.findByRole("link", { name: "Middlemarch" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("img", { name: "200 / 800" })).not.toBeInTheDocument()
    );
  });

  it("offers a retry when the installs can't be read", async () => {
    let fail = true;
    server.use(
      communityHttp.get("/plugins/", () =>
        fail
          ? HttpResponse.json({ detail: "x" }, { status: 500 })
          : HttpResponse.json({ items: [buildToolPlugin()] })
      ),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(
          buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3, name: "Novels" })
        )
      )
    );
    open(shelf);

    expect(
      await screen.findByText("This community's tools couldn't be loaded.")
    ).toBeInTheDocument();
    expect(screen.queryByText("This isn't here")).not.toBeInTheDocument();
    fail = false;
    await userEvent.setup().click(screen.getByRole("button", { name: /try again|retry/i }));
    expect(await screen.findByDisplayValue("Novels")).toBeInTheDocument();
  });

  it("asks for an action's params and sends them, running it once at a time", async () => {
    let sent: unknown = null;
    let runs = 0;
    server.use(
      communityHttp.post(`/plugin-tools/${shelf}/5/actions/describe`, async ({ request }) => {
        runs += 1;
        sent = await request.json();
        await delay(200);
        return HttpResponse.json(buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3 }));
      })
    );
    show(
      shelf,
      { can: ownerCan() },
      {
        tool: {
          actions: [
            {
              id: "describe",
              name: { en: "Describe" },
              on: "shelf",
              params: ["about"],
              write: "{set: {about: params.about}}",
            },
          ],
        },
      }
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Describe" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Long ones");
    await user.click(within(dialog).getByRole("button", { name: "Describe" }));

    // While it runs, it can't be run again.
    await waitFor(() => expect(within(dialog).getAllByRole("button").at(-1)).toBeDisabled());
    await user.click(within(dialog).getAllByRole("button").at(-1) as HTMLElement);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(runs).toBe(1);
    expect(sent).toEqual({ fields: { about: "Long ones" }, people: {} });
  });

  it("starts each param as a new row's field would, so unchanged answers send", async () => {
    let sent: unknown = null;
    server.use(
      communityHttp.post(`/plugin-tools/${shelf}/5/actions/rate`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3 }));
      })
    );
    show(
      shelf,
      { can: ownerCan() },
      {
        tool: {
          fields: [
            ...shelfDefinition().tool.fields,
            { key: "goal", name: { en: "Goal" }, kind: "number", default: 12 },
            { key: "stars", name: { en: "Stars" }, kind: "counter", counter: { initial: "goal" } },
            { key: "tint", name: { en: "Tint" }, kind: "color", default: "random" },
          ],
          actions: [
            {
              id: "rate",
              name: { en: "Rate" },
              on: "shelf",
              params: ["stars", "tint"],
              write: "{set: {stars: params.stars, tint: params.tint}}",
            },
          ],
        },
      }
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rate" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Rate" }));

    await waitFor(() => expect(sent).toEqual({ fields: { stars: 12, tint: null }, people: {} }));
  });

  it("can't run an action again from the menu while it runs", async () => {
    let runs = 0;
    server.use(
      communityHttp.post(`/plugin-tools/${shelf}/5/actions/bump`, async () => {
        runs += 1;
        await delay(300);
        return HttpResponse.json(buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3 }));
      })
    );
    show(
      shelf,
      { can: ownerCan() },
      { tool: { actions: [{ id: "bump", name: { en: "Bump" }, on: "shelf", write: "null" }] } }
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Bump" }));
    await user.click(screen.getByRole("button", { name: "Actions" }));
    const again = await screen.findByRole("menuitem", { name: "Bump" });
    expect(again).toHaveAttribute("data-disabled");
    await user.click(again);
    await waitFor(() => expect(runs).toBe(1));
  });

  it("says so where no installed tool has the kind", async () => {
    open("nothing.here");

    expect(await screen.findByText("This isn't here")).toBeInTheDocument();
  });
});

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
    show(book, { can: ownerCan() }, { placeBookActions: false });

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

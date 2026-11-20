/**
 * A tool plug-in's row on its own page: its table's declared detail, the rows
 * of each item table under it and the dialog that adds one, and what every
 * tool's items have (access settings, archiving, deleting, tags and its
 * declared actions), each offered only where the row's `can` allows it and
 * sent to the universal route with the row's own kind.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

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

const CLASSICS = buildTagSummary({ id: 99, name: "Classics" });

const uid = TOOL_PLUGIN_UID.toLowerCase();
const shelf = `shelf.${uid}`;
const book = `book.${uid}`;

const field = (key: string) => ({ type: "field", props: { field: key } });

/** The shelf, its page placing its tags, and a book's card its tags. */
const definition = () => {
  const made = shelfDefinition();
  made.tool.layouts.detail.main.push(field("tags"));
  made.tool.items[0].layouts.lists[0].card.children.push(field("tags"));
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

/** A page of rows, as the list route answers. */
const page = (items: PluginToolRowRead[]) => ({
  items,
  total_count: items.length,
  page: 1,
  page_size: 0,
  has_next: false,
  has_prev: false,
});

/** The page of one row, the shelf's 5 or book 8 on it, of the shelf as
 *  `definition` declares it, with `tool` over its tool block. */
const show = (kind: string, overrides: Partial<PluginToolRowRead> = {}, tool: object = {}) => {
  const rowId = kind === shelf ? 5 : 8;
  const declared = definition();
  Object.assign(declared.tool, tool);
  server.use(
    communityHttp.get("/plugins/", () =>
      HttpResponse.json({ items: [buildToolPlugin({ definition: declared })] })
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

/** Middlemarch on the shelf, 200 of its 800 pages read. */
const middlemarch = (overrides: Partial<PluginToolRowRead> = {}) =>
  buildToolRowRead({
    kind: book,
    id: 8,
    initiative_id: 3,
    parent_id: 5,
    name: "Middlemarch",
    fields: { pages: 800, read: 200 },
    ...overrides,
  });

describe("ToolPluginRowPage", () => {
  it("draws the row from its declared layout and lists the items under it", async () => {
    show(shelf, { fields: { about: "Long ones" } });
    server.use(
      communityHttp.get(`/plugin-tools/${book}/`, ({ request }) =>
        HttpResponse.json(
          page(
            new URL(request.url).searchParams.get("parent_id") === "5"
              ? [middlemarch({ tags: [CLASSICS] })]
              : []
          )
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
    expect(screen.getByRole("link", { name: "Classics" })).toHaveAttribute("href", "/c/1/tags/99");
  });

  it("draws the row and its items as the places they are listed in laid them out", async () => {
    const changed = "2026-11-01T00:00:00Z";
    const name = field("name");
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

  it("says so where no installed tool has the kind", async () => {
    open("nothing.here");

    expect(await screen.findByText("This isn't here")).toBeInTheDocument();
  });

  it("adds an item under it, sending only the fields the person set", async () => {
    let sent: unknown = null;
    server.use(
      communityHttp.post(`/plugin-tools/${book}/`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(middlemarch({ id: 9, name: "Persuasion" }));
      })
    );
    show(shelf, { can: ownerCan() });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "New Book" }));
    const dialog = await screen.findByRole("dialog");
    const add = within(dialog).getByRole("button", { name: "New Book" });
    expect(add).toBeDisabled();
    // Each field starts as the server would start it: a counter at its least.
    const read = within(dialog).getByRole("group", { name: "Read" });
    expect(within(read).getByRole("spinbutton")).toHaveValue(0);
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Persuasion");
    const pages = within(dialog).getByRole("group", { name: "Pages" });
    await user.type(within(pages).getByRole("spinbutton"), "474");
    await user.click(add);

    await waitFor(() =>
      expect(sent).toEqual({ name: "Persuasion", parent_id: 5, fields: { pages: 474 }, people: {} })
    );
  });
});

describe("a tool plug-in's actions", () => {
  it("asks for an action's params, each started as a new row's field, and runs it once", async () => {
    let sent: unknown = null;
    let runs = 0;
    server.use(
      communityHttp.post(`/plugin-tools/${shelf}/5/actions/rate`, async ({ request }) => {
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
        fields: [
          ...shelfDefinition().tool.fields,
          { key: "goal", name: { en: "Goal" }, kind: "number", default: 12 },
          { key: "stars", name: { en: "Stars" }, kind: "counter", counter: { initial: "goal" } },
          { key: "tint", name: { en: "Tint" }, kind: "color", default: "random" },
          { key: "owned", name: { en: "Owned" }, kind: "checkbox" },
        ],
        actions: [
          {
            id: "rate",
            name: { en: "Rate" },
            on: "shelf",
            params: ["about", "stars", "tint", "owned"],
            write: "{set: params}",
          },
        ],
      }
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rate" }));
    const dialog = await screen.findByRole("alertdialog");
    // The text param's box carries no name of its own.
    await user.type(within(dialog).getByRole("textbox"), "Long ones");
    await user.click(within(dialog).getByRole("button", { name: "Rate" }));

    // While it runs, it can't be run again.
    await waitFor(() => expect(within(dialog).getAllByRole("button").at(-1)).toBeDisabled());
    await user.click(within(dialog).getAllByRole("button").at(-1) as HTMLElement);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(runs).toBe(1);
    // A counter starts at the field it names, a colour the server picks is none
    // yet and a checkbox is off; each is sent unchanged.
    expect(sent).toEqual({
      fields: { about: "Long ones", stars: 12, tint: null, owned: false },
      people: {},
    });
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
      { actions: [{ id: "bump", name: { en: "Bump" }, on: "shelf", write: "null" }] }
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
});

describe("a tool plug-in's row and its items", () => {
  const ARCHIVED = "2026-11-03T00:00:00Z";

  // A book is shared as its tool is, so it has no access settings of its own;
  // its page's layout places no actions, so they head the page.
  it.each<[string, string, ToolCan, string | null, string[], string, string]>([
    [
      "the shelf's owner everything",
      shelf,
      ownerCan(),
      null,
      ["Access settings", "Archive", "Delete"],
      "Delete",
      `DELETE plugin-tools/${shelf}/5`,
    ],
    [
      "a writer of the shelf archiving alone",
      shelf,
      ownerCan({ share: false, delete: false }),
      null,
      ["Archive"],
      "Archive",
      `POST archive/${shelf}/5`,
    ],
    [
      "the owner of an archived shelf taking it back out",
      shelf,
      readerCan({ unarchive: true }),
      ARCHIVED,
      ["Unarchive"],
      "Unarchive",
      `POST unarchive/${shelf}/5`,
    ],
    [
      "a book's owner all but access settings",
      book,
      ownerCan(),
      null,
      ["Archive", "Delete"],
      "Archive",
      `POST archive/${book}/8`,
    ],
    [
      "whoever may add to a book's tool deleting it",
      book,
      ownerCan({ delete: false, edit: false }),
      null,
      ["Delete"],
      "Delete",
      `DELETE plugin-tools/${book}/8`,
    ],
  ])("offers %s, sent by its kind", async (_who, kind, can, archivedAt, offered, pick, asked) => {
    const sent: string[] = [];
    server.use(
      communityHttp.post("/:route/:kind/:id", ({ params }) => {
        sent.push(`POST ${params.route}/${params.kind}/${params.id}`);
        return HttpResponse.json({
          entity_type: params.kind,
          entity_id: Number(params.id),
          archived_at: params.route === "archive" ? ARCHIVED : null,
        });
      }),
      communityHttp.delete("/plugin-tools/:kind/:id", ({ params }) => {
        sent.push(`DELETE plugin-tools/${params.kind}/${params.id}`);
        return new HttpResponse(null, { status: 204 });
      })
    );
    show(kind, { can, archived_at: archivedAt });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(offered);
    await user.click(screen.getByRole("menuitem", { name: pick }));
    if (pick === "Delete") {
      // Nothing is deleted until it is confirmed.
      const dialog = await screen.findByRole("alertdialog");
      expect(sent).toEqual([]);
      await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    }

    await waitFor(() => expect(sent).toEqual([asked]));
  });

  it("shows a reader the row and its tags, and offers nothing to change", async () => {
    show(shelf, { can: readerCan(), tags: [CLASSICS] });

    expect(await screen.findByText("Classics")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("shows a reader an item's fields, each in its kind's look, and why", async () => {
    show(book, {
      can: readerCan(),
      fields: { read: 40, pages: 300, status: "done", cover: "#336699" },
    });

    expect(await screen.findByRole("heading", { name: "Middlemarch" })).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.getByText("Read", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("#336699")).toBeInTheDocument();
    expect(screen.getByText("You can read this, but not change it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actions" })).not.toBeInTheDocument();
  });

  it("gives a writer each declared field's editor, holding the row's value", async () => {
    show(book, { can: ownerCan(), fields: { pages: 474, status: "unread" } });

    const pages = await screen.findByRole("group", { name: "Pages" });
    expect(within(pages).getByRole("spinbutton")).toHaveValue(474);
    expect(screen.getByRole("group", { name: "Status" })).toBeInTheDocument();
  });

  it("shares the row through the bulk route by its kind, with the note", async () => {
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

  it("tags the row, saved on its own change", async () => {
    let sent: unknown = null;
    const row = (tags: (typeof CLASSICS)[]) =>
      buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3, name: "Novels", tags });
    show(shelf, { can: ownerCan() });
    server.use(
      communityHttp.get("/tags/", () => HttpResponse.json([CLASSICS])),
      communityHttp.patch(`/plugin-tools/${shelf}/5`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(row([CLASSICS]));
      }),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(row(sent ? [CLASSICS] : []))
      )
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Classics" }));

    await waitFor(() => expect(sent).toEqual({ tag_ids: [99] }));
  });
});

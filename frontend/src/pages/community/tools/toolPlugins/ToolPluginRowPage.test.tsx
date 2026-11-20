/**
 * A tool plug-in's row on its own page: its table's declared detail, then the
 * rows of each item table under it, read through the generic routes.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildToolPlugin,
  buildToolRowRead,
  shelfDefinition,
  TOOL_PLUGIN_UID,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { ToolPluginRowPage } from "./ToolPluginRowPage";

const uid = TOOL_PLUGIN_UID.toLowerCase();
const shelf = `shelf.${uid}`;
const book = `book.${uid}`;

const render = (kind: string) =>
  renderPage(ToolPluginRowPage, {
    initialRoute: "/c/$communityId/i/$initiativeId/t/$kind/$rowId",
    routeParams: { communityId: "1", initiativeId: "3", kind, rowId: "5" },
  });

describe("ToolPluginRowPage", () => {
  it("draws the row from its declared layout and lists the items under it", async () => {
    server.use(
      communityHttp.get("/plugins/", () => HttpResponse.json({ items: [buildToolPlugin()] })),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(
          buildToolRowRead({
            kind: shelf,
            id: 5,
            initiative_id: 3,
            name: "Novels",
            fields: { about: "Long ones" },
          })
        )
      ),
      communityHttp.get(`/plugin-tools/${book}/`, ({ request }) =>
        new URL(request.url).searchParams.get("parent_id") === "5"
          ? HttpResponse.json({
              items: [
                buildToolRowRead({
                  id: 8,
                  initiative_id: 3,
                  parent_id: 5,
                  name: "Middlemarch",
                  fields: { pages: 800, read: 200 },
                }),
              ],
              total_count: 1,
              page: 1,
              page_size: 100,
              has_next: false,
              has_prev: false,
            })
          : HttpResponse.json({ items: [] })
      )
    );
    render(shelf);

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

  it("walks every page of the items under it", async () => {
    const asked: (string | null)[] = [];
    server.use(
      communityHttp.get("/plugins/", () => HttpResponse.json({ items: [buildToolPlugin()] })),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3 }))
      ),
      communityHttp.get(`/plugin-tools/${book}/`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        asked.push(params.get("page_size"));
        const page = Number(params.get("page"));
        return HttpResponse.json({
          items: [
            buildToolRowRead({
              id: 10 + page,
              initiative_id: 3,
              parent_id: 5,
              name: page === 1 ? "Middlemarch" : "Emma",
            }),
          ],
          total_count: 2,
          page,
          page_size: 0,
          has_next: page === 1,
          has_prev: page > 1,
        });
      })
    );
    render(shelf);

    expect(await screen.findByRole("link", { name: "Emma" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Middlemarch" })).toBeInTheDocument();
    expect(asked).toEqual(["0", "0"]);
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
    render(shelf);

    expect(
      await screen.findByText("This community's tools couldn't be loaded.")
    ).toBeInTheDocument();
    expect(screen.queryByText("This isn't here")).not.toBeInTheDocument();
    fail = false;
    await userEvent.setup().click(screen.getByRole("button", { name: /try again|retry/i }));
    expect(await screen.findByDisplayValue("Novels")).toBeInTheDocument();
  });

  it("asks for an action's params and sends them, running it once at a time", async () => {
    const definition = shelfDefinition();
    Object.assign(definition.tool, {
      actions: [
        {
          id: "describe",
          name: { en: "Describe" },
          on: "shelf",
          params: ["about"],
          write: "{set: {about: params.about}}",
        },
      ],
    });
    let sent: unknown = null;
    let runs = 0;
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({ items: [buildToolPlugin({ definition } as never)] })
      ),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(
          buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3, name: "Novels" })
        )
      ),
      communityHttp.post(`/plugin-tools/${shelf}/5/actions/describe`, async ({ request }) => {
        runs += 1;
        sent = await request.json();
        await delay(200);
        return HttpResponse.json(buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3 }));
      })
    );
    render(shelf);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Describe" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Long ones");
    const confirm = within(dialog).getByRole("button", { name: "Describe" });
    await user.click(confirm);

    // While it runs, it can't be run again.
    await waitFor(() => expect(within(dialog).getAllByRole("button").at(-1)).toBeDisabled());
    await user.click(within(dialog).getAllByRole("button").at(-1) as HTMLElement);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(runs).toBe(1);
    expect(sent).toEqual({ fields: { about: "Long ones" }, people: {} });
  });

  it("starts each param as a new row's field would, so unchanged answers send", async () => {
    const definition = shelfDefinition();
    Object.assign(definition.tool, {
      fields: [
        ...definition.tool.fields,
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
    });
    let sent: unknown = null;
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({ items: [buildToolPlugin({ definition } as never)] })
      ),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(
          buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3, name: "Novels" })
        )
      ),
      communityHttp.post(`/plugin-tools/${shelf}/5/actions/rate`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3 }));
      })
    );
    render(shelf);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rate" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Rate" }));

    await waitFor(() => expect(sent).toEqual({ fields: { stars: 12, tint: null }, people: {} }));
  });

  it("can't run an action again from the menu while it runs", async () => {
    const definition = shelfDefinition();
    Object.assign(definition.tool, {
      actions: [{ id: "bump", name: { en: "Bump" }, on: "shelf", write: "null" }],
    });
    let runs = 0;
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({ items: [buildToolPlugin({ definition } as never)] })
      ),
      communityHttp.get(`/plugin-tools/${shelf}/5`, () =>
        HttpResponse.json(
          buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3, name: "Novels" })
        )
      ),
      communityHttp.post(`/plugin-tools/${shelf}/5/actions/bump`, async () => {
        runs += 1;
        await delay(300);
        return HttpResponse.json(buildToolRowRead({ kind: shelf, id: 5, initiative_id: 3 }));
      })
    );
    render(shelf);
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
    render("nothing.here");

    expect(await screen.findByText("This isn't here")).toBeInTheDocument();
  });
});

/**
 * A tool plug-in's row on its own page: its table's declared detail, then the
 * rows of each item table under it, read through the generic routes.
 */
import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildToolPlugin, buildToolRowRead, TOOL_PLUGIN_UID } from "@/__tests__/factories";
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

  it("says so where no installed tool has the kind", async () => {
    render("nothing.here");

    expect(await screen.findByText("This isn't here")).toBeInTheDocument();
  });
});

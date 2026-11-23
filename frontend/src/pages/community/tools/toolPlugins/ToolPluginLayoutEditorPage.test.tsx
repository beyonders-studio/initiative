/**
 * A tool plug-in's table's layouts, edited where its rows are listed: each
 * change stored under the table's kind in that place, and each put back as
 * its plug-in ships it.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { buildToolPlugin, buildToolRowRead, TOOL_PLUGIN_UID } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { ToolPluginLayoutEditorPage } from "./ToolPluginLayoutEditorPage";

const uid = TOOL_PLUGIN_UID.toLowerCase();
const book = `book.${uid}`;

/** The books' layouts under shelf 5: the grid as `grid` stores it (none: as
 *  shipped), and the book's page as shipped. */
const bookLayouts = (grid?: object) => ({
  can_configure: true,
  layouts: [
    {
      kind: "grid",
      is_default: true,
      hidden: false,
      definition: grid ?? {},
      updated_at: grid ? "2026-11-01T00:00:00Z" : null,
    },
    { kind: book, task_type_id: null, task_type_name: null, definition: {}, updated_at: null },
  ],
});

type Sent = { method: string; kind: string; target: string; body?: unknown };
let sent: Sent[] = [];

const targetOf = (request: Request) => {
  const params = new URL(request.url).searchParams;
  return `${params.get("tool")}:${params.get("tool_id")}`;
};

const render = () =>
  renderPage(ToolPluginLayoutEditorPage, {
    initialRoute: "/c/$communityId/i/$initiativeId/t/$kind/layouts/$parentId",
    routeParams: { communityId: "1", initiativeId: "3", kind: book, parentId: "5" },
  });

const outline = () => screen.findByRole("navigation", { name: /outline/i });

beforeEach(() => {
  sent = [];
  server.use(
    communityHttp.get("/plugins/", () => HttpResponse.json({ items: [buildToolPlugin()] })),
    communityHttp.get(`/plugin-tools/${book}/`, () =>
      HttpResponse.json({
        items: [
          buildToolRowRead({
            kind: book,
            id: 8,
            initiative_id: 3,
            parent_id: 5,
            name: "Middlemarch",
            fields: { pages: 800, read: 200 },
          }),
        ],
        total_count: 1,
        page: 1,
        page_size: 0,
        has_next: false,
        has_prev: false,
      })
    ),
    communityHttp.put("/layouts/", async ({ request }) => {
      const body = (await request.json()) as { kind: string; definition: object };
      sent.push({ method: "PUT", kind: body.kind, target: targetOf(request), body });
      return HttpResponse.json(bookLayouts(body.definition));
    }),
    communityHttp.delete("/layouts/:kind", ({ params, request }) => {
      sent.push({ method: "DELETE", kind: String(params.kind), target: targetOf(request) });
      return HttpResponse.json(bookLayouts());
    })
  );
});

describe("ToolPluginLayoutEditorPage", () => {
  it("takes a field off a list's card and stores it under the item table's kind", async () => {
    server.use(communityHttp.get("/layouts/", () => HttpResponse.json(bookLayouts())));
    const user = userEvent.setup();
    render();

    await user.click(within(await outline()).getByRole("button", { name: /hide read/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    const [save] = sent;
    expect(save.method).toBe("PUT");
    expect(save.target).toBe(`${book}:5`);
    expect(save.kind).toBe("grid");
    const card = JSON.stringify((save.body as { definition: { card: unknown } }).definition.card);
    expect(card).toContain('"name"');
    expect(card).not.toContain('"read"');
  });

  it("puts a changed list back as its plug-in ships it", async () => {
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          bookLayouts({
            card: { type: "card", children: [{ type: "field", props: { field: "name" } }] },
          })
        )
      )
    );
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByRole("button", { name: "Use the shipped layout" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ method: "DELETE", kind: "grid", target: `${book}:5` });
  });
});

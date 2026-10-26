/**
 * The shelf every card-grid tool is browsed from, asked once for all of them.
 *
 * Each tool used to carry its own copy of this page, so each would have needed
 * its own copy of these tests. The cases come from the page's own `TOOL_INDEX`:
 * add a tool with an entry and it is covered here the moment it exists.
 *
 * What only one tool's list takes — a queue's status, a file's type — is
 * asked of that tool alone, at the bottom. So is what only one tool configures
 * today (files dropped on the list, the reader's own order): the page does it
 * for any tool whose entry asks, and files and projects are the ones that do.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { buildNotificationPlace, buildProject, ownerCan, readerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import i18n from "@/__tests__/helpers/i18n-test";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { keepViewPreferences } from "@/__tests__/helpers/viewPreferences";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type ToolIndexEntry,
  ToolIndexPage,
  toolIndexEntry,
} from "@/components/tools/ToolIndexPage";
import { toolTableStorageKey } from "@/components/tools/ToolIndexTable";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import { queryClient } from "@/lib/queryClient";
import { setItem } from "@/lib/storage";
import { TOOLS, toolCamelPlural, toolRouteSegment, toolViews } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

const INITIATIVE_ID = 1;

/** Every tool this page serves, each with what it calls its own strings. */
const CASES = TOOLS.flatMap((tool) => {
  const entry = toolIndexEntry(tool);
  return entry ? [{ tool, entry }] : [];
});

/** The keys come from the table, so the loose signature the page itself uses. */
const translate = i18n.t.bind(i18n) as TranslateFn;

/** One of the tool's own strings, read through the key the table declares. */
const copy = (tool: Tool, key: keyof ToolIndexEntry["text"]) =>
  translate(toolIndexEntry(tool)?.text[key] ?? "", { ns: toolCamelPlural(tool) });

/** A string from the shared toolbar/panel chrome. */
const shared = (key: string) => translate(key, { ns: "common" });

/**
 * Fields a tool's card reads beyond the ones every row has. Written out rather
 * than generated: a card that starts reading a new field should fail here
 * loudly rather than render a blank.
 */
const CARD_FIELDS: Partial<Record<Tool, Record<string, unknown>>> = {
  file: {
    file_type: "native",
    featured_image_url: null,
    is_template: false,
    properties: [],
    file_content_type: null,
    original_filename: null,
    smart_link_url: null,
  },
  catalog: { cover: null, preview: [] },
  project: {
    icon: null,
    is_template: false,
    pinned_at: null,
    task_summary: { total: 0, completed: 0 },
  },
  queue: { current_round: 1, is_active: true },
};

const row = (tool: Tool, fields: { id: number; name: string; archived_at?: string | null }) => ({
  description: null,
  initiative_id: INITIATIVE_ID,
  community_id: 1,
  created_by: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  archived_at: null,
  can: ownerCan(),
  comments_enabled: false,
  comment_count: 0,
  tags: [],
  grants: [],
  ...CARD_FIELDS[tool],
  ...fields,
});

/**
 * Serve the tool's list endpoint, honouring what every tool's page can ask
 * for: which archive state, a search, and a page. Every request is kept, so a
 * test can read what the page sent.
 */
const stubList = (tool: Tool, rows: { name: string; archived_at?: string | null }[]) => {
  const requests: URLSearchParams[] = [];
  server.use(
    communityHttp.get(`/${toolRouteSegment(tool)}/`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const wantArchived = params.get("archived") === "true";
      const search = (params.get("search") ?? "").toLowerCase();
      const matching = rows.filter(
        (item) =>
          Boolean(item.archived_at) === wantArchived &&
          (!search || item.name.toLowerCase().includes(search))
      );
      const page = Number(params.get("page") ?? 1);
      const pageSize = Number(params.get("page_size") ?? 20);
      return HttpResponse.json({
        items: matching.slice((page - 1) * pageSize, page * pageSize),
        total_count: matching.length,
        page,
        page_size: pageSize,
        has_next: page * pageSize < matching.length,
      });
    })
  );
  return requests;
};

const renderIndex = (tool: Tool, routerSearch?: Record<string, unknown>) =>
  renderPage(() => <ToolIndexPage tool={tool} fixedInitiativeId={INITIATIVE_ID} canCreate />, {
    routerSearch,
  });

describe("the tool index page", () => {
  it.each(CASES)("$tool names its own empty shelf", async ({ tool }) => {
    stubList(tool, []);

    renderIndex(tool);

    expect(await screen.findByText(copy(tool, "emptyTitle"))).toBeInTheDocument();
    expect(screen.getByText(copy(tool, "emptyBody"))).toBeInTheDocument();
  });

  it.each(CASES)("$tool reaches its archived rows from the toolbar", async ({ tool }) => {
    const requests = stubList(tool, [
      row(tool, { id: 1, name: "Still in use" }),
      row(tool, { id: 2, name: "Put away", archived_at: "2026-02-01T00:00:00Z" }),
    ]);
    server.use(
      communityHttp.get(`/tools/${tool}/counts`, ({ request }) => {
        expect(new URL(request.url).searchParams.get("initiative_id")).toBe(`${INITIATIVE_ID}`);
        return HttpResponse.json({
          views: { active: 1, archived: 1 },
          tag_counts: {},
          untagged_count: 0,
        });
      })
    );

    renderIndex(tool);

    expect(await screen.findByText("Still in use")).toBeInTheDocument();
    expect(screen.queryByText("Put away")).not.toBeInTheDocument();

    const archived = screen.getByRole("radio", { name: shared("toolViewFilter.archived") });
    await waitFor(() => expect(archived).toHaveTextContent("1"));
    await userEvent.click(archived);

    expect(await screen.findByText("Put away")).toBeInTheDocument();
    await waitFor(() => expect(requests.at(-1)?.get("archived")).toBe("true"));
    // Nothing is made into the archive.
    expect(screen.queryByRole("button", { name: copy(tool, "create") })).not.toBeInTheDocument();
  });

  it.each(CASES)("$tool opens its filters from the toolbar", async ({ tool }) => {
    stubList(tool, []);

    renderIndex(tool);
    await screen.findByText(copy(tool, "emptyTitle"));

    const button = screen.getByRole("button", { name: shared("toolbar.filters") });
    expect(button).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(button);

    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it.each(CASES)(
    "$tool searches on the server, and says so when nothing matches",
    async ({ tool }) => {
      const requests = stubList(tool, [row(tool, { id: 1, name: "Findable" })]);

      renderIndex(tool);
      expect(await screen.findByText("Findable")).toBeInTheDocument();

      await userEvent.type(
        screen.getByLabelText(translate("filters.searchLabel", { ns: toolCamelPlural(tool) })),
        "nothing here"
      );

      // Not the empty shelf: the tool has rows, they are just not these.
      expect(await screen.findByText(copy(tool, "noMatches"))).toBeInTheDocument();
      expect(screen.queryByText(copy(tool, "emptyTitle"))).not.toBeInTheDocument();
      // Sent once, after the typing stopped, rather than once a keystroke.
      expect(requests.map((params) => params.get("search")).filter(Boolean)).toEqual([
        "nothing here",
      ]);
    }
  );

  it.each(CASES.filter(({ entry }) => !entry.CreateDialog))(
    "$tool is created from the shared dialog",
    async ({ tool }) => {
      stubList(tool, []);
      let sent: unknown;
      server.use(
        communityHttp.post(`/${toolRouteSegment(tool)}/`, async ({ request }) => {
          sent = await request.json();
          return HttpResponse.json(row(tool, { id: 9, name: "Fresh" }));
        })
      );

      renderIndex(tool);
      await userEvent.click(await screen.findByRole("button", { name: copy(tool, "create") }));

      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText(copy(tool, "createDescription"))).toBeInTheDocument();
      await userEvent.type(
        within(dialog).getByLabelText(translate("name", { ns: toolCamelPlural(tool) })),
        "Fresh"
      );
      await userEvent.click(within(dialog).getByRole("button", { name: copy(tool, "create") }));

      await waitFor(() =>
        expect(sent).toMatchObject({ name: "Fresh", initiative_id: INITIATIVE_ID })
      );
    }
  );

  it.each(CASES)("$tool asks for its list a page at a time", async ({ tool }) => {
    const requests = stubList(tool, [row(tool, { id: 1, name: "Paged" })]);

    renderIndex(tool);

    expect(await screen.findByText("Paged")).toBeInTheDocument();
    expect(requests.at(-1)?.get("page")).toBe("1");
    expect(requests.at(-1)?.get("page_size")).toBe("20");
    expect(
      screen.getByText(
        translate("pagination.rangeOf", { ns: "common", start: 1, end: 1, total: 1 })
      )
    ).toBeInTheDocument();
  });

  it.each(CASES)("$tool leaves a page past its end for its last one", async ({ tool }) => {
    const requests = stubList(tool, [row(tool, { id: 1, name: "Survivor" })]);

    // A link to page 3 of a list that now holds one row.
    renderIndex(tool, { page: 3 });

    expect(await screen.findByText("Survivor")).toBeInTheDocument();
    expect(requests.map((params) => params.get("page"))).toEqual(["3", "1"]);
  });

  it.each(CASES)("$tool opens a row at its own address", async ({ tool }) => {
    stubList(tool, [row(tool, { id: 7, name: "Openable" })]);

    renderIndex(tool);

    const link = (await screen.findByText("Openable")).closest("a");
    expect(link).toHaveAttribute("href", `/c/1/i/${INITIATIVE_ID}/${toolRouteSegment(tool)}/7`);
  });

  it.each(CASES)("$tool marks the row with something unread", async ({ tool }) => {
    stubList(tool, [
      row(tool, { id: 7, name: "Talked about" }),
      row(tool, { id: 8, name: "Quiet" }),
    ]);
    server.use(
      http.get("/api/v1/notifications/unread", () =>
        HttpResponse.json({ places: [buildNotificationPlace({ tool, resource_id: 7 })] })
      )
    );

    renderIndex(tool);

    await screen.findByText("Quiet");
    const dot = await screen.findByRole("img", { name: translate("communities:unreadHere") });
    expect(screen.getAllByRole("img", { name: translate("communities:unreadHere") })).toHaveLength(
      1
    );
    expect(dot.parentElement).toHaveTextContent("Talked about");
  });
});

describe("the tool index page's property filter", () => {
  it("offers only the properties of the initiative the list is in", async () => {
    stubList(Tool.queue, [row(Tool.queue, { id: 1, name: "Running" })]);
    const asked: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/property-definitions/", ({ request }) => {
        asked.push(new URL(request.url).searchParams);
        return HttpResponse.json([]);
      })
    );

    renderIndex(Tool.queue);
    await screen.findByText("Running");
    await userEvent.click(screen.getByRole("button", { name: shared("toolbar.filters") }));

    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    expect(asked.map((params) => params.get("initiative_id"))).toEqual(
      asked.map(() => String(INITIATIVE_ID))
    );
  });
});

describe("the queue index page", () => {
  it("sends the status filter as is_active", async () => {
    const requests = stubList(Tool.queue, [row(Tool.queue, { id: 1, name: "Running" })]);
    const pick = async (label: string) => {
      await userEvent.click(
        screen.getByRole("combobox", { name: translate("filters.status", { ns: "queues" }) })
      );
      await userEvent.click(
        await screen.findByRole("option", { name: translate(label, { ns: "queues" }) })
      );
    };

    renderIndex(Tool.queue);
    await screen.findByText("Running");
    await userEvent.click(screen.getByRole("button", { name: shared("toolbar.filters") }));

    await pick("filters.inactiveOnly");
    await waitFor(() => expect(requests.at(-1)?.get("is_active")).toBe("false"));
    await pick("filters.activeOnly");
    await waitFor(() => expect(requests.at(-1)?.get("is_active")).toBe("true"));
    await pick("filters.allStatuses");
    await waitFor(() => expect(requests.at(-1)?.has("is_active")).toBe(false));
  });
});

describe("the catalog index page", () => {
  it("draws the newest four pictures of a catalog nobody chose a cover for", async () => {
    const preview = [1, 2, 3, 4].map((id) => ({
      item_id: id,
      file_url: `/uploads/picture-${id}.png`,
      thumbnail_url: null,
      width: null,
      height: null,
    }));
    // The list carries the pictures only when it is asked for them.
    server.use(
      communityHttp.get(`/${toolRouteSegment(Tool.catalog)}/`, ({ request }) => {
        const asked = new URL(request.url).searchParams.get("include_preview") === "true";
        return HttpResponse.json({
          items: [
            {
              ...row(Tool.catalog, { id: 1, name: "Store assets" }),
              preview: asked ? preview : [],
            },
          ],
          total_count: 1,
          page: 1,
          page_size: 100,
          has_next: false,
        });
      })
    );

    const { container } = renderIndex(Tool.catalog);
    await screen.findByText("Store assets");

    await waitFor(() =>
      expect(
        Array.from(container.querySelectorAll("img"), (img) => img.getAttribute("src"))
      ).toEqual(preview.map((picture) => expect.stringContaining(picture.file_url)))
    );
  });
});

describe("the tool index page's templates", () => {
  it.each(CASES.filter(({ tool }) => toolViews(tool).includes("templates")))(
    "$tool keeps its templates in a view of their own, with nothing to create there",
    async ({ tool }) => {
      const requests = stubList(tool, []);

      renderIndex(tool);
      await screen.findByText(copy(tool, "emptyTitle"));
      expect(requests.at(-1)?.get("is_template")).toBe("false");

      await userEvent.click(
        screen.getByRole("radio", { name: shared("toolViewFilter.templates") })
      );

      await waitFor(() => expect(requests.at(-1)?.get("is_template")).toBe("true"));
      expect(await screen.findByText(shared("toolIndex.emptyTemplatesTitle"))).toBeInTheDocument();
      expect(
        screen.queryByRole("button", {
          name: translate("createFirst", { ns: toolCamelPlural(tool) }),
        })
      ).not.toBeInTheDocument();
    }
  );
});

describe("the tool index page's bulk actions", () => {
  const select = async (name: string) => {
    await userEvent.click(screen.getByRole("button", { name: shared("toolbar.moreActions") }));
    await userEvent.click(
      await screen.findByRole("menuitem", { name: shared("toolbar.selectItems") })
    );
    await userEvent.click(await screen.findByRole("button", { name, pressed: false }));
  };

  it("duplicates and deletes a selection through the tool's own routes", async () => {
    stubList(Tool.queue, [
      row(Tool.queue, { id: 4, name: "Standup" }),
      row(Tool.queue, { id: 5, name: "Retro" }),
    ]);
    const duplicated: string[] = [];
    const deleted: string[] = [];
    server.use(
      communityHttp.post("/queues/:id/duplicate", ({ params }) => {
        duplicated.push(String(params.id));
        return HttpResponse.json({ id: 40, initiative_id: INITIATIVE_ID });
      }),
      communityHttp.delete("/queues/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      })
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderIndex(Tool.queue);
    await screen.findByText("Standup");

    await select("Standup");
    await userEvent.click(screen.getByRole("button", { name: shared("bulkActions.duplicate") }));
    await waitFor(() => expect(duplicated).toEqual(["4"]));

    await select("Retro");
    await userEvent.click(screen.getByRole("button", { name: shared("delete") }));
    await waitFor(() => expect(deleted).toEqual(["5"]));
  });

  it("refuses sharing on an archived selection, and says why", async () => {
    stubList(Tool.project, [
      buildProject({
        name: "Planescape Detour",
        // What an archived project arrives as: nothing on it may be changed
        // but taking it back out.
        can: { ...readerCan({ unarchive: true }), configure: false },
        archived_at: "2026-06-01T00:00:00.000Z",
      }),
    ]);

    renderIndex(Tool.project, { status: "archived" });
    await screen.findByText("Planescape Detour");
    await select("Planescape Detour");

    const editAccess = screen.getByRole("button", { name: translate("access:bulkBar.editAccess") });
    expect(editAccess).toBeDisabled();
    expect(editAccess).toHaveAttribute("title", translate("access:bulkBar.archived"));
  });

  it("copies templates it can only read, and refreshes the list when part of a batch fails", async () => {
    const readOnly = { ...ownerCan(), edit: false, delete: false };
    const templates = [
      {
        ...row(Tool.file, { id: 6, name: "Brief template" }),
        is_template: true,
        can: readOnly,
      },
      { ...row(Tool.file, { id: 7, name: "Memo template" }), is_template: true, can: readOnly },
    ];
    const requests = stubList(Tool.file, templates);
    server.use(
      communityHttp.post("/files/:id/duplicate", ({ params }) =>
        params.id === "6"
          ? HttpResponse.json({ id: 60, initiative_id: INITIATIVE_ID })
          : new HttpResponse(null, { status: 500 })
      )
    );

    // The app's own client, which the bulk action's refresh reaches.
    renderPage(
      () => <ToolIndexPage tool={Tool.file} fixedInitiativeId={INITIATIVE_ID} canCreate />,
      { routerSearch: { status: "templates" }, queryClient }
    );
    onTestFinished(() => queryClient.clear());
    await screen.findByText("Brief template");
    await select("Brief template");
    await userEvent.click(
      await screen.findByRole("button", { name: "Memo template", pressed: false })
    );

    const listed = requests.length;
    const duplicate = screen.getByRole("button", { name: shared("bulkActions.duplicate") });
    expect(duplicate).toBeEnabled();
    await userEvent.click(duplicate);
    // The copy that landed is real: the list is read again despite the failure.
    await waitFor(() => expect(requests.length).toBeGreaterThan(listed));
  });
});

describe("the file index page", () => {
  const files = (key: string) => translate(key, { ns: "files" });

  /** Rendered in the layout a reader left the list in. */
  const renderIn = (
    layout: "grid" | "list" | "tags",
    canCreate = true,
    kept: Record<string, unknown> = {}
  ) => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
      items: { [`${Tool.file}:view-mode`]: layout, ...kept },
    });
    return renderPage(
      () => (
        <ToolIndexPage tool={Tool.file} fixedInitiativeId={INITIATIVE_ID} canCreate={canCreate} />
      ),
      { queryClient }
    );
  };

  it("narrows by type within the view being shown", async () => {
    const requests = stubList(Tool.file, []);

    renderIndex(Tool.file);
    await screen.findByText(copy(Tool.file, "emptyTitle"));
    expect(requests.at(-1)?.get("file_type")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: shared("toolbar.filters") }));
    await userEvent.click(screen.getByRole("combobox", { name: files("filters.type") }));
    await userEvent.click(
      await screen.findByRole("option", { name: files("filters.types.whiteboard") })
    );

    await waitFor(() => expect(requests.at(-1)?.get("file_type")).toBe("whiteboard"));
    expect(requests.at(-1)?.get("is_template")).toBe("false");
  });

  it("is made from a dialog of its own", async () => {
    stubList(Tool.file, []);

    renderIndex(Tool.file);
    await userEvent.click(await screen.findByRole("button", { name: copy(Tool.file, "create") }));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("tab", { name: files("create.tabUpload") })
    ).toBeInTheDocument();
  });

  it("opens its table newest first, and remembers another order for the next visit", async () => {
    const requests = stubList(Tool.file, [row(Tool.file, { id: 1, name: "Brief" })]);
    const kept = keepViewPreferences();

    const first = renderIn("list");
    await screen.findByText("Brief");
    expect(requests.at(-1)?.get("sort_by")).toBe("updated_at");
    expect(requests.at(-1)?.get("sort_dir")).toBe("desc");

    await userEvent.click(screen.getByRole("button", { name: shared("name") }));
    await waitFor(() => expect(requests.at(-1)?.get("sort_by")).toBe("name"));
    expect(requests.at(-1)?.get("sort_dir")).toBe("asc");

    // It is kept for the reader, on any device.
    first.unmount();
    await waitFor(() => expect(Object.keys(kept)).toHaveLength(1));
    requests.length = 0;
    renderIn("list", true, kept);
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(requests.at(-1)?.get("sort_by")).toBe("name");
    expect(requests.at(-1)?.get("sort_dir")).toBe("asc");
  });

  describe("file drop", () => {
    const brief = () => new File(["%PDF"], "site-brief.pdf", { type: "application/pdf" });
    const drag = (files: File[]) => ({ dataTransfer: { types: ["Files"], files } });

    it.each(["tags", "grid", "list"] as const)(
      "opens an upload holding a file dropped on the %s layout",
      async (layout) => {
        stubList(Tool.file, [row(Tool.file, { id: 1, name: "Existing" })]);

        const { container } = renderIn(layout);
        await screen.findByText("Existing");
        const root = container.querySelector(".relative.space-y-6") as HTMLElement;
        fireEvent.dragEnter(root, drag([]));
        expect(screen.getByText(files("dropToUpload"))).toBeInTheDocument();
        fireEvent.drop(root, drag([brief()]));

        const dialog = await screen.findByRole("dialog");
        expect(
          within(dialog).getByRole("tab", { name: files("create.tabUpload") })
        ).toHaveAttribute("aria-selected", "true");
        expect(within(dialog).getByText("site-brief.pdf")).toBeInTheDocument();
        expect(within(dialog).getByLabelText(files("create.titleLabel"))).toHaveValue("site-brief");
      }
    );

    it("takes no drop from somebody who may not create files", async () => {
      stubList(Tool.file, [row(Tool.file, { id: 1, name: "Existing" })]);

      const { container } = renderIn("list", false);
      await screen.findByText("Existing");
      const root = container.querySelector(".relative.space-y-6") as HTMLElement;
      fireEvent.dragEnter(root, drag([]));
      expect(screen.queryByText(files("dropToUpload"))).not.toBeInTheDocument();
      fireEvent.drop(root, drag([brief()]));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});

describe("the project index page", () => {
  const handles = () =>
    screen.queryAllByRole("button", { name: translate("projects:preview.reorder") });

  it("lists in the reader's own order, and offers the live cards to drag", async () => {
    const requests = stubList(Tool.project, [
      buildProject({ name: "Barovia Arc" }),
      buildProject({ name: "Planescape Detour", archived_at: "2026-06-01T00:00:00.000Z" }),
    ]);

    renderIndex(Tool.project);
    await screen.findByText("Barovia Arc");

    // Asked for no order, the server lists in the reader's own.
    expect(requests.at(-1)?.has("sort_by")).toBe(false);
    expect(handles()).toHaveLength(1);

    // A search narrows the list, and a cleared one still does until the full
    // list is back: a drop would send only the narrowed rows.
    const search = screen.getByLabelText(translate("projects:filters.searchLabel"));
    await userEvent.type(search, "Barovia");
    await waitFor(() => expect(requests.at(-1)?.get("search")).toBe("Barovia"));
    expect(handles()).toHaveLength(0);
    await userEvent.clear(search);
    expect(handles()).toHaveLength(0);
    await waitFor(() => expect(handles()).toHaveLength(1));

    await userEvent.click(screen.getByRole("radio", { name: shared("toolViewFilter.archived") }));
    expect(await screen.findByText("Planescape Detour")).toBeInTheDocument();
    expect(handles()).toHaveLength(0);
  });

  it("is made from a dialog of its own, in the initiative it is listed in", async () => {
    stubList(Tool.project, []);
    let sent: unknown;
    server.use(
      communityHttp.post("/projects/", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(buildProject({ id: 9, name: "Fresh" }));
      })
    );

    renderIndex(Tool.project);
    await userEvent.click(
      await screen.findByRole("button", { name: translate("projects:addProject") })
    );

    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(translate("common:name")), "Fresh");
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: translate("projects:createDialog.createProject"),
      })
    );

    await waitFor(() =>
      expect(sent).toMatchObject({ name: "Fresh", initiative_id: INITIATIVE_ID })
    );
  });

  it("drags nothing once the reader picks an order in the table", async () => {
    setItem(
      toolTableStorageKey(Tool.project, "order"),
      JSON.stringify({ grouping: [], sorting: [{ id: "name", desc: false }] })
    );
    const requests = stubList(Tool.project, [buildProject({ name: "Barovia Arc" })]);

    renderIndex(Tool.project);
    await screen.findByText("Barovia Arc");

    // The order this device kept carries over into the reader's view.
    await waitFor(() => expect(requests.at(-1)?.get("sort_by")).toBe("name"));
    expect(handles()).toHaveLength(0);
  });
});

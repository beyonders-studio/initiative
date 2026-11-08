import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildOwnedDecoration,
  buildProject,
  buildProjectTaskStatus,
  buildTask,
  buildWiki,
} from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { keepViewPreferences } from "@/__tests__/helpers/viewPreferences";
import type { PersonalItemRead } from "@/api/generated/initiativeAPI.schemas";
import { type HomeLayout, readingOrder } from "@/lib/home/layout";
import { HOME_VIEWS_KEY, type HomeViews, homeViewKey, MAIN_VIEW_ID } from "@/lib/home/views";

import { HomePage } from "./HomePage";

/** Every `/me/tasks` read answers with nothing, so the task widgets settle. */
function stubNoTasks() {
  server.use(
    http.get("/api/v1/me/tasks", () =>
      HttpResponse.json({ items: [], total_count: 0, page: 1, page_size: 20, has_next: false })
    )
  );
}

const MAIN = homeViewKey(MAIN_VIEW_ID);

/** A server keeping the reader's preferences, starting from this layout of
 *  their one view. */
function keepLayout(layout?: HomeLayout) {
  const kept = keepViewPreferences();
  if (layout) kept[MAIN] = layout;
  return kept;
}

const comingUpAndCommunities: HomeLayout = {
  version: 1,
  widgets: [
    { id: "comingUp", type: "comingUp", grid: { x: 0, y: 0, w: 4, h: 8 } },
    { id: "communities", type: "communities", grid: { x: 4, y: 0, w: 8, h: 6 } },
  ],
};

const renderHome = () => renderPage(HomePage, { queryClient: createTestQueryClient() });

const keptLayout = (kept: Record<string, unknown>, key = MAIN) => kept[key] as HomeLayout;
const keptViews = (kept: Record<string, unknown>) => kept[HOME_VIEWS_KEY] as HomeViews;

describe("HomePage", () => {
  it("opens as My Tasks did for somebody who never arranged it, and saves nothing", async () => {
    stubNoTasks();
    const kept = keepLayout();
    renderHome();

    expect(await screen.findByRole("heading", { name: /^good|burning/i })).toBeInTheDocument();
    expect(await screen.findByText("Focus")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "My Tasks" })).toBeInTheDocument();
    expect(kept[MAIN]).toBeUndefined();
    expect(kept[HOME_VIEWS_KEY]).toBeUndefined();
    // One view and nothing being customized: no tabs.
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("folds the focus card away in the stack a narrow screen shows, and keeps it folded", async () => {
    const user = userEvent.setup();
    stubNoTasks();
    const kept = keepLayout();
    renderHome();

    // Stacked, nothing sizes the card, so it folds as it did on My Tasks.
    const toggle = await screen.findByRole("button", { name: "Focus" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(kept["my-tasks:focus"]).toMatchObject({ open: false }));
  });

  it("adds a widget while customizing, and keeps it for next time", async () => {
    const user = userEvent.setup();
    const kept = keepLayout(comingUpAndCommunities);
    const first = renderHome();

    await user.click(await screen.findByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    const picker = await screen.findByRole("dialog", { name: "Add a widget" });
    // Coming up may appear more than once; My communities only once.
    expect(within(picker).getByRole("button", { name: /my communities/i })).toBeDisabled();
    await user.click(within(picker).getByRole("button", { name: /^coming up/i }));

    await waitFor(() => expect(keptLayout(kept)?.widgets.map((w) => w.id)).toContain("comingUp-2"));

    first.unmount();
    renderHome();
    expect(await screen.findAllByRole("heading", { name: "Coming up" })).toHaveLength(2);
  });

  it("moves and removes widgets in the stack a narrow screen shows", async () => {
    const user = userEvent.setup();
    const kept = keepLayout(comingUpAndCommunities);
    renderHome();

    await user.click(await screen.findByRole("button", { name: "Customize" }));
    expect(screen.getByRole("button", { name: "Move Coming up up" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Move Coming up down" }));
    await waitFor(() =>
      expect(readingOrder(keptLayout(kept)?.widgets ?? []).map((w) => w.id)).toEqual([
        "communities",
        "comingUp",
      ])
    );

    await user.click(screen.getByRole("button", { name: "Remove My communities" }));
    await waitFor(() => expect(keptLayout(kept)?.widgets.map((w) => w.id)).toEqual(["comingUp"]));
  });

  it("makes a new view from a layout, beside the one the reader arranged", async () => {
    const user = userEvent.setup();
    stubNoTasks();
    const kept = keepLayout(comingUpAndCommunities);
    renderHome();

    await user.click(await screen.findByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "New view" }));
    const picker = await screen.findByRole("dialog", { name: "New view" });
    await user.click(within(picker).getByRole("button", { name: /assigned work/i }));

    await waitFor(() => expect(keptViews(kept)?.views).toHaveLength(2));
    const [home, added] = keptViews(kept).views;
    expect(home).toEqual({ id: MAIN_VIEW_ID, name: "Home" });
    expect(added.name).toBe("Assigned work");
    expect(keptViews(kept).current).toBe(added.id);
    expect(keptLayout(kept, homeViewKey(added.id)).widgets.map((w) => w.type)).toEqual([
      "tasks",
      "focus",
      "activity",
    ]);
    // Nothing of the page they had is lost.
    expect(keptLayout(kept)).toEqual(comingUpAndCommunities);
    expect(screen.getByRole("tab", { name: "Assigned work" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("opens the view the reader had last, and switches between them", async () => {
    const user = userEvent.setup();
    const kept = keepLayout(comingUpAndCommunities);
    kept[HOME_VIEWS_KEY] = {
      version: 1,
      views: [
        { id: MAIN_VIEW_ID, name: "Work" },
        { id: "league", name: "League" },
      ],
      current: "league",
    } satisfies HomeViews;
    kept[homeViewKey("league")] = {
      version: 1,
      widgets: [{ id: "clock", type: "clock", grid: { x: 0, y: 0, w: 4, h: 4 } }],
    } satisfies HomeLayout;
    renderHome();

    expect(await screen.findByRole("tab", { name: "League" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(screen.getByRole("heading", { name: "Clock" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Coming up" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Work" }));
    expect(await screen.findByRole("heading", { name: "Coming up" })).toBeInTheDocument();
    await waitFor(() => expect(keptViews(kept).current).toBe(MAIN_VIEW_ID));
  });

  it("renames and deletes a view", async () => {
    const user = userEvent.setup();
    const kept = keepLayout(comingUpAndCommunities);
    kept[HOME_VIEWS_KEY] = {
      version: 1,
      views: [
        { id: MAIN_VIEW_ID, name: "Home" },
        { id: "league", name: "League" },
      ],
      current: "league",
    } satisfies HomeViews;
    kept[homeViewKey("league")] = { version: 1, widgets: [] } satisfies HomeLayout;
    renderHome();

    await user.click(await screen.findByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Options for League" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Rec league{Enter}");
    await waitFor(() =>
      expect(keptViews(kept).views.find((view) => view.id === "league")?.name).toBe("Rec league")
    );

    await user.click(screen.getByRole("button", { name: "Options for Rec league" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete view" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Delete “Rec league”?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(keptViews(kept).views).toEqual([{ id: MAIN_VIEW_ID, name: "Home" }])
    );
    expect(kept[homeViewKey("league")]).toBeNull();
    // Back on the one that is left.
    expect(await screen.findByRole("heading", { name: "Coming up" })).toBeInTheDocument();
  });

  it("fills an empty view from a layout without making another", async () => {
    const user = userEvent.setup();
    stubNoTasks();
    const kept = keepLayout({ version: 1, widgets: [] });
    renderHome();

    expect(await screen.findByText("Your home page is empty")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start from a layout" }));
    const picker = await screen.findByRole("dialog", { name: "Start from a layout" });
    expect(within(picker).queryByRole("button", { name: /blank/i })).not.toBeInTheDocument();
    await user.click(within(picker).getByRole("button", { name: /my day/i }));

    await waitFor(() => expect(keptLayout(kept)?.preset).toBe("myDay"));
    expect(kept[HOME_VIEWS_KEY]).toBeUndefined();
  });

  it("shows the reader's communities as their directory cards", async () => {
    keepLayout(comingUpAndCommunities);
    renderHome();

    const widget = (await screen.findByRole("heading", { name: "My communities" })).closest(
      "div.rounded-xl"
    ) as HTMLElement;
    // Already in it, so the card opens it rather than joining.
    expect(await within(widget).findAllByRole("button", { name: "Open" })).not.toHaveLength(0);
  });

  it("runs a timer that is still running after a reload", async () => {
    const user = userEvent.setup();
    const kept = keepLayout({
      version: 1,
      widgets: [{ id: "clock", type: "clock", grid: { x: 0, y: 0, w: 4, h: 4 } }],
    });
    renderHome();

    await user.click(await screen.findByRole("radio", { name: "Timer" }));
    await user.click(await screen.findByRole("button", { name: "5 min" }));
    expect(screen.getByRole("button", { name: /timer set to 05:00/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start" }));
    expect(screen.getByRole("timer")).toHaveTextContent(/0[45]:\d\d/);

    await waitFor(() =>
      expect(keptLayout(kept).widgets[0].options).toMatchObject({
        mode: "timer",
        timer: { duration: 300, endsAt: expect.any(Number) },
      })
    );

    await user.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() =>
      expect(keptLayout(kept).widgets[0].options).toMatchObject({
        timer: { duration: 300, left: expect.any(Number) },
      })
    );
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("takes a timer's length typed onto its face, and keeps it muted", async () => {
    const user = userEvent.setup();
    const kept = keepLayout({
      version: 1,
      widgets: [
        {
          id: "clock",
          type: "clock",
          grid: { x: 0, y: 0, w: 4, h: 4 },
          options: { mode: "timer" },
        },
      ],
    });
    renderHome();

    await user.click(await screen.findByRole("button", { name: /timer set to 25:00/i }));
    const field = screen.getByRole("textbox", { name: /type a length/i });
    await user.clear(field);
    await user.type(field, "7:30{Enter}");
    await waitFor(() =>
      expect(keptLayout(kept).widgets[0].options).toMatchObject({ timer: { duration: 450 } })
    );
    expect(screen.getByRole("button", { name: /timer set to 07:30/i })).toBeInTheDocument();

    // Something that is not a length leaves it as it was.
    await user.click(screen.getByRole("button", { name: /timer set to 07:30/i }));
    await user.clear(screen.getByRole("textbox", { name: /type a length/i }));
    await user.type(screen.getByRole("textbox", { name: /type a length/i }), "soon{Enter}");
    expect(screen.getByRole("button", { name: /timer set to 07:30/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Mute the timer" }));
    await waitFor(() => expect(keptLayout(kept).widgets[0].options).toMatchObject({ muted: true }));
    const unmute = screen.getByRole("button", { name: "Turn the timer's sound on" });
    expect(unmute).toHaveAttribute("aria-pressed", "true");
    await user.click(unmute);
    await waitFor(() => expect(keptLayout(kept).widgets[0].options).not.toHaveProperty("muted"));
  });

  it("walks a new arrival through getting started, and goes when asked", async () => {
    const user = userEvent.setup();
    stubNoTasks();
    const kept = keepLayout({
      version: 1,
      preset: "community",
      widgets: [
        {
          id: "gettingStarted",
          type: "gettingStarted",
          grid: { x: 0, y: 0, w: 12, h: 5 },
          options: { path: "join" },
        },
      ],
    });
    renderHome();

    const card = (await screen.findByRole("heading", { name: "Getting started" })).closest(
      "div.rounded-xl"
    ) as HTMLElement;
    // Already in a community; not yet anything else.
    const steps = within(card)
      .getAllByRole("listitem")
      .map((step) => step.querySelector("p")?.textContent);
    expect(steps).toContain("Join a community (done)");
    expect(steps).toContain("Add a task of your own");
    // Joined one, so nobody asks them to invite people to it.
    expect(steps).not.toContain("Invite your people");

    // Customizing from the card is customizing the page.
    await user.click(within(card).getByRole("button", { name: "Customize" }));
    expect(screen.getByRole("button", { name: "Add widget" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));

    await user.click(within(card).getByRole("button", { name: "Hide getting started" }));
    await waitFor(() => expect(keptLayout(kept).widgets).toEqual([]));
  });

  it("lets Yonder sit the greeting out", async () => {
    const user = userEvent.setup();
    stubNoTasks();
    const kept = keepLayout({
      version: 1,
      widgets: [{ id: "greeting", type: "greeting", grid: { x: 0, y: 0, w: 12, h: 2 } }],
    });
    const { container } = renderHome();

    await screen.findByRole("heading", { level: 2 });
    expect(container.querySelector("section img")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Greeting settings" }));
    await user.click(await screen.findByRole("switch", { name: "Show Yonder" }));

    await waitFor(() => expect(keptLayout(kept).widgets[0].options).toEqual({ yonder: false }));
    expect(container.querySelector("section img")).toBeNull();
  });

  it("adds a first task to the reader's list from an empty tasks widget", async () => {
    const user = userEvent.setup();
    stubNoTasks();
    const created: unknown[] = [];
    server.use(
      http.post("/api/v1/c/:communityId/tasks/", async ({ params, request }) => {
        created.push({ community: params.communityId, body: await request.json() });
        return HttpResponse.json({ id: 1 });
      }),
      // The list's name is read from the list, not kept with the widget.
      http.get("/api/v1/c/:communityId/projects/:projectId", () =>
        HttpResponse.json(buildProject({ id: 9, name: "To do" }))
      )
    );
    keepLayout({
      version: 1,
      widgets: [
        {
          id: "tasks",
          type: "tasks",
          grid: { x: 0, y: 0, w: 12, h: 10 },
          options: { addTo: { communityId: 4, initiativeId: 2, projectId: 9 } },
        },
      ],
    });
    renderHome();

    expect(await screen.findByText(/nothing is assigned to you yet/i)).toBeInTheDocument();
    await user.type(
      await screen.findByRole("textbox", { name: "Add a task to To do…" }),
      "Book the hall{Enter}"
    );

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      community: "4",
      body: { title: "Book the hall", project_id: 9, assignee_ids: [expect.any(Number)] },
    });
  });

  it("shows My Calendar as a widget, with its filters in the card", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/me/calendar-entries", () =>
        HttpResponse.json({ events: [], tasks: [], task_occurrences: [], projects: [], polls: [] })
      ),
      http.get("/api/v1/me/calendars", () =>
        HttpResponse.json({ items: [], total_count: 0, page: 1, page_size: 100, has_next: false })
      )
    );
    keepLayout({
      version: 1,
      widgets: [{ id: "calendar", type: "calendar", grid: { x: 0, y: 0, w: 12, h: 11 } }],
    });
    renderHome();

    const title = await screen.findByRole("link", { name: "My calendar" });
    expect(title).toHaveAttribute("href", "/my-calendar");
    const card = title.closest("div.rounded-xl") as HTMLElement;
    await user.click(within(card).getByRole("button", { name: /filter/i }));
    expect(await within(card).findByText("Filter by community")).toBeInTheDocument();
  });

  it("lists what the reader opened lately, each linking back into its community", async () => {
    server.use(
      http.get("/api/v1/me/personal-items", () =>
        HttpResponse.json([
          {
            entity_type: "project",
            entity_id: 5,
            community_id: 3,
            initiative_id: 2,
            name: "Fete stalls",
            viewed_at: new Date().toISOString(),
            icon: "🎪",
            file_type: null,
            mime_type: null,
            original_filename: null,
          },
        ])
      )
    );
    keepLayout({
      version: 1,
      widgets: [{ id: "recent", type: "recent", grid: { x: 0, y: 0, w: 4, h: 6 } }],
    });
    renderHome();

    expect(await screen.findByRole("link", { name: /fete stalls/i })).toHaveAttribute(
      "href",
      "/c/3/i/2/projects/5"
    );
  });

  it("shows what changed lately across every kind of tool, newest first, until narrowed", async () => {
    const user = userEvent.setup();
    const page = (items: unknown[]) =>
      HttpResponse.json({
        items,
        total_count: items.length,
        page: 1,
        page_size: 8,
        has_next: false,
      });
    const asked: string[] = [];
    server.use(
      http.get("/api/v1/me/tools/counts", () =>
        HttpResponse.json({
          counts: { project: 1, wiki: 1, file: 0, counter_group: 0, calendar: 0, dashboard: 0 },
        })
      ),
      http.get("/api/v1/me/projects", () => {
        asked.push("projects");
        return page([
          buildProject({
            id: 5,
            name: "Older project",
            community_id: 3,
            updated_at: "2026-10-01T00:00:00Z",
          }),
        ]);
      }),
      http.get("/api/v1/me/wikis", () => {
        asked.push("wikis");
        return page([
          buildWiki({
            id: 7,
            name: "Newer wiki",
            community_id: 3,
            updated_at: "2026-10-10T00:00:00Z",
          }),
        ]);
      }),
      http.get("/api/v1/me/files", () => {
        asked.push("files");
        return page([]);
      })
    );
    const kept = keepLayout({
      version: 1,
      widgets: [
        {
          id: "recent",
          type: "recent",
          grid: { x: 0, y: 0, w: 4, h: 6 },
          options: { mode: "changed" },
        },
      ],
    });
    renderHome();

    expect(await screen.findByRole("heading", { name: "Recently changed" })).toBeInTheDocument();
    await screen.findByRole("link", { name: /older project/i });
    const names = screen
      .getAllByRole("link")
      .map((link) => link.textContent ?? "")
      .filter((text) => /older project|newer wiki/i.test(text));
    expect(names[0]).toMatch(/newer wiki/i);
    expect(names[1]).toMatch(/older project/i);
    // Nobody asks for the files the reader has none of.
    expect(asked).not.toContain("files");

    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Recent settings" }));
    await user.click(await screen.findByRole("combobox", { name: "Tools" }));
    await user.click(await screen.findByRole("option", { name: "Projects" }));
    await waitFor(() =>
      expect(keptLayout(kept).widgets[0].options).toEqual({ mode: "changed", tools: ["project"] })
    );
  });

  it("lists what the reader bookmarked in every community, and takes a bookmark off", async () => {
    const user = userEvent.setup();
    const bookmarked = (
      over: Pick<PersonalItemRead, "entity_type" | "entity_id" | "name"> & Partial<PersonalItemRead>
    ): PersonalItemRead => ({
      community_id: 3,
      initiative_id: 2,
      viewed_at: null,
      bookmarked_at: "2026-10-10T00:00:00Z",
      icon: null,
      file_type: null,
      mime_type: null,
      original_filename: null,
      ...over,
    });
    let bookmarks = [
      bookmarked({ entity_type: "counter_group", entity_id: 7, name: "Raffle tickets" }),
      bookmarked({ entity_type: "project", entity_id: 5, name: "Fete stalls", icon: "🎪" }),
    ];
    const removed: string[] = [];
    server.use(
      http.get("/api/v1/me/personal-items", () => HttpResponse.json(bookmarks)),
      http.delete("/api/v1/c/:communityId/personal-items/bookmark/:tool/:id", ({ params }) => {
        removed.push(`${params.communityId}/${params.tool}/${params.id}`);
        bookmarks = bookmarks.filter((item) => item.entity_type !== params.tool);
        return new HttpResponse(null, { status: 204 });
      })
    );
    const kept = keepLayout({
      version: 1,
      widgets: [{ id: "bookmarks", type: "bookmarks", grid: { x: 0, y: 0, w: 4, h: 6 } }],
    });
    renderHome();

    expect(await screen.findByRole("link", { name: /fete stalls/i })).toHaveAttribute(
      "href",
      "/c/3/i/2/projects/5"
    );
    expect(screen.getByRole("link", { name: /raffle tickets/i })).toHaveAttribute(
      "href",
      "/c/3/i/2/counter-groups/7"
    );

    const [first] = screen.getAllByRole("button", { name: "Remove bookmark" });
    await user.click(first);
    await waitFor(() => expect(removed).toEqual(["3/counter_group/7"]));
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: /raffle tickets/i })).not.toBeInTheDocument()
    );

    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Bookmarks settings" }));
    await user.click(await screen.findByRole("combobox", { name: "Tools" }));
    await user.click(await screen.findByRole("option", { name: "Counters" }));
    await waitFor(() =>
      expect(keptLayout(kept).widgets[0].options).toEqual({ tools: ["counter_group"] })
    );
    await user.keyboard("{Escape}");
    await user.keyboard("{Escape}");
    expect(await screen.findByRole("heading", { name: "Bookmarked Counters" })).toBeInTheDocument();
    expect(await screen.findByText(/nothing bookmarked yet/i)).toBeInTheDocument();
  });

  it("says the recent list could not load when a list it asked for failed", async () => {
    server.use(
      http.get("/api/v1/me/tools/counts", () =>
        HttpResponse.json({
          counts: { project: 1, file: 0, counter_group: 0, calendar: 0, dashboard: 0 },
        })
      ),
      http.get("/api/v1/me/projects", () => new HttpResponse(null, { status: 500 }))
    );
    keepLayout({
      version: 1,
      widgets: [
        {
          id: "recent",
          type: "recent",
          grid: { x: 0, y: 0, w: 4, h: 6 },
          options: { mode: "changed", tools: ["project"] },
        },
      ],
    });
    renderHome();

    expect(await screen.findByText("Couldn't load what's recent.")).toBeInTheDocument();
    expect(screen.queryByText("Nothing has changed lately.")).not.toBeInTheDocument();
  });

  it("holds a task in every widget while one of them is saving it", async () => {
    const user = userEvent.setup();
    const todo = buildProjectTaskStatus({
      id: 10,
      project_id: 5,
      category: "todo",
      is_default: true,
    });
    const task = buildTask({
      id: 101,
      title: "Write the thing",
      community_id: 3,
      project_id: 5,
      task_status_id: todo.id,
      task_status: todo,
    });
    server.use(
      // The same task in the table and on the focus card.
      http.get("/api/v1/me/tasks", () =>
        HttpResponse.json({
          items: [task],
          total_count: 1,
          page: 1,
          page_size: 20,
          has_next: false,
        })
      ),
      http.get("/api/v1/c/:communityId/projects/:projectId/task-statuses", () =>
        HttpResponse.json([todo])
      ),
      http.patch("/api/v1/c/:communityId/tasks/:taskId", async () => {
        await delay("infinite");
        return new HttpResponse(null, { status: 204 });
      })
    );
    keepLayout({
      version: 1,
      widgets: [
        { id: "focus", type: "focus", grid: { x: 0, y: 0, w: 12, h: 5 } },
        { id: "tasks", type: "tasks", grid: { x: 0, y: 5, w: 12, h: 10 } },
      ],
    });
    renderHome();

    const table = await screen.findByRole("table");
    await within(table).findByText("Write the thing");
    const boxes = () => screen.getAllByRole("checkbox", { name: /mark task as done/i });
    await waitFor(() => expect(boxes().length).toBeGreaterThanOrEqual(2));
    await user.click(within(table).getByRole("checkbox", { name: /mark task as done/i }));

    // Both copies wait for the one save, so neither can start a second.
    await waitFor(() => {
      for (const box of screen.getAllByRole("checkbox", {
        name: /mark task as (done|in progress)/i,
      })) {
        expect(box).toBeDisabled();
      }
    });
  });

  it("sends the reader to the marketplace for more layouts", async () => {
    const user = userEvent.setup();
    keepLayout(comingUpAndCommunities);
    renderHome();

    await user.click(await screen.findByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "New view" }));
    const picker = await screen.findByRole("dialog", { name: "New view" });
    expect(within(picker).getByRole("link", { name: "Browse the marketplace" })).toHaveAttribute(
      "href",
      "/marketplace"
    );
  });

  it("wears the banner a view was given, while the reader still has it", async () => {
    const user = userEvent.setup();
    let library = [buildOwnedDecoration({ id: "core.aurora", kind: "banner" })];
    server.use(http.get("/api/v1/me/decorations", () => HttpResponse.json({ items: library })));
    const kept = keepLayout(comingUpAndCommunities);
    const first = renderHome();

    // No banner yet: the page's heading is the hidden one.
    await screen.findByRole("heading", { name: "Coming up" });
    expect(first.container.querySelector('img[src*="aurora"]')).toBeNull();

    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Banner" }));
    const picker = await screen.findByRole("dialog", { name: "This view's banner" });
    await user.click(await within(picker).findByRole("radio", { name: "Aurora" }));

    await waitFor(() => expect(keptLayout(kept)?.banner).toBe("core.aurora"));
    await waitFor(() => expect(first.container.querySelector('img[src*="aurora"]')).not.toBeNull());
    await user.click(within(picker).getByRole("button", { name: "Done" }));
    // The view tabs ride at the top of the banner.
    const banner = first.container.querySelector('img[src*="aurora"]') as Element;
    expect(banner.parentElement?.contains(screen.getByRole("tablist"))).toBe(true);

    // Done, with one view: no bar of tabs, only the button to customize.
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Customize" })).toBeInTheDocument();

    // A pack given back takes its banner with it.
    first.unmount();
    library = [];
    const second = renderHome();
    await screen.findByRole("heading", { name: "Coming up" });
    expect(second.container.querySelector('img[src*="aurora"]')).toBeNull();
  });

  it("keeps a dialog the tabs opened when the view's banner arrives", async () => {
    const user = userEvent.setup();
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("/api/v1/me/decorations", async () => {
        await gate;
        return HttpResponse.json({
          items: [buildOwnedDecoration({ id: "core.aurora", kind: "banner" })],
        });
      })
    );
    const kept = keepLayout({ ...comingUpAndCommunities, banner: "core.aurora" });
    kept[HOME_VIEWS_KEY] = {
      version: 1,
      views: [
        { id: MAIN_VIEW_ID, name: "Home" },
        { id: "league", name: "League" },
      ],
    } satisfies HomeViews;
    const { container } = renderHome();

    await user.click(await screen.findByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Options for Home" }));
    await user.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const name = await screen.findByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Work");

    // The banner lands while the rename is open.
    release();
    await waitFor(() => expect(container.querySelector('img[src*="aurora"]')).not.toBeNull());
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Work");
  });

  it("says when the banner library could not be read, rather than that it is empty", async () => {
    const user = userEvent.setup();
    server.use(http.get("/api/v1/me/decorations", () => new HttpResponse(null, { status: 500 })));
    keepLayout(comingUpAndCommunities);
    renderHome();

    await user.click(await screen.findByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Banner" }));
    const picker = await screen.findByRole("dialog", { name: "This view's banner" });
    expect(await within(picker).findByText("Couldn't load your banners.")).toBeInTheDocument();
    expect(within(picker).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

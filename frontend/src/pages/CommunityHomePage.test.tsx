import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { addDays, addHours, format, startOfDay } from "date-fns";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import {
  buildActivityEntry,
  buildBanner,
  buildCalendarEvent,
  buildCommunity,
  buildInitiative,
  buildInitiativeDirectoryEntry,
  buildInitiativeJoinRequest,
  buildPoll,
  buildPost,
  buildProject,
  buildRecentActivityEntry,
  buildTask,
  buildUser,
  buildUserPublic,
  initiativeCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { BannerTextAlign } from "@/api/generated/initiativeAPI.schemas";
import { queryClient } from "@/lib/queryClient";
import { setItem } from "@/lib/storage";
import { isToolEnabled, TOOLS } from "@/lib/tools";

import { CommunityHomePage } from "./CommunityHomePage";

const INITIATIVE_ID = 7;

/** Whoever is reading the page. */
const READER = buildUser({ id: 42 });

/** The listing is the reader's own memberships, community admin or not, so the
 *  stub carries their role, and may view every tool the initiative has on. */
function stubInitiatives(overrides: Record<string, boolean> = {}) {
  const initiative = buildInitiative({
    id: INITIATIVE_ID,
    name: "Apollo",
    member_count: 1,
    role_display_name: "Member",
    ...overrides,
  });
  initiative.can = initiativeCan({ view: TOOLS.filter((tool) => isToolEnabled(tool, initiative)) });
  server.use(communityHttp.get("/initiatives/", () => HttpResponse.json([initiative])));
}

/** What the community offers to join. Empty by default, as in the shared handlers. */
function stubDirectory(entries: unknown[]) {
  server.use(communityHttp.get("/initiatives/directory", () => HttpResponse.json(entries)));
}

/** One card on offer whose own state flips once the reader has acted on it —
 *  which is what re-reading the directory has to surface. */
function stubFlippingDirectory(
  entry: Parameters<typeof buildInitiativeDirectoryEntry>[0],
  flips: "is_member" | "has_pending_request"
) {
  const acted = { yet: false };
  server.use(
    communityHttp.get("/initiatives/directory", () =>
      HttpResponse.json([buildInitiativeDirectoryEntry({ ...entry, [flips]: acted.yet })])
    )
  );
  return acted;
}

/** A community with nothing in it: no initiatives, and whatever —
 *  usually nothing — it has on offer to join. */
function stubEmptyCommunity(directory: unknown[] = []) {
  server.use(communityHttp.get("/initiatives/", () => HttpResponse.json([])));
  stubDirectory(directory);
}

const NEBULA = () => buildInitiativeDirectoryEntry({ id: 9, name: "Nebula", join_policy: "open" });

/** One case of the feed: what the community holds, the entry, and where it
 *  has to lead. */
type FeedCase = [
  label: string,
  community: { initiative?: Record<string, boolean> },
  entry: Parameters<typeof buildActivityEntry>[0],
  href: string,
];

/** The community's feed holds these entries, and says which view was asked for. */
function stubFeed(...entries: ReturnType<typeof buildActivityEntry>[]) {
  const asked: string[] = [];
  server.use(
    communityHttp.get("/activity/", ({ request }) => {
      asked.push(new URL(request.url).searchParams.get("view") ?? "");
      return HttpResponse.json({ items: entries, page: 1, page_size: 20, has_next: false });
    })
  );
  return asked;
}

/** One comment case: what the community holds, what was said, and where it
 *  has to lead. */
type CommentCase = [
  label: string,
  community: { initiative?: Record<string, boolean> },
  entry: NonNullable<Parameters<typeof buildRecentActivityEntry>[0]>,
  says: string,
  href: string,
];

/** One comment in the community's feed, wherever it was left. */
function stubRecentComment(overrides: Parameters<typeof buildRecentActivityEntry>[0]) {
  server.use(
    communityHttp.get("/comments/recent", () =>
      HttpResponse.json([buildRecentActivityEntry(overrides)])
    )
  );
}

const renderHome = (search?: Record<string, unknown>) =>
  renderPage(CommunityHomePage, {
    auth: { user: READER },
    communities: {
      activeCommunityId: 1,
      activeCommunity: buildCommunity({ id: 1, role: "admin" }),
    },
    routerSearch: search,
  });

/** The same page over a community that carries something particular: the
 *  banner cases turn on what the community *is*, not on what is in it. */
const renderHomeFor = (community: Parameters<typeof buildCommunity>[0]) =>
  renderPage(CommunityHomePage, {
    communities: {
      activeCommunityId: 1,
      activeCommunity: buildCommunity({ id: 1, role: "admin", ...community }),
    },
  });

/** Mounted against the app's own query client — the one the invalidation
 *  helpers address, so a flow that turns on a refetch is observable at all. */
const renderHomeLive = (role: "admin" | "member") =>
  renderPage(CommunityHomePage, {
    communities: { activeCommunityId: 1, activeCommunity: buildCommunity({ id: 1, role }) },
    queryClient,
  });

/** The same page seen by a plain member — no create affordance. */
const renderHomeAsMember = (search?: Record<string, unknown>) =>
  renderPage(CommunityHomePage, {
    auth: { user: READER },
    communities: {
      activeCommunityId: 1,
      activeCommunity: buildCommunity({ id: 1, role: "member" }),
    },
    routerSearch: search,
  });

describe("CommunityHomePage", () => {
  // One test mounts against the app's own query client (the one the
  // invalidation helpers address); clear it so nothing carries between tests.
  beforeEach(() => {
    queryClient.clear();
  });

  it("heads the page with the community's banner, carrying its own name and description", async () => {
    stubInitiatives();

    renderHomeFor({
      name: "Ravenloft Chronicle",
      description: "A long campaign in the mists",
      banner: buildBanner({ image_url: "/api/v1/communities/1/image/abc" }),
    });

    const heading = await screen.findByRole("heading", { name: "Ravenloft Chronicle" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("A long campaign in the mists")).toBeInTheDocument();
  });

  // Every community has a banner, so a community that set no artwork is headed by
  // the colour it wears rather than by a plain title.
  it.each([
    [
      "the colour the community set instead of artwork",
      buildBanner({ color: "#2a9d8f" }),
      "rgb(42, 157, 143)",
    ],
    ["the colour it wears by default", buildBanner(), "rgb(37, 99, 235)"],
  ])("heads a community with no artwork with %s", async (_label, banner, colour) => {
    stubInitiatives();

    const { container } = renderHomeFor({ banner });

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector(`[style*="${colour}"]`)).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  // "0 online" reads as a verdict on the community rather than on the moment, so an
  // empty room says nothing about presence at all.
  it.each([
    ["says how many are in it right now", 11, 3, "11 members", "3 online"],
    ["says nothing about presence in an empty room", 4, 0, "4 members", null],
  ])(
    "says how big the community is, and %s",
    async (_label, member_count, online_count, members, online) => {
      stubInitiatives();

      renderHomeFor({ member_count, online_count });

      await screen.findByRole("heading", { level: 1 });
      expect(screen.getByText(members)).toBeInTheDocument();
      if (online) {
        expect(screen.getByText(online)).toBeInTheDocument();
      } else {
        expect(screen.queryByText(/online/)).not.toBeInTheDocument();
      }
    }
  );

  it("carries the community's own banner layout through to the banner", async () => {
    stubInitiatives();

    const { container } = renderHomeFor({
      banner: buildBanner({ text_align: "left", fade: "strong" }),
    });

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector("h1")?.parentElement?.className).toContain("text-left");
    // A faded banner is extended and the same amount taken back, so the rail
    // and the tray below end up over its tail.
    const banner = container.querySelector<HTMLElement>("div.grid");
    expect(banner?.style.marginBottom).toBe("-224px");
  });

  // The rail sits under the banner's copy, so it follows the edge that was
  // aligned to rather than a fixed one of its own.
  it.each<[string, BannerTextAlign, boolean]>([
    ["centres the rail under a banner that centres its copy", "center", true],
    ["keeps it against the edge the banner's copy sits on when it is left", "left", false],
  ])("%s", async (_label, text_align, centred) => {
    stubInitiatives();

    renderHomeFor({ banner: buildBanner({ text_align }) });

    await screen.findByRole("heading", { level: 1 });
    const rail = screen.getByRole("navigation", { name: "Community activity" }).firstElementChild;
    if (centred) {
      expect(rail?.className).toContain("justify-center");
    } else {
      expect(rail?.className).not.toContain("justify-center");
    }
  });

  // Each entry leads straight to its item, on whichever surface holds it —
  // including one the community itself holds rather than an initiative.
  it.each<FeedCase>([
    [
      "a task, to the task inside its project",
      {},
      { title: "Fuel check", entity_type: "task", entity_id: 4, tool: "project", tool_id: 1 },
      "/c/1/i/5/projects/1/tasks/4",
    ],
    [
      "a tool entity, to that entity",
      { initiative: { counter_groups_enabled: true } },
      {
        title: "Combat Order",
        entity_type: "counter_group",
        entity_id: 8,
        tool: "counter_group",
        tool_id: 8,
      },
      "/c/1/i/5/counter-groups/8",
    ],
    [
      "a community-level calendar, at the community route",
      { initiative: { calendars_enabled: true } },
      {
        title: "Club Nights",
        entity_type: "calendar",
        entity_id: 3,
        tool: "calendar",
        tool_id: 3,
        initiative_id: null,
      },
      "/c/1/calendars/3",
    ],
  ])("links %s", async (_label, { initiative = {} }, entry, href) => {
    stubInitiatives(initiative);
    stubFeed(buildActivityEntry(entry));

    renderHome();

    const title = String(entry?.title);
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: new RegExp(title) })).toHaveAttribute("href", href);
  });

  // The Comments circle is the community's latest comments. Each names where
  // the comment was left and leads straight back to it, on whichever surface
  // that was — including one the community itself holds rather than an
  // initiative.
  it.each<CommentCase>([
    [
      "the community's latest comment on a task, to the task inside its project",
      {},
      {
        comment_id: 11,
        content: "Ready for the review",
        entity_type: "task",
        entity_id: 4,
        entity_name: "Fuel check",
        project_id: 1,
        project_name: "Lunar Lander",
        initiative_id: 5,
      },
      "on Fuel check in Lunar Lander",
      "/c/1/i/5/projects/1/tasks/4",
    ],
    [
      "a comment left on a tool entity, to that entity",
      { initiative: { counter_groups_enabled: true } },
      {
        comment_id: 12,
        content: "Order looks wrong",
        entity_type: "counter_group",
        entity_id: 8,
        entity_name: "Combat Order",
        initiative_id: 5,
      },
      "on Combat Order",
      "/c/1/i/5/counter-groups/8",
    ],
    [
      "a community-level calendar's comment, at the community route",
      { initiative: { calendars_enabled: true } },
      {
        comment_id: 13,
        content: "Moving this to Thursday",
        entity_type: "calendar",
        entity_id: 3,
        entity_name: "Club Nights",
        initiative_id: null,
      },
      "on Club Nights",
      "/c/1/calendars/3",
    ],
  ])("links %s", async (_label, { initiative = {} }, entry, says, href) => {
    stubInitiatives(initiative);
    stubRecentComment(entry);

    renderHome({ node: "comments" });

    expect(await screen.findByText(says)).toBeInTheDocument();
    expect(screen.getByText(String(entry.content))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: new RegExp(String(entry.content)) })).toHaveAttribute(
      "href",
      href
    );
  });

  it("shows the community's comments in the tray, under their circle", async () => {
    stubInitiatives();
    stubRecentComment({ content: "Still here" });

    renderHome({ node: "comments" });

    const rail = await screen.findByRole("navigation", { name: "Community activity" });
    expect(within(rail).getByRole("link", { name: "Comments" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(await screen.findByText("Still here")).toBeInTheDocument();
  });

  it("says so when the community has no comments yet", async () => {
    stubInitiatives();

    renderHome({ node: "comments" });

    expect(await screen.findByText("No comments yet")).toBeInTheDocument();
  });

  it("opens a plug-in's settings from the address, where the reader answers what it asked", async () => {
    stubInitiatives();
    server.use(
      communityHttp.get("/plugins/3", () =>
        HttpResponse.json({
          id: 3,
          name: "Auto",
          definition: {},
          enabled: true,
          connections: [],
          consents: [
            {
              id: 41,
              purpose: "node-1",
              label: "Comment on the linked issue",
              initiative_id: null,
              requested_access: "read",
              granted_access: null,
              status: "pending",
              requested_at: "2026-09-24T00:00:00Z",
              granted_at: null,
              revoked_at: null,
            },
          ],
        })
      )
    );

    renderHomeAsMember({ plugin: 3 });

    expect(await screen.findByText("Auto: “Comment on the linked issue”")).toBeInTheDocument();
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();
  });

  it("shows everything under All by default, saying who did what", async () => {
    stubInitiatives();
    const asked = stubFeed(
      buildActivityEntry({
        actors: [buildUserPublic({ display_name: "Ada" })],
        actor_count: 3,
        verbs: ["commented", "edited"],
      })
    );

    renderHome();

    const rail = await screen.findByRole("navigation", { name: "Community activity" });
    expect(within(rail).getByRole("link", { name: "All" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText("Ada and 2 others commented and edited")).toBeInTheDocument();
    expect(asked).toEqual(["all"]);
  });

  it("asks the feed for the circle in the address", async () => {
    stubInitiatives();
    const asked = stubFeed();

    renderHome({ node: "yours" });

    const rail = await screen.findByRole("navigation", { name: "Community activity" });
    expect(within(rail).getByRole("link", { name: "Yours" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(
      await screen.findByText("Nothing has happened to your things this week.")
    ).toBeInTheDocument();
    expect(asked).toEqual(["yours"]);
  });

  it("marks what changed since the reader's last visit as new", async () => {
    stubInitiatives();
    await setItem(`activity-last-visit:${READER.id}:1`, "2026-01-15T12:00:00.000Z");
    stubFeed(
      buildActivityEntry({ title: "Since", entity_id: 1, latest: "2026-01-16T00:00:00.000Z" }),
      buildActivityEntry({ title: "Before", entity_id: 2, latest: "2026-01-14T00:00:00.000Z" })
    );

    renderHome();

    const since = (await screen.findByText("Since")).closest("li") as HTMLElement;
    const before = screen.getByText("Before").closest("li") as HTMLElement;
    expect(within(since).getByText("New")).toBeInTheDocument();
    expect(within(before).queryByText("New")).not.toBeInTheDocument();
  });

  it("shows each item once across pages, which are ranked afresh", async () => {
    stubInitiatives();
    const pages = [
      [
        buildActivityEntry({ title: "First", entity_id: 1 }),
        buildActivityEntry({ title: "Moved up", entity_id: 2 }),
      ],
      // Ranked afresh: what was on the first page can come back on the second.
      [
        buildActivityEntry({ title: "Moved up", entity_id: 2 }),
        buildActivityEntry({ title: "Third", entity_id: 3 }),
      ],
    ];
    server.use(
      communityHttp.get("/activity/", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? 1);
        return HttpResponse.json({
          items: pages[page - 1],
          page,
          page_size: 2,
          has_next: page === 1,
        });
      })
    );
    const user = userEvent.setup();

    renderHome();
    await screen.findByText("First");
    await user.click(screen.getByRole("button", { name: "Show more" }));

    expect(await screen.findByText("Third")).toBeInTheDocument();
    expect(screen.getAllByText("Moved up")).toHaveLength(1);
  });

  it("keeps the rows it has when the next page fails, with a way to try again", async () => {
    stubInitiatives();
    server.use(
      communityHttp.get("/activity/", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? 1);
        if (page > 1) return new HttpResponse(null, { status: 500 });
        return HttpResponse.json({
          items: [buildActivityEntry({ title: "First", entity_id: 1 })],
          page,
          page_size: 1,
          has_next: true,
        });
      })
    );
    const user = userEvent.setup();

    renderHome();
    await user.click(await screen.findByRole("button", { name: "Show more" }));

    expect(
      await screen.findByText("Failed to load what's been happening. Please try again later.")
    ).toBeInTheDocument();
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled();
  });

  it("lists everything dated this week under the initiatives, each leading to itself", async () => {
    stubInitiatives();
    const tomorrowNoon = addHours(addDays(startOfDay(new Date()), 1), 12);
    const asked: URL[] = [];
    server.use(
      communityHttp.get("/calendar-entries/", ({ request }) => {
        asked.push(new URL(request.url));
        return HttpResponse.json({
          events: [
            buildCalendarEvent({
              id: 5,
              title: "Board night",
              initiative_id: INITIATIVE_ID,
              start_at: tomorrowNoon.toISOString(),
              end_at: addHours(tomorrowNoon, 2).toISOString(),
            }),
          ],
          tasks: [
            buildTask({
              id: 11,
              title: "Print flyers",
              project_id: 1,
              project_name: "Lunar Lander",
              initiative_id: INITIATIVE_ID,
              due_date: tomorrowNoon.toISOString(),
            }),
          ],
          task_occurrences: [],
          projects: [
            buildProject({
              id: 2,
              name: "Bake sale",
              initiative_id: INITIATIVE_ID,
              end_date: format(tomorrowNoon, "yyyy-MM-dd"),
            }),
          ],
          polls: [
            buildPost({
              id: 3,
              name: "Pick a night",
              initiative_id: INITIATIVE_ID,
              poll: buildPoll({ question: null, closes_at: tomorrowNoon.toISOString() }),
            }),
          ],
        });
      })
    );

    renderHome();

    const card = (title: string) => screen.getByRole("link", { name: new RegExp(title) });
    expect(await screen.findByText("Board night")).toBeInTheDocument();
    expect(card("Board night")).toHaveAttribute("href", "/c/1/go/calendar-event/5");
    expect(card("Print flyers")).toHaveTextContent("Task due");
    expect(card("Print flyers")).toHaveTextContent("Lunar Lander · Apollo");
    expect(card("Print flyers")).toHaveAttribute(
      "href",
      `/c/1/i/${INITIATIVE_ID}/projects/1/tasks/11`
    );
    expect(card("Bake sale")).toHaveTextContent("Project ends");
    expect(card("Bake sale")).toHaveTextContent("Tomorrow");
    expect(card("Bake sale")).toHaveAttribute("href", `/c/1/i/${INITIATIVE_ID}/projects/2`);
    expect(card("Pick a night")).toHaveTextContent("Poll closes");
    expect(card("Pick a night")).toHaveAttribute("href", `/c/1/i/${INITIATIVE_ID}/posts/3`);
    // Projects and polls are asked for, and only open tasks.
    const url = asked.at(-1);
    expect(url?.searchParams.get("include_projects")).toBe("true");
    expect(url?.searchParams.get("include_polls")).toBe("true");
    expect(url?.searchParams.get("conditions")).toContain("in_progress");
  });

  it("lists the community's initiatives under the feed, grouped by where you stand", async () => {
    stubInitiatives();
    stubDirectory([
      buildInitiativeDirectoryEntry({ id: INITIATIVE_ID, name: "Apollo", is_member: true }),
      NEBULA(),
    ]);

    renderHome();

    expect(await screen.findByRole("heading", { name: "Initiatives" })).toBeInTheDocument();
    const mine = (await screen.findByRole("heading", { name: "Your initiatives" }))
      .parentElement as HTMLElement;
    const joinable = screen.getByRole("heading", { name: "Open to join" })
      .parentElement as HTMLElement;
    expect(within(mine).getByRole("link", { name: "Apollo" })).toBeInTheDocument();
    expect(within(joinable).getByRole("button", { name: "Join" })).toBeInTheDocument();
  });

  it("asks no directory for a guest", async () => {
    stubInitiatives();
    let asked = false;
    server.use(
      communityHttp.get("/initiatives/directory", () => {
        asked = true;
        return HttpResponse.json([NEBULA()]);
      })
    );

    renderHomeFor({ role: "guest" });

    expect(
      await screen.findByRole("navigation", { name: "Community activity" })
    ).toBeInTheDocument();
    expect(screen.queryByText("Nebula")).not.toBeInTheDocument();
    expect(asked).toBe(false);
  });

  it("folds the whole initiatives section away from its heading", async () => {
    stubInitiatives();
    stubDirectory([NEBULA()]);

    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: /Initiatives/ }));

    await waitFor(() => expect(screen.queryByText("Nebula")).not.toBeInTheDocument());
    // The rest of the page is untouched by the fold.
    expect(screen.getByRole("navigation", { name: "Community activity" })).toBeInTheDocument();
  });

  it("offers a community admin the create dialog from the section header", async () => {
    stubInitiatives();
    stubDirectory([NEBULA()]);

    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: /New initiative/i }));

    // The wizard opens on its first question, not on a form of everything.
    expect(await screen.findByRole("dialog")).toHaveTextContent("What is it called?");
  });

  it("keeps creating out of a member's hands", async () => {
    stubInitiatives();
    stubDirectory([NEBULA()]);

    renderHomeAsMember();

    expect(await screen.findByRole("heading", { name: "Initiatives" })).toBeInTheDocument();
    // The backend refuses it either way; the affordance doesn't pretend.
    expect(screen.queryByRole("button", { name: /New initiative/i })).not.toBeInTheDocument();
  });

  it("opens the create dialog for the ?create=true deep link", async () => {
    stubInitiatives();

    renderHome({ create: "true" });

    // The sidebar's "Add initiative" and the retired /i list route both land here.
    // The wizard opens on its first question, not on a form of everything.
    expect(await screen.findByRole("dialog")).toHaveTextContent("What is it called?");
  });

  it("re-reads the community once the reader joins, so the card flips to joined", async () => {
    stubInitiatives();

    // The membership row is what the directory reports back on, so the second
    // read — the one the join's invalidation forces — answers differently.
    const acted = stubFlippingDirectory(
      { id: 9, name: "Nebula", join_policy: "open" },
      "is_member"
    );
    server.use(
      communityHttp.post("/initiatives/:id/join", () => {
        acted.yet = true;
        return HttpResponse.json(buildInitiative({ id: 9, name: "Nebula", join_policy: "open" }));
      })
    );

    renderHomeLive("admin");

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    // Once you're in, the card's title leads there and the Join is spent.
    expect(await screen.findByRole("link", { name: "Nebula" })).toHaveAttribute("href", "/c/1/i/9");
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("re-reads the community once the reader knocks, so the card flips to requested", async () => {
    stubInitiatives();

    // Asking changes nothing about what the reader can see — only the card's
    // own state — so the directory is what has to answer differently.
    const acted = stubFlippingDirectory(
      { id: 9, name: "Vanguard", join_policy: "request" },
      "has_pending_request"
    );
    server.use(
      communityHttp.post("/initiatives/:id/join-requests", () => {
        acted.yet = true;
        return HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: 9 }), { status: 201 });
      })
    );

    renderHomeLive("member");

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));

    // Waiting on a manager is a state, not an action.
    expect(await screen.findByText("Requested")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request to join" })).not.toBeInTheDocument();
  });

  it("tells a member with no initiatives how to get into one", async () => {
    stubEmptyCommunity([NEBULA()]);

    renderHomeAsMember();

    expect(await screen.findByText(/You haven’t joined any initiatives yet/)).toBeInTheDocument();
    // The directory is the way in, so it takes the page over from the rail.
    expect(screen.getByRole("button", { name: "Join" })).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Community activity" })
    ).not.toBeInTheDocument();
  });

  it("does not call a failed lookup an empty membership", async () => {
    stubEmptyCommunity();
    server.use(communityHttp.get("/initiatives/", () => new HttpResponse(null, { status: 500 })));

    renderHomeAsMember();

    // A request that never answered is not proof the reader is in nothing —
    // saying so would be a confident lie about their own access.
    expect(
      await screen.findByRole("navigation", { name: "Community activity" })
    ).toBeInTheDocument();
    expect(screen.queryByText(/You haven’t joined any initiatives yet/)).not.toBeInTheDocument();
  });

  it("does not call a failed directory an empty one", async () => {
    stubEmptyCommunity();
    server.use(
      communityHttp.get("/initiatives/directory", () => new HttpResponse(null, { status: 500 }))
    );

    renderHomeAsMember();

    // Being in nothing is established; having nothing to join is not, so the
    // page says the list failed rather than inventing an empty community.
    expect(await screen.findByText(/You haven’t joined any initiatives yet/)).toBeInTheDocument();
    expect(await screen.findByText(/couldn't load this/i)).toBeInTheDocument();
    expect(screen.queryByText("Nothing to join yet")).not.toBeInTheDocument();
  });

  it("stays honest when the community has nothing on offer either", async () => {
    stubEmptyCommunity();

    renderHomeAsMember();

    expect(await screen.findByText("Nothing to join yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
    // A member has no way to make one, so nothing offers it.
    expect(screen.queryByRole("button", { name: /Create initiative/i })).not.toBeInTheDocument();
  });

  it("offers an admin of an empty community the first initiative, not an admin to ask", async () => {
    stubEmptyCommunity();

    renderHome();

    // A community with nothing in it is now the ordinary first minute, and the
    // reader looking at it is the person who fills it. Telling them they
    // haven't joined anything, or that an admin could add them to one, would
    // be sending them to themselves.
    expect(await screen.findByText("This community has no initiatives yet")).toBeInTheDocument();
    expect(screen.getByText("Start the first initiative")).toBeInTheDocument();
    expect(screen.queryByText(/You haven’t joined any initiatives yet/)).not.toBeInTheDocument();
    expect(screen.queryByText(/A community admin or project manager/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Create initiative/i }));

    // The wizard opens on its first question, not on a form of everything.
    expect(await screen.findByRole("dialog")).toHaveTextContent("What is it called?");
  });
});

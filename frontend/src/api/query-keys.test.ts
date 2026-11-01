import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { type PostRead, PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  invalidate,
  patchCachedPost,
  q,
  resetCommunityScopedQueries,
  setInvalidationCommunity,
} from "@/api/query-keys";
import { queryClient } from "@/lib/queryClient";
import { TOOLS, toolRouteSegment } from "@/lib/tools";

/** Seed a query so it exists in the cache, then report whether it got invalidated. */
const seed = (key: readonly unknown[]) => {
  queryClient.setQueryData(key, { seeded: true });
  return () => queryClient.getQueryState(key)?.isInvalidated ?? false;
};

describe("query-keys community scoping", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  it("invalidates only the active community's queries", async () => {
    const activeCommunity = seed(["/api/v1/c/5/tasks/"]);
    const otherCommunity = seed(["/api/v1/c/7/tasks/"]);

    setInvalidationCommunity(5);
    await invalidate(q.allTasks());

    expect(activeCommunity()).toBe(true);
    expect(otherCommunity()).toBe(false);
  });

  it("still invalidates the cross-community /me aggregate", async () => {
    const communityScoped = seed(["/api/v1/c/5/tasks/"]);
    const meAggregate = seed(["/api/v1/me/tasks"]);

    setInvalidationCommunity(5);
    await invalidate(q.allTasks());

    expect(communityScoped()).toBe(true);
    expect(meAggregate()).toBe(true);
  });

  it("refreshes an initiative's list of layouts with its projects, and not with files", async () => {
    const key = ["/api/v1/c/5/layouts/initiative", { initiative_id: 2 }];
    const listed = seed(key);

    setInvalidationCommunity(5);
    await invalidate(q.allFiles());
    expect(listed()).toBe(false);
    await invalidate(q.allProjects());
    expect(listed()).toBe(true);
  });

  it("refreshes the calendar entries with projects and posts, whose dates they show", async () => {
    const entries = seed(["/api/v1/c/5/calendar-entries/"]);

    setInvalidationCommunity(5);
    await invalidate(q.allFiles());
    expect(entries()).toBe(false);
    await invalidate(q.toolLists(Tool.project));
    expect(entries()).toBe(true);

    const again = seed(["/api/v1/c/5/calendar-entries/", { include_polls: true }]);
    await invalidate(q.toolLists(Tool.post));
    expect(again()).toBe(true);
  });

  it.each(TOOLS)("a %s list reaches its cross-community /me twin", async (tool) => {
    const communityList = seed([`/api/v1/c/5/${toolRouteSegment(tool)}/`]);
    const meList = seed([`/api/v1/me/${toolRouteSegment(tool)}`]);

    setInvalidationCommunity(5);
    await invalidate(q.toolList(tool));

    expect(communityList()).toBe(true);
    expect(meList()).toBe(true);
  });

  it("a property write reaches the row's own reads and the tool it sits in", async () => {
    const page = seed(["/api/v1/c/5/wiki-pages/9"]);
    const tree = seed(["/api/v1/c/5/wikis/3/pages"]);
    const unrelated = seed(["/api/v1/c/5/files/"]);
    const calendarEntries = seed(["/api/v1/c/5/calendar-entries/"]);

    setInvalidationCommunity(5);
    await invalidate(q.propertyHolder(PropertyTarget.wiki_page));

    expect(page()).toBe(true);
    expect(tree()).toBe(true);
    expect(unrelated()).toBe(false);
    expect(calendarEntries()).toBe(false);

    // A task's values also show on the calendar's entries.
    await invalidate(q.propertyHolder(PropertyTarget.task));
    expect(calendarEntries()).toBe(true);
  });

  it("falls back to plain matching when no active community is set", async () => {
    const communityA = seed(["/api/v1/c/5/tasks/"]);
    const communityB = seed(["/api/v1/c/7/tasks/"]);

    // No setInvalidationCommunity call (personal mode / pre-mount): scoping is skipped.
    await invalidate(q.allTasks());

    expect(communityA()).toBe(true);
    expect(communityB()).toBe(true);
  });

  describe("boundaries do not cross", () => {
    it("community invalidation never touches personal / platform keys", async () => {
      const communityScoped = seed(["/api/v1/c/5/initiatives/"]);
      const meTasks = seed(["/api/v1/me/tasks"]);
      const notifications = seed(["/api/v1/notifications/"]);
      const recents = seed(["/api/v1/me/personal-items"]);

      setInvalidationCommunity(5);
      await invalidate(q.allInitiatives());

      expect(communityScoped()).toBe(true);
      expect(meTasks()).toBe(false);
      expect(notifications()).toBe(false);
      expect(recents()).toBe(false);
    });

    it("personal invalidation never touches community keys", async () => {
      const notifications = seed(["/api/v1/notifications/"]);
      const communityTasks = seed(["/api/v1/c/5/tasks/"]);

      setInvalidationCommunity(5);
      await invalidate(q.notifications());

      expect(notifications()).toBe(true);
      expect(communityTasks()).toBe(false);
    });

    // The community member roster is community-scoped (`/api/v1/c/{id}/users/`) even though
    // its mutations go through the platform `/api/v1/communities/...` path — a role change
    // must refresh the active community's roster without a manual reload.
    it("community member invalidation hits the active community roster only", async () => {
      const activeRoster = seed(["/api/v1/c/5/users/", { page: 2, page_size: 20 }]);
      const activeSearch = seed(["/api/v1/c/5/users/search", { search: "ada" }]);
      const otherRoster = seed(["/api/v1/c/7/users/"]);

      setInvalidationCommunity(5);
      await invalidate(q.communityMembers());

      expect(activeRoster()).toBe(true);
      expect(activeSearch()).toBe(true);
      expect(otherRoster()).toBe(false);
    });

    // Spanning helper: reaches platform AI (personal) AND the active community's AI
    // settings, but still never another community's.
    it("all-AI-settings spans both families without crossing communities", async () => {
      const platform = seed(["/api/v1/settings/ai/platform"]);
      const communityAI = seed(["/api/v1/c/5/settings/ai/resolved"]);
      const otherCommunityAI = seed(["/api/v1/c/7/settings/ai/resolved"]);

      setInvalidationCommunity(5);
      await invalidate(q.allAISettings());

      expect(platform()).toBe(true);
      expect(communityAI()).toBe(true);
      expect(otherCommunityAI()).toBe(false);
    });
  });

  describe("community switch", () => {
    // Reset (unlike invalidate) drops the data, so a surviving key is one whose
    // cached value is still there afterwards.
    const survives = (key: readonly unknown[]) => {
      queryClient.setQueryData(key, { seeded: true });
      return () => queryClient.getQueryData(key) !== undefined;
    };

    it("drops community-scoped data and keeps every key that addresses no community", async () => {
      const communityScoped = survives(["/api/v1/c/5/projects/"]);
      const kept = [
        ["/api/v1/communities/"],
        ["/api/v1/communities/directory", { search: "chess" }],
        ["/api/v1/access-grants/queue", { status: "pending" }],
        ["/api/v1/me"],
        ["/api/v1/me/tasks", { page: 1 }],
        // The tabs bar spans every community, so a switch must not blank it.
        ["/api/v1/me/personal-items"],
        ["dm", "inbox"],
        // Hand-written community keys carry their community, so another community never reads them.
        ["query", 5, "SELECT 1", null],
      ].map(survives);

      await resetCommunityScopedQueries();

      expect(communityScoped()).toBe(false);
      for (const key of kept) expect(key()).toBe(true);
    });

    it("keeps the arriving community's own data — it is not the departing community's", async () => {
      const arriving = survives(["/api/v1/c/5/projects/"]);
      const arrivingDetail = survives(["/api/v1/c/5/tasks/12"]);
      const departing = survives(["/api/v1/c/4/projects/"]);

      await resetCommunityScopedQueries(5);

      expect(arriving()).toBe(true);
      expect(arrivingDetail()).toBe(true);
      expect(departing()).toBe(false);
    });

    it("keeps a person's own views of the departing community's lists", async () => {
      const views = survives(["/api/v1/c/4/view-preferences"]);
      const lists = survives(["/api/v1/c/4/projects/"]);

      await resetCommunityScopedQueries(5);

      expect(views()).toBe(true);
      expect(lists()).toBe(false);
    });

    it("still drops everything community-scoped when no arriving community is named", async () => {
      const five = survives(["/api/v1/c/5/projects/"]);

      await resetCommunityScopedQueries();

      expect(five()).toBe(false);
    });
  });
});

/**
 * Read state and ballots are written into the cache rather than refetched:
 * invalidating for either would refetch the board mid-scroll, moving rows
 * under the cursor and — with the unread filter on — deleting the one being
 * read. That only works if the patch reaches every shape a post is cached in,
 * and the board is the one that is easy to miss: it scrolls rather than pages,
 * so its cache is an infinite query's `{ pages: [...] }` and not a single page
 * of items.
 */
describe("patchCachedPost", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  const markRead = (post: PostRead) => ({ ...post, is_read: true });

  it("patches a post inside an infinite feed's pages", () => {
    const key = ["/api/v1/c/5/posts/", { initiative_id: 1 }];
    queryClient.setQueryData(key, {
      pageParams: [1, 2],
      pages: [
        { items: [{ id: 1, is_read: false }], page: 1 },
        { items: [{ id: 2, is_read: false }], page: 2 },
      ],
    });

    patchCachedPost(2, markRead);

    const data = queryClient.getQueryData(key) as {
      pages: { items: { id: number; is_read: boolean }[] }[];
    };
    expect(data.pages[1].items[0].is_read).toBe(true);
    expect(data.pages[0].items[0].is_read).toBe(false);
  });

  it("leaves untouched pages identical, so their cards do not re-render", () => {
    const key = ["/api/v1/c/5/posts/"];
    const untouched = { items: [{ id: 1, is_read: false }], page: 1 };
    queryClient.setQueryData(key, {
      pageParams: [1, 2],
      pages: [untouched, { items: [{ id: 2, is_read: false }], page: 2 }],
    });

    patchCachedPost(2, markRead);

    const data = queryClient.getQueryData(key) as { pages: unknown[] };
    expect(data.pages[0]).toBe(untouched);
  });

  it("still patches a single page of items and a single post", () => {
    const listKey = ["/api/v1/c/5/posts/"];
    const postKey = ["/api/v1/c/5/posts/7"];
    queryClient.setQueryData(listKey, { items: [{ id: 7, is_read: false }] });
    queryClient.setQueryData(postKey, { id: 7, is_read: false });

    patchCachedPost(7, markRead);

    expect(
      (queryClient.getQueryData(listKey) as { items: { is_read: boolean }[] }).items[0].is_read
    ).toBe(true);
    expect((queryClient.getQueryData(postKey) as { is_read: boolean }).is_read).toBe(true);
  });
});

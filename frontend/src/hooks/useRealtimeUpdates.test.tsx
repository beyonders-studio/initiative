/**
 * Realtime invalidation drift tests — what a frame off the bus refreshes.
 *
 * The bus names a resource and the resources it sits inside, both as
 * `{type, id}` and both addressed the same way (backend `event_outbox.parents`).
 * The handler derives its work from the tool registry rather than a branch per
 * kind, so these walk `TOOLS`: adding a tool without an invalidation path fails
 * here instead of shipping a thread that only refreshes on reload.
 */

import { InfiniteQueryObserver } from "@tanstack/react-query";
import { HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildComment } from "@/__tests__/factories/comment.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { latestSocket, MockWebSocket } from "@/__tests__/helpers/mockWebSocket";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { setAuthToken } from "@/api/client";
import { getListCommentsQueryKey } from "@/api/generated/comments/comments";
import type { CommentRead } from "@/api/generated/initiativeAPI.schemas";
import { setInvalidationCommunity } from "@/api/query-keys";
import { commentThreadQueryOptions } from "@/hooks/useComments";
import { applyChanges, useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import { chipKey } from "@/hooks/useSmartChips";
import { dashboardDataKey } from "@/hooks/useSqlQuery";
import { queryClient } from "@/lib/queryClient";
import { TOOLS, toolPlural, toolRouteSegment } from "@/lib/tools";

const COMMUNITY = 5;
const ENTITY_ID = 42;
// Must match the backend's MSG_AUTH.
const MSG_AUTH = 5;

// The hook keys its socket off the route's community; the tests drive the socket
// rather than the router, so the param is stated directly.
vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useParams: () => ({ communityId: String(COMMUNITY) }),
}));

/** Seed a query so it exists in the cache, then report whether it got invalidated. */
const seed = (key: readonly unknown[]) => {
  queryClient.setQueryData(key, { seeded: true });
  return () => queryClient.getQueryState(key)?.isInvalidated ?? false;
};

/** A comment thread on one parent, as `useComments` keys and holds it; open
 *  (something on screen watching it) unless `open` is false. */
const seedThread = (
  param: string,
  id: number,
  { comments = [], open = true }: { comments?: CommentRead[]; open?: boolean } = {}
) => {
  const key = getListCommentsQueryKey(COMMUNITY, { [param]: id });
  queryClient.setQueryData(key, {
    pages: [{ comments, next_cursor: null }],
    pageParams: [undefined],
  });
  if (open) {
    new InfiniteQueryObserver(queryClient, {
      ...commentThreadQueryOptions(COMMUNITY, { [param]: id }),
      enabled: false,
    }).subscribe(() => {});
  }
  return {
    ids: () =>
      queryClient
        .getQueryData<{ pages: { comments: CommentRead[] }[] }>(key)
        ?.pages.flatMap((page) => page.comments.map((c) => c.id)),
    content: (commentId: number) =>
      queryClient
        .getQueryData<{ pages: { comments: CommentRead[] }[] }>(key)
        ?.pages.flatMap((page) => page.comments)
        .find((c) => c.id === commentId)?.content,
    invalidated: () => queryClient.getQueryState(key)?.isInvalidated ?? false,
  };
};

/** Answers the read-back of one comment: the comment as it now reads, or 404
 *  for one that is gone. Returns the ids that were asked for. */
const serveComments = (byId: Record<number, CommentRead | null>) => {
  const asked: number[] = [];
  server.use(
    communityHttp.get("/comments/:commentId", ({ params }) => {
      const id = Number(params.commentId);
      asked.push(id);
      const found = byId[id];
      return found ? HttpResponse.json(found) : new HttpResponse(null, { status: 404 });
    })
  );
  return asked;
};

const comment = (id: number, parents: { type: string; id: number }[]) => ({
  resource: { type: "comments", id },
  parents,
  action: "created",
});

describe("realtime comment frames", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationCommunity(COMMUNITY);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  it.each(TOOLS)("puts a new comment into a %s's thread and refreshes the entity", async (tool) => {
    const thread = seedThread(`${tool}_id`, ENTITY_ID);
    const entity = seed([`/api/v1/c/${COMMUNITY}/${toolRouteSegment(tool)}/${ENTITY_ID}`]);
    serveComments({ 1: buildComment({ id: 1, [`${tool}_id`]: ENTITY_ID }) });

    applyChanges([comment(1, [{ type: toolPlural(tool), id: ENTITY_ID }])], COMMUNITY);

    await vi.waitFor(() => expect(thread.ids(), `${tool} thread`).toEqual([1]));
    expect(thread.invalidated(), `${tool} thread is not read again`).toBe(false);
    expect(entity(), `${tool} entity`).toBe(true);
  });

  it("updates the thread, refreshes the task and its project, and nothing further out", async () => {
    const thread = seedThread("task_id", ENTITY_ID);
    const task = seed([`/api/v1/c/${COMMUNITY}/tasks/${ENTITY_ID}`]);
    // A task list row carries its comment count.
    const taskList = seed([`/api/v1/c/${COMMUNITY}/tasks/`, { project_id: 7 }]);
    const activity = seed([`/api/v1/c/${COMMUNITY}/projects/7/activity`]);
    const project = seed([`/api/v1/c/${COMMUNITY}/projects/7`]);
    const otherActivity = seed([`/api/v1/c/${COMMUNITY}/projects/70/activity`]);
    const projectList = seed([`/api/v1/c/${COMMUNITY}/projects/`, { page: 1 }]);
    const counts = seed([`/api/v1/c/${COMMUNITY}/tools/counts/by-initiative`]);
    const initiative = seed([`/api/v1/c/${COMMUNITY}/initiatives/3`]);
    const members = seed([`/api/v1/c/${COMMUNITY}/initiatives/3/members`]);
    serveComments({ 1: buildComment({ id: 1, task_id: ENTITY_ID }) });

    applyChanges(
      [
        comment(1, [
          { type: "tasks", id: ENTITY_ID },
          { type: "projects", id: 7 },
          { type: "initiatives", id: 3 },
        ]),
      ],
      COMMUNITY
    );

    await vi.waitFor(() => expect(thread.ids(), "thread").toEqual([1]));
    expect(task(), "task").toBe(true);
    expect(taskList(), "task list").toBe(true);
    expect(activity(), "project activity").toBe(true);
    expect(project(), "project").toBe(true);
    expect(otherActivity(), "another project's activity").toBe(false);
    expect(projectList(), "project list").toBe(false);
    expect(counts(), "counts").toBe(false);
    expect(initiative(), "initiative").toBe(false);
    expect(members(), "roster").toBe(false);
  });

  it("refreshes the community's recent activity for any comment", () => {
    const recent = seed([`/api/v1/c/${COMMUNITY}/comments/recent`]);

    applyChanges([comment(1, [{ type: "posts", id: ENTITY_ID }])], COMMUNITY);

    expect(recent()).toBe(true);
  });

  it("leaves another entity's thread alone, and reads nothing for a thread not open", async () => {
    const other = seedThread("post_id", 99);
    const closed = seedThread("post_id", ENTITY_ID, { open: false });
    const asked = serveComments({ 1: buildComment({ id: 1, post_id: ENTITY_ID }) });

    applyChanges([comment(1, [{ type: "posts", id: ENTITY_ID }])], COMMUNITY);

    // A closed thread is only marked stale; it reads again when it is shown.
    await vi.waitFor(() => expect(closed.invalidated()).toBe(true));
    expect(asked).toEqual([]);
    expect(closed.ids()).toEqual([]);
    expect(other.ids()).toEqual([]);
    expect(other.invalidated()).toBe(false);
  });

  it("puts a wiki page's comment into that page's thread, which it names before its wiki", async () => {
    const page = seedThread("wiki_page_id", 7);
    const siblingPage = seedThread("wiki_page_id", 8);
    const asked = serveComments({ 1: buildComment({ id: 1, wiki_page_id: 7 }) });

    applyChanges(
      [
        comment(1, [
          { type: "wiki_pages", id: 7 },
          { type: "wikis", id: ENTITY_ID },
        ]),
      ],
      COMMUNITY
    );

    await vi.waitFor(() => expect(page.ids()).toEqual([1]));
    expect(siblingPage.ids()).toEqual([]);
    expect(siblingPage.invalidated(), "another page's thread is not touched").toBe(false);
    expect(asked).toEqual([1]);
  });

  it("reads back each comment a batch names and brings the open pages up to date", async () => {
    const onTask = { task_id: ENTITY_ID };
    const root = buildComment({ id: 1, ...onTask });
    const reply = buildComment({ id: 2, parent_comment_id: 1, ...onTask });
    const edited = buildComment({ id: 4, content: "Before", ...onTask });
    const thread = seedThread("task_id", ENTITY_ID, { comments: [root, reply, edited] });
    const parents = [{ type: "tasks", id: ENTITY_ID }];
    const asked = serveComments({
      // 1 was deleted; its reply stays, as somebody else's words.
      1: null,
      3: buildComment({ id: 3, ...onTask }),
      4: { ...edited, content: "After" },
      // A reply to a conversation on a page not loaded yet comes with that page.
      5: buildComment({ id: 5, parent_comment_id: 99, ...onTask }),
    });

    applyChanges(
      [comment(4, parents), comment(1, parents), comment(3, parents), comment(5, parents)],
      COMMUNITY
    );

    await vi.waitFor(() => expect(thread.ids()).toEqual([2, 4, 3]));
    expect(thread.content(4)).toBe("After");
    expect(asked.sort()).toEqual([1, 3, 4, 5]);
    expect(thread.invalidated()).toBe(false);
  });
});

describe("realtime frames for a case's conversation", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationCommunity(COMMUNITY);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  it("keeps what is said with the requester out of the task's thread and reads the case again", async () => {
    const onTask = { task_id: ENTITY_ID };
    const thread = seedThread("task_id", ENTITY_ID);
    const caseRead = seed([`/api/v1/c/${COMMUNITY}/tasks/${ENTITY_ID}/case`]);
    serveComments({
      1: buildComment({ id: 1, audience: "filer", ...onTask }),
      2: buildComment({ id: 2, ...onTask }),
    });

    applyChanges(
      [
        comment(1, [{ type: "tasks", id: ENTITY_ID }]),
        comment(2, [{ type: "tasks", id: ENTITY_ID }]),
      ],
      COMMUNITY
    );

    await vi.waitFor(() => expect(thread.ids()).toEqual([2]));
    expect(caseRead()).toBe(true);
  });
});

describe("realtime resource frames", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationCommunity(COMMUNITY);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  it.each(TOOLS)("refreshes a %s that changed", (tool) => {
    const entity = seed([`/api/v1/c/${COMMUNITY}/${toolRouteSegment(tool)}/${ENTITY_ID}`]);

    applyChanges(
      [{ resource: { type: toolPlural(tool), id: ENTITY_ID }, parents: [], action: "updated" }],
      COMMUNITY
    );

    expect(entity()).toBe(true);
  });

  it("moves the counts only when a row arrives, leaves or changes where it counts", () => {
    const list = seed([`/api/v1/c/${COMMUNITY}/counter-groups/`, { page: 1 }]);
    const counts = seed([`/api/v1/c/${COMMUNITY}/tools/counts/by-initiative`]);
    const group = (action: string, changed: string[]) => ({
      resource: { type: "counter_groups", id: ENTITY_ID },
      parents: [],
      action,
      changed,
    });

    applyChanges([group("updated", ["name"])], COMMUNITY);
    expect(list(), "list after a rename").toBe(true);
    expect(counts(), "counts after a rename").toBe(false);

    for (const change of [
      group("updated", ["archived_at"]),
      group("updated", ["sharing"]),
      group("created", []),
      group("deleted", []),
    ]) {
      seed([`/api/v1/c/${COMMUNITY}/tools/counts/by-initiative`]);
      applyChanges([change], COMMUNITY);
      expect(counts(), `counts after ${change.action} ${change.changed}`).toBe(true);
    }
  });

  it("refreshes a task's project and the chips about both from the task's own frame", () => {
    const task = seed([`/api/v1/c/${COMMUNITY}/tasks/${ENTITY_ID}`]);
    const project = seed([`/api/v1/c/${COMMUNITY}/projects/7`]);
    const status = seed(chipKey(COMMUNITY, `task:${ENTITY_ID}:status`));
    const progress = seed(chipKey(COMMUNITY, "project:7:progress"));
    const otherTask = seed(chipKey(COMMUNITY, `task:${ENTITY_ID + 1}:status`));

    applyChanges(
      [
        {
          resource: { type: "tasks", id: ENTITY_ID },
          parents: [{ type: "projects", id: 7 }],
          action: "updated",
        },
      ],
      COMMUNITY
    );

    expect(task(), "task").toBe(true);
    expect(project(), "project").toBe(true);
    expect(status(), "the task's chip").toBe(true);
    expect(progress(), "the project's progress chip").toBe(true);
    expect(otherTask(), "another task's chip").toBe(false);
  });

  it("refreshes every task's chip when a project's columns change", () => {
    // A renamed or recoloured column changes what a status chip says, and the
    // change names the project, not the tasks in it.
    const status = seed(chipKey(COMMUNITY, `task:${ENTITY_ID}:status`));
    const counter = seed(chipKey(COMMUNITY, "counter:4:value"));

    applyChanges(
      [
        {
          resource: { type: "projects", id: 7 },
          parents: [],
          action: "updated",
          changed: ["statuses"],
        },
      ],
      COMMUNITY
    );

    expect(status(), "a task's status chip").toBe(true);
    expect(counter(), "a counter's chip").toBe(false);
  });

  it("refreshes every task, listed or open, when a project's types change", () => {
    // A task carries its type's name, look and page shape, and the change
    // names the project, not the tasks of the type.
    const list = seed([`/api/v1/c/${COMMUNITY}/tasks/`, { project_id: 7 }]);
    const page = seed([`/api/v1/c/${COMMUNITY}/tasks/${ENTITY_ID}`]);
    const chip = seed(chipKey(COMMUNITY, `task:${ENTITY_ID}:status`));
    const counter = seed(chipKey(COMMUNITY, "counter:4:value"));

    applyChanges(
      [
        {
          resource: { type: "projects", id: 7 },
          parents: [],
          action: "updated",
          changed: ["types"],
        },
      ],
      COMMUNITY
    );

    expect(list(), "a list of tasks").toBe(true);
    expect(page(), "a task's page").toBe(true);
    expect(chip(), "a task's chip").toBe(true);
    expect(counter(), "a counter's chip").toBe(false);
  });

  it("refreshes a project's layouts when they change, and not on any other update", () => {
    // The layouts are read at an address of their own, so the project's own
    // refresh does not reach them.
    const layouts = seed([`/api/v1/c/${COMMUNITY}/layouts/`, { tool: "project", tool_id: 7 }]);
    const project = (changed: string[]) => ({
      resource: { type: "projects", id: 7 },
      parents: [],
      action: "updated",
      changed,
    });

    applyChanges([project(["name"])], COMMUNITY);
    expect(layouts(), "after a rename").toBe(false);

    applyChanges([project(["layouts"])], COMMUNITY);
    expect(layouts(), "after a layouts change").toBe(true);
  });

  it("refreshes the roster, the roles, what they permit and the properties", () => {
    // Membership, role and property definition rows have no route of their
    // own, so these report as the initiative — one frame has to cover them.
    // What the roles permit is on the initiative's own read.
    const initiative = seed([`/api/v1/c/${COMMUNITY}/initiatives/${ENTITY_ID}`]);
    const members = seed([`/api/v1/c/${COMMUNITY}/initiatives/${ENTITY_ID}/members`]);
    const roles = seed([`/api/v1/c/${COMMUNITY}/initiatives/${ENTITY_ID}/roles`]);
    const properties = seed([`/api/v1/c/${COMMUNITY}/property-definitions`]);

    applyChanges(
      [{ resource: { type: "initiatives", id: ENTITY_ID }, parents: [], action: "updated" }],
      COMMUNITY
    );

    expect(initiative(), "initiative").toBe(true);
    expect(members(), "members").toBe(true);
    expect(roles(), "roles").toBe(true);
    expect(properties(), "properties").toBe(true);
  });

  it("refreshes the plug-in list and an install's own reads", () => {
    // Community-wide and parentless: nothing else on the client covers it.
    const list = seed([`/api/v1/c/${COMMUNITY}/plugins/`]);
    const detail = seed(["community-plugin", COMMUNITY, ENTITY_ID]);
    const members = seed(["community-plugin-members", COMMUNITY, ENTITY_ID]);

    applyChanges(
      [{ resource: { type: "plugins", id: ENTITY_ID }, parents: [], action: "updated" }],
      COMMUNITY
    );

    expect(list(), "plug-in list").toBe(true);
    expect(detail(), "plug-in detail").toBe(true);
    expect(members(), "plug-in members").toBe(true);
  });

  it("leaves another community's install reads alone", () => {
    const other = seed(["community-plugin", COMMUNITY + 1, ENTITY_ID]);

    applyChanges(
      [{ resource: { type: "plugins", id: ENTITY_ID }, parents: [], action: "created" }],
      COMMUNITY
    );

    expect(other()).toBe(false);
  });

  it("ignores a resource type it has no invalidation for", () => {
    const untouched = seed([`/api/v1/c/${COMMUNITY}/tasks/${ENTITY_ID}`]);

    expect(() =>
      applyChanges(
        [{ resource: { type: "something_new", id: 1 }, parents: [], action: "created" }],
        COMMUNITY
      )
    ).not.toThrow();
    expect(untouched()).toBe(false);
  });

  it("ignores a malformed frame rather than throwing", () => {
    expect(() =>
      applyChanges([{}, { resource: undefined, parents: undefined }], COMMUNITY)
    ).not.toThrow();
  });

  it("still refreshes the parents when the resource itself is unknown", () => {
    const project = seed([`/api/v1/c/${COMMUNITY}/projects/7`]);

    applyChanges(
      [
        {
          resource: { type: "mystery_items", id: 3 },
          parents: [{ type: "projects", id: 7 }],
          action: "updated",
        },
      ],
      COMMUNITY
    );

    expect(project()).toBe(true);
  });
});

/**
 * The socket around those frames: what it says on the way up, and how it
 * notices it has stopped carrying.
 *
 * This bus has no poll behind it — a socket that quietly dies takes live
 * updates with it until something else refetches — so both halves are load
 * bearing: the server's beat is what silence is measured against, and the gap
 * a reconnect names is what the server answers with "something moved".
 */
const Probe = () => {
  useRealtimeUpdates();
  return null;
};

describe("realtime socket lifecycle", () => {
  beforeEach(() => {
    // The socket takes its credential from the api client, where signing in
    // puts it — the auth frame reads it as it writes.
    setAuthToken("test-token");
    MockWebSocket.instances = [];
    queryClient.clear();
    setInvalidationCommunity(COMMUNITY);
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
    // Reconnects are jittered; pin the draw so each lands mid-window.
    vi.spyOn(Math, "random").mockReturnValue(0.5);
  });

  afterEach(() => {
    setAuthToken(null);
    vi.useRealTimers();
    queryClient.clear();
    setInvalidationCommunity(null);
  });

  it("authenticates in the first frame and names no gap", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();

    expect(socket.url).not.toContain("token");
    expect(socket.sent[0][0]).toBe(MSG_AUTH);
    // A tab that has only just mounted fetched what it is showing.
    expect(socket.authPayload()).toEqual({ token: "test-token" });
  });

  it("tells the server how long it was without a socket, dated from the last frame", async () => {
    renderWithProviders(<Probe />);
    const first = latestSocket();
    first.open();
    first.receive({ heartbeat: true });

    // Quiet for a minute, then gone. The gap starts where the frames stopped,
    // not where the close was noticed.
    await vi.advanceTimersByTimeAsync(60_000);
    first.serverClose(1006);
    await vi.advanceTimersByTimeAsync(2000);

    const second = latestSocket();
    expect(second).not.toBe(first);
    second.open();
    expect(second.authPayload()).toEqual({ token: "test-token", away_seconds: 62 });
  });

  it("does not shorten the gap for an attempt that never carried", async () => {
    renderWithProviders(<Probe />);
    const first = latestSocket();
    first.open();
    first.receive({ heartbeat: true });

    await vi.advanceTimersByTimeAsync(30_000);
    first.serverClose(1006);
    // The attempt in between opens and dies having heard nothing, so it has
    // proved nothing about the gap it was meant to close.
    await vi.advanceTimersByTimeAsync(2000);
    latestSocket().open();
    latestSocket().serverClose(1006);
    await vi.advanceTimersByTimeAsync(2000);

    const third = latestSocket();
    third.open();
    expect(third.authPayload()).toEqual({ token: "test-token", away_seconds: 34 });
  });

  it("reads the community again when the server says it fell behind", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();
    const project = seed([`/api/v1/c/${COMMUNITY}/projects/${ENTITY_ID}`]);
    const activity = seed([`/api/v1/c/${COMMUNITY}/projects/${ENTITY_ID}/activity`]);

    socket.receive({ changes: [], more: true });

    expect(project(), "project").toBe(true);
    expect(activity(), "project activity").toBe(true);
  });

  it("ignores a beat beyond taking it as proof of life", async () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();
    const project = seed([`/api/v1/c/${COMMUNITY}/projects/${ENTITY_ID}`]);

    socket.receive({ heartbeat: true });
    await vi.advanceTimersByTimeAsync(1000);

    expect(project()).toBe(false);
    expect(socket.closed).toBe(false);
  });
});

describe("realtime frames and dashboards", () => {
  const INITIATIVE = 3;
  const DASHBOARD = 9;
  const canvas = (relations: string[]) => ({
    initiative_id: INITIATIVE,
    widgets: {
      w1: {
        result: { columns: [], rows: [], truncated: false, relations },
        error: null,
      },
    },
  });
  const seedCanvas = (communityId: number, relations: string[]) => {
    const key = dashboardDataKey(communityId, DASHBOARD);
    queryClient.setQueryData(key, canvas(relations));
    return () => queryClient.getQueryState(key)?.isInvalidated ?? false;
  };
  const task = (initiative: number | null) => ({
    resource: { type: "tasks", id: 1 },
    parents: [{ type: "projects", id: 2 }],
    initiative_id: initiative,
    action: "updated",
  });

  beforeEach(() => queryClient.clear());
  afterEach(() => queryClient.clear());

  it("refreshes a dashboard when something it reads changes in its initiative", () => {
    const stale = seedCanvas(COMMUNITY, ["tasks"]);
    applyChanges([task(INITIATIVE)], COMMUNITY);
    expect(stale()).toBe(true);
  });

  it("leaves it alone when the change is to something it does not read", () => {
    const stale = seedCanvas(COMMUNITY, ["projects"]);
    applyChanges([task(INITIATIVE)], COMMUNITY);
    expect(stale()).toBe(false);
  });

  it("leaves it alone when the change is in another initiative", () => {
    const stale = seedCanvas(COMMUNITY, ["tasks"]);
    applyChanges([task(INITIATIVE + 1)], COMMUNITY);
    expect(stale()).toBe(false);
  });

  it("leaves another community's dashboard alone, whose initiative ids are its own", () => {
    const stale = seedCanvas(COMMUNITY + 1, ["tasks"]);
    applyChanges([task(INITIATIVE)], COMMUNITY);
    expect(stale()).toBe(false);
  });
});

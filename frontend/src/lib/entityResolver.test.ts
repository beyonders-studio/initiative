/**
 * The `/go` resolver is the only path an id-only link has to a real URL, and
 * the legacy normalizer is what keeps already-sent notification links working
 * after tools moved inside their initiatives. Neither is type-checked against
 * a route, so both are pinned here.
 */
import { QueryClient } from "@tanstack/react-query";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import {
  isEntityRefType,
  linkedCommentId,
  normalizeLegacyTarget,
  resolveEntityPath,
} from "@/lib/entityResolver";

const COMMUNITY = 1;
let queryClient: QueryClient;

beforeEach(() => {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("resolveEntityPath", () => {
  it("resolves a tool entity to its initiative-scoped address", async () => {
    server.use(
      communityHttp.get("/projects/:id", () => HttpResponse.json({ id: 7, initiative_id: 5 }))
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "project", 7)).resolves.toBe(
      "/i/5/projects/7"
    );
  });

  it("nests a task under the project that owns it", async () => {
    server.use(
      communityHttp.get("/tasks/:id", () =>
        HttpResponse.json({ id: 9, project_id: 4, project: { id: 4, initiative_id: 2 } })
      )
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "task", 9)).resolves.toBe(
      "/i/2/projects/4/tasks/9"
    );
  });

  it("falls back to reading the project when the task omits its initiative", async () => {
    server.use(
      communityHttp.get("/tasks/:id", () =>
        HttpResponse.json({ id: 9, project_id: 4, project: null })
      ),
      communityHttp.get("/projects/:id", () => HttpResponse.json({ id: 4, initiative_id: 8 }))
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "task", 9)).resolves.toBe(
      "/i/8/projects/4/tasks/9"
    );
  });

  it("nests an event under its calendar, community-level or not", async () => {
    server.use(
      communityHttp.get("/calendar-events/:id", () =>
        HttpResponse.json({ id: 3, calendar_id: 6, initiative_id: null })
      )
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "calendar-event", 3)).resolves.toBe(
      "/calendars/6/events/3"
    );
  });

  it("opens a wiki page inside its wiki", async () => {
    server.use(
      communityHttp.get("/wiki-pages/:id", () => HttpResponse.json({ id: 11, wiki_id: 4 })),
      communityHttp.get("/wikis/:id", () => HttpResponse.json({ id: 4, initiative_id: 1 }))
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "wiki-page", 11)).resolves.toBe(
      "/i/1/wikis/4/pages/11"
    );
  });

  it("opens a collection in its initiative's Files", async () => {
    server.use(
      communityHttp.get("/collections/:id", () => HttpResponse.json({ id: 12, initiative_id: 1 }))
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "collection", 12)).resolves.toBe(
      "/i/1/files/collections/12"
    );
  });

  // Deleted, or invisible to this reader — the caller lands on the community home
  // rather than a URL that 404s.
  it.each([
    ["a task", { task_id: 9 }, "/i/2/projects/4/tasks/9#comment-21"],
    ["a wiki page", { wiki_page_id: 11 }, "/i/1/wikis/4/pages/11#comment-21"],
    ["a post", { post_id: 6 }, "/i/3/posts/6#comment-21"],
  ])("lands a comment on %s, on the comment itself", async (_label, parent, expected) => {
    server.use(
      communityHttp.get("/comments/:id", () =>
        HttpResponse.json({
          id: 21,
          task_id: null,
          wiki_page_id: null,
          post_id: null,
          parent_comment_id: null,
          ...parent,
        })
      ),
      communityHttp.get("/tasks/:id", () =>
        HttpResponse.json({ id: 9, project_id: 4, project: { id: 4, initiative_id: 2 } })
      ),
      communityHttp.get("/wiki-pages/:id", () => HttpResponse.json({ id: 11, wiki_id: 4 })),
      communityHttp.get("/wikis/:id", () => HttpResponse.json({ id: 4, initiative_id: 1 })),
      communityHttp.get("/posts/:id", () => HttpResponse.json({ id: 6, initiative_id: 3 }))
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "comment", 21)).resolves.toBe(expected);
  });

  it("opens a queue item's queue", async () => {
    server.use(
      communityHttp.get("/queue-items/:id", () => HttpResponse.json({ id: 5, queue_id: 2 })),
      communityHttp.get("/queues/:id", () => HttpResponse.json({ id: 2, initiative_id: 7 }))
    );
    await expect(resolveEntityPath(queryClient, COMMUNITY, "queue-item", 5)).resolves.toBe(
      "/i/7/queues/2"
    );
  });

  it("returns null for a comment the reader can't read", async () => {
    server.use(communityHttp.get("/comments/:id", () => HttpResponse.json(null, { status: 404 })));
    await expect(resolveEntityPath(queryClient, COMMUNITY, "comment", 21)).resolves.toBeNull();
  });

  it("reads the comment a fragment names", () => {
    expect(linkedCommentId("#comment-21")).toBe(21);
    expect(linkedCommentId("#comments")).toBeNull();
    expect(linkedCommentId("")).toBeNull();
  });

  it("returns null when the entity can't be read", async () => {
    server.use(communityHttp.get("/files/:id", () => new HttpResponse(null, { status: 404 })));
    await expect(resolveEntityPath(queryClient, COMMUNITY, "file", 99)).resolves.toBeNull();
  });

  it("returns null for an unknown ref type or a non-numeric id", async () => {
    await expect(resolveEntityPath(queryClient, COMMUNITY, "widget", 1)).resolves.toBeNull();
    await expect(
      resolveEntityPath(queryClient, COMMUNITY, "project", Number.NaN)
    ).resolves.toBeNull();
  });

  it("recognises exactly the ref types it can resolve", () => {
    expect(isEntityRefType("counter-group")).toBe(true);
    expect(isEntityRefType("calendar-event")).toBe(true);
    expect(isEntityRefType("counter_group")).toBe(false);
    expect(isEntityRefType("user")).toBe(false);
    expect(isEntityRefType("collection")).toBe(true);
  });
});

describe("normalizeLegacyTarget", () => {
  it("maps a stored pre-nesting target onto the resolver", () => {
    expect(normalizeLegacyTarget("/tasks/4")).toBe("/go/task/4");
    expect(normalizeLegacyTarget("/projects/12")).toBe("/go/project/12");
    expect(normalizeLegacyTarget("/files/3")).toBe("/go/file/3");
    expect(normalizeLegacyTarget("/calendar-events/8")).toBe("/go/calendar-event/8");
    expect(normalizeLegacyTarget("/go/event/8")).toBe("/go/calendar-event/8");
  });

  it("rewrites an initiative path directly — no lookup needed", () => {
    expect(normalizeLegacyTarget("/initiatives/6")).toBe("/i/6");
  });

  it("sends a deleted list page to the community home", () => {
    expect(normalizeLegacyTarget("/projects")).toBe("/");
    expect(normalizeLegacyTarget("/calendar")).toBe("/");
    // The initiative list is a section of the community home now, not a page.
    expect(normalizeLegacyTarget("/initiatives")).toBe("/");
  });

  it("leaves a current path alone", () => {
    expect(normalizeLegacyTarget("/i/5/projects/7")).toBe("/i/5/projects/7");
    expect(normalizeLegacyTarget("/settings/data")).toBe("/settings/data");
    expect(normalizeLegacyTarget("settings/data")).toBe("/settings/data");
  });
});

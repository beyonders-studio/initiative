/**
 * What the router actually resolves each URL to.
 *
 * The initiative subtree puts a tool tab (`/i/5/projects`) beside the
 * initiative's own static children (`/i/5/settings`, `/i/5/plugins/3`), and every
 * link in the app is a plain string rather than a typed route id — so nothing
 * else checks that a built path lands where it was meant to. These failures
 * would otherwise appear only at runtime, as a blank page.
 */
import { createRouter } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

import { buildRouterContext } from "./helpers/render";

const router = createRouter({ routeTree, context: buildRouterContext() });

/**
 * The id of the innermost route a pathname resolves to.
 *
 * A path under `/c/{id}` with no page behind it still matches the community
 * *layout*, so "nothing serves this" reads as resolving to `COMMUNITY` rather than
 * to null — that is what the deleted-route cases below assert.
 */
function resolvedRouteId(pathname: string): string {
  const matches = router.matchRoutes(pathname, {});
  return String(matches.at(-1)?.routeId ?? "__none__");
}

const COMMUNITY = "/_serverRequired/_authenticated/c/$communityId";
const INITIATIVE = `${COMMUNITY}/i/$initiativeId`;

describe("initiative route resolution", () => {
  it.each([
    ["/c/1/i/5", `${INITIATIVE}/`],
    ["/c/1/i/5/projects", `${INITIATIVE}/projects/`],
    ["/c/1/i/5/projects/7", `${INITIATIVE}/projects/$projectId/`],
    ["/c/1/i/5/projects/7/settings", `${INITIATIVE}/projects/$projectId/settings/`],
    ["/c/1/i/5/projects/7/tasks/22", `${INITIATIVE}/projects/$projectId/tasks/$taskId`],
    ["/c/1/i/5/files/3", `${INITIATIVE}/files/$fileId/`],
    ["/c/1/i/5/counter-groups/6", `${INITIATIVE}/counter-groups/$counterGroupId/`],
    [
      "/c/1/i/5/counter-groups/6/counter/9",
      `${INITIATIVE}/counter-groups/$counterGroupId/counter/$counterId`,
    ],
    ["/c/1/i/5/calendars/2", `${INITIATIVE}/calendars/$calendarId/`],
    ["/c/1/i/5/calendars/2/events/8", `${INITIATIVE}/calendars/$calendarId/events/$eventId/`],
    ["/c/1/i/5/dashboards/5", `${INITIATIVE}/dashboards/$dashboardId/`],
  ])("resolves %s", (pathname, routeId) => {
    expect(resolvedRouteId(pathname)).toBe(routeId);
  });

  // The initiatives list is the community home, so the bare `/i` segment serves
  // nothing of its own and falls back to the community layout.
  it("leaves the bare initiatives segment to the community layout", () => {
    expect(resolvedRouteId("/c/1/i")).toBe(COMMUNITY);
  });

  // The tab routes are siblings of these; a tool segment that collided with
  // one, or a ranking that preferred the dynamic sibling, would swallow them.
  it("keeps the initiative's own children ahead of the tool tabs", () => {
    // `/settings` is a layout now; its index serves the details section.
    expect(resolvedRouteId("/c/1/i/5/settings")).toBe(`${INITIATIVE}/settings/`);
    expect(resolvedRouteId("/c/1/i/5/plugins/3")).toBe(`${INITIATIVE}/plugins/$pluginId`);
  });

  // Each settings section is an address of its own, so a manager can be linked
  // straight to one (the join-request queue lives under `members`).
  it.each([
    ["/c/1/i/5/settings/members", `${INITIATIVE}/settings/members`],
    ["/c/1/i/5/settings/roles", `${INITIATIVE}/settings/roles`],
    ["/c/1/i/5/settings/properties", `${INITIATIVE}/settings/properties`],
    ["/c/1/i/5/settings/export", `${INITIATIVE}/settings/export`],
    ["/c/1/i/5/settings/danger", `${INITIATIVE}/settings/danger`],
  ])("resolves %s", (pathname, routeId) => {
    expect(resolvedRouteId(pathname)).toBe(routeId);
  });

  // A tool's settings sections are addresses too, so a share link can point at
  // the sharing controls and the back button walks back out of them.
  it.each([
    ["/c/1/i/5/projects/7/settings/access", `${INITIATIVE}/projects/$projectId/settings/access`],
    [
      "/c/1/i/5/projects/7/settings/task-statuses",
      `${INITIATIVE}/projects/$projectId/settings/task-statuses`,
    ],
    [
      "/c/1/i/5/projects/7/settings/task-types",
      `${INITIATIVE}/projects/$projectId/settings/task-types`,
    ],
    ["/c/1/i/5/files/3/settings/access", `${INITIATIVE}/files/$fileId/settings/access`],
    [
      "/c/1/i/5/counter-groups/6/settings/advanced",
      `${INITIATIVE}/counter-groups/$counterGroupId/settings/advanced`,
    ],
    [
      "/c/1/i/5/dashboards/5/settings/access",
      `${INITIATIVE}/dashboards/$dashboardId/settings/access`,
    ],
    ["/c/1/i/5/calendars/2/settings", `${INITIATIVE}/calendars/$calendarId/settings/`],
    ["/c/1/calendars/2/settings/access", `${COMMUNITY}/calendars/$calendarId/settings/access`],
  ])("resolves %s", (pathname, routeId) => {
    expect(resolvedRouteId(pathname)).toBe(routeId);
  });

  // A calendar's events sit beside its settings sections; neither may swallow
  // the other.
  it("keeps a calendar's events clear of its settings sections", () => {
    expect(resolvedRouteId("/c/1/i/5/calendars/2/events/8")).toBe(
      `${INITIATIVE}/calendars/$calendarId/events/$eventId/`
    );
  });

  // `gallery` is a static sibling of `$dashboardId` at the same depth.
  it("prefers a static leaf over the id beside it", () => {
    expect(resolvedRouteId("/c/1/i/5/dashboards/gallery")).toBe(`${INITIATIVE}/dashboards/gallery`);
  });

  // Only calendars can be community-level; those keep their pre-initiative routes.
  it("resolves a community-level calendar and its events", () => {
    expect(resolvedRouteId("/c/1/calendars/2")).toBe(`${COMMUNITY}/calendars/$calendarId/`);
    expect(resolvedRouteId("/c/1/calendars/2/events/8")).toBe(
      `${COMMUNITY}/calendars/$calendarId/events/$eventId/`
    );
  });

  // The calendar plug-in's own surface — the community's calendars, not a roll-up of
  // its initiatives'. That is why this one address survives the list below.
  it("resolves the community's calendars", () => {
    expect(resolvedRouteId("/c/1/calendars")).toBe(`${COMMUNITY}/calendars/`);
  });

  it("resolves the entity-reference resolver", () => {
    expect(resolvedRouteId("/c/1/go/file/42")).toBe(`${COMMUNITY}/go/$refType/$refId`);
  });

  // Deleted on purpose — the community home is the cross-initiative browse now.
  it.each([
    "/c/1/projects",
    "/c/1/files",
    "/c/1/dashboards",
    "/c/1/counter-groups",
    // Sub-entities moved under their parent tool in the same change.
    "/c/1/tasks/4",
    "/c/1/calendar-events/8",
    // The initiatives tree answers at /i now.
    "/c/1/initiatives",
    "/c/1/initiatives/5",
  ])("no longer serves %s", (path) => {
    expect(resolvedRouteId(path)).toBe(COMMUNITY);
  });
});

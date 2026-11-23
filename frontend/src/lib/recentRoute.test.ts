/**
 * The recents tab bar both BUILDS entity URLs and PARSES them back out of the
 * pathname to decide which tab is active. Neither direction is type-checked
 * against the router, so a URL-shape change breaks the highlight silently —
 * which is exactly what these tests are for.
 */
import { describe, expect, it } from "vitest";

import { buildRecentItem } from "@/__tests__/factories/recent.factory";
import {
  activityScope,
  getActiveRecentKey,
  recentKeyMatches,
  recentRoute,
} from "@/lib/recentRoute";

describe("recentRoute", () => {
  it("addresses an entity inside its community and initiative", () => {
    const item = buildRecentItem({
      entity_type: "project",
      entity_id: 7,
      community_id: 3,
      initiative_id: 5,
    });
    expect(recentRoute(item)).toBe("/c/3/i/5/projects/7");
  });

  // Only calendars can be community-level (a plug-in installs one).
  it("keeps a community-level entity at its community route", () => {
    const item = buildRecentItem({
      entity_type: "calendar",
      entity_id: 9,
      community_id: 3,
      initiative_id: null,
    });
    expect(recentRoute(item)).toBe("/c/3/calendars/9");
  });
});

describe("getActiveRecentKey", () => {
  it("reads community, initiative, tool and entity out of a nested path", () => {
    expect(getActiveRecentKey("/c/3/i/5/wikis/7")).toEqual({
      entityType: "wiki",
      entityId: 7,
      communityId: 3,
      initiativeId: 5,
    });
  });

  it("still matches when the path continues past the entity", () => {
    expect(getActiveRecentKey("/c/1/i/2/projects/4/tasks/9")).toEqual({
      entityType: "project",
      entityId: 4,
      communityId: 1,
      initiativeId: 2,
    });
  });

  it("reads the community-level shape with no initiative segment", () => {
    expect(getActiveRecentKey("/c/1/calendars/12")).toEqual({
      entityType: "calendar",
      entityId: 12,
      communityId: 1,
      initiativeId: null,
    });
  });

  it("returns null for a path that names no entity", () => {
    expect(getActiveRecentKey("/c/1/i/2/projects")).toBeNull();
    expect(getActiveRecentKey("/c/1/i/2")).toBeNull();
    expect(getActiveRecentKey("/c/1/settings/users")).toBeNull();
    expect(getActiveRecentKey("/profile")).toBeNull();
    // A tool segment that isn't a tool.
    expect(getActiveRecentKey("/c/1/i/2/widgets/3")).toBeNull();
    // A non-numeric id must not parse as one.
    expect(getActiveRecentKey("/c/1/i/2/projects/gallery")).toBeNull();
  });
});

describe("activityScope", () => {
  it("narrows to the tool a page is in, including what lives inside it", () => {
    expect(activityScope("/c/1/i/2/projects/3")).toEqual({ tool: "project", toolId: 3 });
    expect(activityScope("/c/1/i/2/projects/3/tasks/9")).toEqual({ tool: "project", toolId: 3 });
    expect(activityScope("/c/1/calendars/4")).toEqual({ tool: "calendar", toolId: 4 });
  });

  it("narrows to an initiative on its own page, and nowhere under it", () => {
    expect(activityScope("/c/1/i/2")).toEqual({ initiativeId: 2 });
    expect(activityScope("/c/1/i/2/")).toEqual({ initiativeId: 2 });
    expect(activityScope("/c/1/i/2/settings")).toBeNull();
    expect(activityScope("/c/1/i/2/projects")).toBeNull();
  });

  it("shows nothing for a tool that opted out, or a page about no tool", () => {
    expect(activityScope("/c/1/i/2/wikis/5")).toBeNull();
    expect(activityScope("/c/1")).toBeNull();
    expect(activityScope("/profile")).toBeNull();
  });
});

describe("recentKeyMatches", () => {
  it("matches on community too, since entity ids collide across communities", () => {
    const item = buildRecentItem({ entity_type: "project", entity_id: 4, community_id: 1 });
    expect(recentKeyMatches(getActiveRecentKey("/c/1/i/2/projects/4"), item)).toBe(true);
    expect(recentKeyMatches(getActiveRecentKey("/c/9/i/2/projects/4"), item)).toBe(false);
    expect(recentKeyMatches(null, item)).toBe(false);
  });
});

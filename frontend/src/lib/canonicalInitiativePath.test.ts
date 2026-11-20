/**
 * A detail page reads its initiative from the path, but the entity it loads is
 * the authority — if the two disagree the address is wrong, and every child,
 * settings and back link built from it would point into an initiative the
 * entity isn't in. This is the rewrite that resolves that.
 */
import { describe, expect, it } from "vitest";

import { canonicalInitiativePath } from "@/lib/communityUrl";

describe("canonicalInitiativePath", () => {
  it.each([
    // An initiative the entity doesn't belong to is replaced.
    ["/c/1/i/9/projects/7", 5, "/c/1/i/5/projects/7"],
    ["/c/1/i/9/projects/7/tasks/22", 5, "/c/1/i/5/projects/7/tasks/22"],
    // A plug-in's calendar belongs to no initiative; its address says so.
    ["/c/1/i/9/calendars/2", null, "/c/1/calendars/2"],
    ["/c/1/i/9/calendars/2/events/8", null, "/c/1/calendars/2/events/8"],
    ["/c/1/calendars/2", 5, "/c/1/i/5/calendars/2"],
    ["/c/1/i/5/projects/7", 5, "/c/1/i/5/projects/7"],
    ["/c/1/calendars/2", null, "/c/1/calendars/2"],
    // Nothing outside a community has an initiative to canonicalize.
    ["/my-tools", 5, "/my-tools"],
    ["/profile/notifications", null, "/profile/notifications"],
    ["/c/1", 5, "/c/1/i/5"],
    ["/c/1/i/5", null, "/c/1"],
  ])("rewrites %s for initiative %s as %s", (path, initiativeId, expected) => {
    expect(canonicalInitiativePath(path, initiativeId)).toBe(expected);
  });
});

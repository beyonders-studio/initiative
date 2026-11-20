import { describe, expect, it } from "vitest";

import type { AnnouncementSection } from "@/api/generated/initiativeAPI.schemas";

import { matchesTriggerRoute, splitIntoPages, validateTriggerRoute } from "./announcementPages";

const section = (heading: string, startsPage = false): AnnouncementSection => ({
  heading,
  starts_page: startsPage,
});

describe("splitIntoPages", () => {
  it.each([
    ["an unbroken list is one page", [section("a"), section("b")], [["a", "b"]]],
    [
      "breaks where a section says so",
      [section("a"), section("b", true), section("c")],
      [["a"], ["b", "c"]],
    ],
    [
      "opens with no empty page when the first breaks",
      [section("a", true), section("b")],
      [["a", "b"]],
    ],
    ["no sections, no pages", [], []],
  ])("%s", (_why, sections, expected) => {
    expect(splitIntoPages(sections).map((page) => page.map((s) => s.heading))).toEqual(expected);
  });
});

describe("matchesTriggerRoute", () => {
  // `*` is exactly one segment, `**` the rest of the path including none of it,
  // and a trailing slash on either side is ignored.
  it.each([
    ["/settings/platform", "/settings/platform", true],
    ["/settings/platform", "/settings", false],
    ["/settings/", "/settings", true],
    ["/settings", "/settings/", true],
    ["/c/*/settings", "/c/12/settings", true],
    ["/c/*/settings", "/c/12/34/settings", false],
    ["/c/*/settings", "/c/12/settings/users", false],
    ["/c/**", "/c/12/i/3/projects/9", true],
    ["/c/**", "/c", true],
    ["/c/**", "/settings", false],
    ["/c/*/i/*/projects/**", "/c/1/i/2/projects/3/tasks/4", true],
    ["/c/*/i/*/projects/**", "/c/1/i/2/files/3", false],
  ])("%s against %s is %s", (pattern, path, expected) => {
    expect(matchesTriggerRoute(pattern, path)).toBe(expected);
  });
});

describe("validateTriggerRoute", () => {
  it.each([
    // An empty field is fine: the trigger is optional.
    ["", null],
    ["   ", null],
    ["/settings/platform", null],
    ["/c/*/settings", null],
    ["/c/*/i/*/projects/**", null],
    ["c/*/settings", "needsSlash"],
    ["https://example.test/x", "needsSlash"],
    ["//example.test/x", "needsSlash"],
    ["/c/* /settings", "whitespace"],
    // A wildcard glued to a segment could never match.
    ["/c/*settings", "wildcardSegment"],
    ["/c/**/x**", "wildcardSegment"],
    ["/c/**/settings", "doubleStarNotLast"],
  ])("%j is %s", (pattern, expected) => {
    expect(validateTriggerRoute(pattern)).toBe(expected);
  });
});

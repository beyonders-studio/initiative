/**
 * What counts as a page in this app, for the three readers of `next`.
 */
import { describe, expect, it } from "vitest";

import { returnPath } from "@/lib/returnPath";

describe("the page a sign-in returns to", () => {
  it("keeps a path in this app, query and fragment and all", () => {
    expect(returnPath("/profile/security")).toBe("/profile/security");
    expect(returnPath("/c/1/search?q=riverside#top")).toBe("/c/1/search?q=riverside#top");
  });

  it.each([
    "//example.test/take-me",
    "/\\example.test/take-me",
    "https://example.test/take-me",
    "profile/security",
    // No trip to finish.
    undefined,
    null,
    "",
  ])("has nothing for %j", (next) => {
    expect(returnPath(next)).toBeNull();
  });
});

import { describe, expect, it } from "vitest";

import { pageTerms } from "./helpSearch";

describe("pageTerms", () => {
  it("names what a page holds, a parameter by what it holds", () => {
    expect(pageTerms("/c/$communityId/i/$initiativeId/")).toBe("community initiative");
    expect(pageTerms("/c/$communityId/i/$initiativeId/projects/$projectId")).toBe(
      "projects project"
    );
    expect(pageTerms("/c/$communityId/settings/members")).toBe("settings members");
    expect(pageTerms("/messages")).toBe("messages");
    expect(pageTerms("/")).toBe("");
  });
});

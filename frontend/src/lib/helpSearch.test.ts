import { describe, expect, it } from "vitest";

import { forPage, pageTerm } from "./helpSearch";

describe("pageTerm", () => {
  it("names what a page holds, a parameter by what it holds", () => {
    expect(pageTerm("/c/$communityId/i/$initiativeId/")).toBe("initiative");
    expect(pageTerm("/c/$communityId/i/$initiativeId/projects/$projectId")).toBe("project");
    expect(pageTerm("/c/$communityId/settings/members")).toBe("members");
    expect(pageTerm("/")).toBe("");
  });
});

describe("forPage", () => {
  const entry = (title: string, section = "") => ({ title, section, location: title, snippet: "" });

  it("keeps the entries that name the page", () => {
    expect(
      forPage(
        [entry("Projects and tasks"), entry("Inviting people", "Communities"), entry("Calendars")],
        "/c/$communityId/i/$initiativeId/projects/$projectId"
      ).map((found) => found.title)
    ).toEqual(["Projects and tasks"]);
  });
});

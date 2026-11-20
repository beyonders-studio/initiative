import { describe, expect, it } from "vitest";

import { chooseNoCommunityLayout, type NoCommunityLayoutChoice } from "./noCommunityLayout";

/**
 * The route gate this helper drives is an auth boundary: a wrong
 * answer either traps a user with zero memberships out of their own
 * account-management surface, or admits someone without platform access into the
 * platform shell. Tests here pin the truth table.
 */
describe("chooseNoCommunityLayout", () => {
  it.each<[string, boolean, string, boolean, NoCommunityLayoutChoice]>([
    // [why, hasCommunities, pathname, canAccessPlatformAreas, expected]
    ["a member gets the main layout whatever the path", true, "/profile", false, "main"],
    ["a member gets the main layout whatever the role", true, "/settings/operator", true, "main"],
    ["a member gets the main layout on content", true, "/projects/42", false, "main"],
    ["user settings, any role", false, "/profile", false, "shell"],
    ["user settings sub-paths", false, "/profile/danger", false, "shell"],
    // The trailing slash keeps a future refactor from silently widening the gate.
    ["not a partial-prefix collision with /profile", false, "/profilex", false, "empty"],
    ["the community directory, to join one", false, "/communities", false, "shell"],
    ["not a partial-prefix collision with /communities", false, "/communitiesx", false, "empty"],
    ["a community's billing link", false, "/c/7/billing", false, "shell"],
    ["nothing under the billing link", false, "/c/7/billing/x", false, "empty"],
    ["no billing link for a non-numeric community", false, "/c/x/billing", false, "empty"],
    ["no other community path", false, "/c/7/settings", false, "empty"],
    ["the operator dashboard with platform access", false, "/settings/operator", true, "shell"],
    ["below the operator dashboard", false, "/settings/operator/users", true, "shell"],
    ["platform settings", false, "/settings/platform/branding", true, "shell"],
    ["no operator dashboard without platform access", false, "/settings/operator", false, "empty"],
    ["no platform settings without access", false, "/settings/platform/branding", false, "empty"],
    ["the start flow at home", false, "/", false, "empty"],
    ["the start flow on content, whatever the role", false, "/projects/1", true, "empty"],
    ["the start flow on community settings", false, "/settings/security", true, "empty"],
  ])("%s", (_why, hasCommunities, pathname, canAccessPlatformAreas, expected) => {
    expect(chooseNoCommunityLayout({ hasCommunities, pathname, canAccessPlatformAreas })).toBe(
      expected
    );
  });

  it("asks to try again when the community list could not be read, where it would start over", () => {
    const failed = (hasCommunities: boolean, pathname: string) =>
      chooseNoCommunityLayout({
        hasCommunities,
        listFailed: true,
        pathname,
        canAccessPlatformAreas: false,
      });
    expect(failed(false, "/")).toBe("unavailable");
    expect(failed(false, "/profile")).toBe("shell");
    expect(failed(true, "/")).toBe("main");
  });
});

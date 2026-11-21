import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityRole } from "@/api/generated/initiativeAPI.schemas";

import { IndexPage } from "./IndexPage";

// `/settings` names no tab, so it opens the first one this person may open —
// never one that would turn them away.
describe("IndexPage", () => {
  it.each<[string, CommunityRole, string]>([
    ["the seat on Usage", "superadmin", "/c/4/settings/usage"],
    ["an ordinary admin, who cannot open Usage, on Community", "admin", "/c/4/settings/community"],
  ])("lands %s", async (_label, role, landing) => {
    const activeCommunity = buildCommunity({ id: 4, role });
    const { router } = renderPage(IndexPage, {
      auth: { user: buildUser() },
      communities: { communities: [activeCommunity], activeCommunity, activeCommunityId: 4 },
      initialRoute: "/c/$communityId/settings",
      routeParams: { communityId: "4" },
    });
    await waitFor(() => expect(router.state.location.pathname).toBe(landing));
  });
});

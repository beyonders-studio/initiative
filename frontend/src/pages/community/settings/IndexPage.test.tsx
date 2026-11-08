import { waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUser, communityCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityRole } from "@/api/generated/initiativeAPI.schemas";
import type { useAppConfig as useAppConfigType } from "@/hooks/useAppConfig";
import type { CommunityEntry } from "@/hooks/useCommunities";

let communityRole: CommunityRole = "superadmin";
let billing: { url: string } | null = null;

vi.mock(import("@/hooks/useAppConfig"), async (importOriginal) => ({
  ...(await importOriginal()),
  useAppConfig: () => ({ billing }) as unknown as ReturnType<typeof useAppConfigType>,
}));

// Partial: the render helper reaches for ``CommunityContext`` from this module.
vi.mock(import("@/hooks/useCommunities"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunities: () => {
    const activeCommunity: CommunityEntry = buildCommunity({
      id: 4,
      role: communityRole,
      can: communityCan(communityRole),
    });
    return {
      communities: [activeCommunity],
      activeCommunity,
      activeCommunityId: 4,
    } as unknown as ReturnType<typeof import("@/hooks/useCommunities").useCommunities>;
  },
}));

import { IndexPage } from "./IndexPage";

const landing = async () => {
  const { router } = renderPage(IndexPage, {
    auth: { user: buildUser() },
    initialRoute: "/c/$communityId/settings",
    routeParams: { communityId: "4" },
  });
  await waitFor(() => expect(router.state.location.pathname).not.toBe("/c/4/settings"));
  return router.state.location.pathname;
};

// `/settings` names no tab, so it opens the first one this person may open —
// never one that would turn them away.
describe("IndexPage", () => {
  beforeEach(() => {
    communityRole = "superadmin";
    billing = null;
  });

  it("lands the seat on Usage", async () => {
    expect(await landing()).toBe("/c/4/settings/usage");
  });

  it("lands the seat of a hosted install on Usage too", async () => {
    billing = { url: "https://billing.example.com" };
    expect(await landing()).toBe("/c/4/settings/usage");
  });

  it("lands an ordinary admin, who cannot open Usage, on Community", async () => {
    communityRole = "admin";
    expect(await landing()).toBe("/c/4/settings/community");
  });
});

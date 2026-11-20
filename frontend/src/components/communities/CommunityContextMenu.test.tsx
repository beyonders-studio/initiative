/**
 * Inviting members from a community's context menu, against the community's seat cap.
 *
 * The cap (`max_users`) and the current headcount (`member_count`) both ride
 * on the admin's own community payload, so the menu can tell a full community from a
 * roomy one without asking the server first.
 *
 * What a full community is offered depends on the deployment: self-hosted, the cap
 * is the operator's to lift; with a billing portal it comes with the plan, and
 * the item leads there instead.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, communityCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";

import { CommunityContextMenu } from "./CommunityContextMenu";

const mintInvite = vi.hoisted(() => vi.fn());
const mintHandoff = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/communities/communities", () => ({
  createCommunityInvite: mintInvite,
  createCommunityBillingHandoff: mintHandoff,
}));

// Null billing is the self-hosted deployment; a test opts into the portal.
const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: state.billing }) }));

const setup = (overrides: Partial<CommunityRead>) => {
  const community = buildCommunity({
    role: "superadmin",
    name: "Alpha",
    ...overrides,
  }) as CommunityRead;
  renderPage(
    () => (
      <CommunityContextMenu community={community}>
        <button type="button">Alpha</button>
      </CommunityContextMenu>
    ),
    { communities: { communities: [], activeCommunityId: community.id } }
  );
  return community;
};

const openMenu = async () => {
  fireEvent.contextMenu(await screen.findByRole("button", { name: "Alpha" }));
};

describe("CommunityContextMenu invite action", () => {
  beforeEach(() => {
    state.billing = null;
    mintInvite.mockReset();
    mintHandoff.mockReset();
  });

  it.each([
    ["while a seat is free", 3, 2],
    ["when the community has no cap at all", null, 42],
  ])("offers the invite action %s", async (_label, max_users, member_count) => {
    setup({ max_users, member_count });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");
  });

  it("disables it, and says why, once every seat is taken", async () => {
    setup({ max_users: 2, member_count: 2 });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members (community full)" });
    expect(item).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(item);
    expect(mintInvite).not.toHaveBeenCalled();
  });

  it("sends a full community to the billing portal where one is configured", async () => {
    state.billing = { url: "https://billing.example.com" };
    mintHandoff.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const community = setup({ id: 42, max_users: 1, member_count: 1 });

    await openMenu();
    const item = await screen.findByRole("menuitem", { name: "Upgrade to invite members" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");

    fireEvent.click(item);

    expect(mintInvite).not.toHaveBeenCalled();
    await waitFor(() => expect(mintHandoff).toHaveBeenCalledWith(community.id));
    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/upgrade?lang=en#handoff=TOK")
    );
    openSpy.mockRestore();
  });
});

describe("CommunityContextMenu billing action", () => {
  beforeEach(() => {
    state.billing = null;
    mintHandoff.mockReset();
  });

  it("opens the billing portal for the seat of a hosted install", async () => {
    state.billing = { url: "https://billing.example.com" };
    mintHandoff.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    setup({ id: 42 });

    await openMenu();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Manage billing" }));

    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/manage?lang=en#handoff=TOK")
    );
    openSpy.mockRestore();
  });

  const grantee = (configure: boolean) =>
    ({
      accessType: "grant",
      grantSettingsLevel: "superadmin",
      can: communityCan("superadmin", { configure }),
    }) as Partial<CommunityRead>;

  it.each([
    ["on a self-hosted install", null, {}, false],
    ["to support holding the seat with write access", true, grantee(true), true],
    ["to support whose grant only reads", true, grantee(false), false],
    ["to an ordinary admin", true, { role: "admin", can: communityCan("admin") }, false],
  ] as const)("is offered %s: %s", async (_label, hosted, overrides, offered) => {
    state.billing = hosted ? { url: "https://billing.example.com" } : null;
    setup({ id: 42, ...overrides });

    await openMenu();
    expect(await screen.findByRole("menuitem", { name: /settings/i })).toBeInTheDocument();
    expect(Boolean(screen.queryByRole("menuitem", { name: "Manage billing" }))).toBe(offered);
  });
});

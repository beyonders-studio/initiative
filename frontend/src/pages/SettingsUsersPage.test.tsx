/**
 * The seat-cap notice on Settings › Users.
 *
 * A full community mints no invite, and what the admin can do about it depends on
 * the deployment: self-hosted, the cap is the operator's to lift, so the copy
 * says to ask one. Where a billing portal exists the cap comes with the plan —
 * no operator is reachable to raise it — so the notice names the plan and
 * offers the way to change it.
 */
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUserCommunityMember } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  CommunityAuthOption,
  CommunityInviteRead,
  CommunityRead,
  UserCommunityMember,
} from "@/api/generated/initiativeAPI.schemas";

const state = vi.hoisted(() => ({
  billing: null as { url: string } | null,
  members: [] as UserCommunityMember[],
  authOptions: [] as CommunityAuthOption[],
  invites: [] as CommunityInviteRead[],
}));
vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: state.billing }) }));

const mintHandoff = vi.hoisted(() => vi.fn());
const listInvites = vi.hoisted(() => vi.fn());
const createInvite = vi.hoisted(() => vi.fn());
const deleteInvite = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/communities/communities", () => ({
  createCommunityInvite: createInvite,
  deleteCommunityInvite: deleteInvite,
  useListCommunityInvites: (communityId: number, options?: { query?: { enabled?: boolean } }) => {
    if (options?.query?.enabled !== false) listInvites(communityId);
    return { data: state.invites, isLoading: false, isError: false, refetch: vi.fn() };
  },
  createCommunityBillingHandoff: mintHandoff,
}));

const setApiAccess = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useUsers", () => ({
  USER_ID_LOOKUP_MAX: 100,
  useUsers: () => ({
    data: {
      items: state.members,
      total_count: state.members.length,
      page: 1,
      page_size: 20,
      has_next: false,
      has_prev: false,
    },
    isLoading: false,
    isError: false,
  }),
  useSetMemberApiAccess: () => ({ mutate: setApiAccess, isPending: false }),
  useUserSearch: () => ({ data: undefined, isFetching: false }),
  useUpdateCommunityMembership: () => ({ mutate: vi.fn() }),
  useSetMemberDisplayName: () => ({ mutate: vi.fn(), isPending: false }),
  useExportCommunityUsersCsv: () => ({ mutate: vi.fn() }),
}));

vi.mock("@/hooks/useCommunityAuthPolicy", () => ({
  useCommunityAuthSettings: () => ({ data: { auth_options: state.authOptions } }),
}));

vi.mock("@/components/communities/UnownedContentCard", () => ({ UnownedContentCard: () => null }));

import { SettingsUsersPage } from "./SettingsUsersPage";

beforeEach(() => {
  state.invites = [];
});

// The page's last render, whose reads are waited on before clicking into a
// table row: each read that lands redraws the rows.
let rendered: ReturnType<typeof renderPage>;
const settled = () => waitFor(() => expect(rendered.queryClient.isFetching()).toBe(0));

const setup = (overrides: Partial<CommunityRead>) => {
  const community = buildCommunity({
    role: "superadmin",
    name: "Alpha",
    ...overrides,
  }) as CommunityRead;
  rendered = renderPage(() => <SettingsUsersPage />, {
    communities: {
      communities: [community],
      activeCommunityId: community.id,
      activeCommunity: community,
    },
  });
  return community;
};

describe("SettingsUsersPage seat cap", () => {
  beforeEach(() => {
    state.billing = null;
    mintHandoff.mockReset();
  });

  it("points a self-hosted community admin at whoever runs the server", async () => {
    setup({ max_users: 2, member_count: 2 });

    expect(
      await screen.findByText(/ask whoever runs this server to raise the limit/i)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upgrade" })).not.toBeInTheDocument();
  });

  it("names the plan and offers the portal when billing is configured", async () => {
    state.billing = { url: "https://billing.example.com" };
    mintHandoff.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const community = setup({ id: 42, max_users: 1, member_count: 1, tier_name: "starter" });

    expect(
      await screen.findByText(/The starter plan includes a single seat, and it's taken/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/ask whoever runs this server/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Upgrade" }));

    await waitFor(() => expect(mintHandoff).toHaveBeenCalledWith(community.id));
    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/upgrade?lang=en#handoff=TOK")
    );
    openSpy.mockRestore();
  });

  it("falls back to plan-free wording when the community carries no plan name", async () => {
    state.billing = { url: "https://billing.example.com" };
    setup({ max_users: 5, member_count: 5, tier_name: null });

    expect(await screen.findByText(/All 5 seats on your plan are in use/i)).toBeInTheDocument();
  });

  it("says nothing about seats while one is free", async () => {
    setup({ max_users: 5, member_count: 2 });

    await screen.findByRole("button", { name: "Generate invite" });
    expect(screen.queryByText(/seats/i)).not.toBeInTheDocument();
  });
});

describe("SettingsUsersPage roles", () => {
  beforeEach(() => {
    state.billing = null;
  });

  it("explains what each role is, where the choice is made", async () => {
    setup({});

    expect(await screen.findByText(/runs the community/i)).toBeInTheDocument();
    expect(screen.getByText(/plus how people get in/i)).toBeInTheDocument();
  });

  it("offers the seat only to somebody already holding it", async () => {
    setup({});
    expect(await screen.findByText("Superadmin")).toBeInTheDocument();

    cleanup();
    setup({ role: "admin" });
    // The rung below neither appoints the seat nor takes it away, so it is
    // not on the list it is offered.
    expect(await screen.findByText("Admin")).toBeInTheDocument();
    expect(screen.queryByText("Superadmin")).not.toBeInTheDocument();
  });
});

describe("SettingsUsersPage invites", () => {
  it("leaves invites out for a rung that reads the roster", async () => {
    const community = buildCommunity({ role: "admin" }) as CommunityRead;
    setup({ role: "admin", can: { ...community.can, configure: false } });

    expect(await screen.findByText("Admin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate invite" })).not.toBeInTheDocument();
    expect(listInvites).not.toHaveBeenCalled();
  });

  it("shows a new invite's link once, until the invite is deleted", async () => {
    const community = setup({});
    const invite = {
      id: 7,
      community_id: community.id,
      created_by: null,
      expires_at: null,
      max_uses: 1,
      uses: 0,
      invitee_email: null,
      created_at: new Date().toISOString(),
      guest_days: null,
      grants: [],
    };
    createInvite.mockImplementation(async () => {
      state.invites = [invite];
      return { ...invite, code: "fresh-code" };
    });

    await userEvent.click(await screen.findByRole("button", { name: "Generate invite" }));

    expect(await screen.findByText(/\/invite\/fresh-code$/)).toBeInTheDocument();
    expect(screen.getByText("Invite link")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete invite" }));

    await waitFor(() => expect(screen.queryByText(/fresh-code/)).not.toBeInTheDocument());
    expect(deleteInvite).toHaveBeenCalledWith(community.id, 7);
  });

  it("leaves guest invites to the Guests tab", async () => {
    state.invites = [
      {
        id: 8,
        community_id: 1,
        created_by: null,
        expires_at: null,
        max_uses: 1,
        uses: 0,
        invitee_email: null,
        created_at: new Date().toISOString(),
        guest_days: 5,
        grants: [],
      },
    ];
    setup({});

    expect(await screen.findByText("No active invites.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete invite" })).not.toBeInTheDocument();
  });
});

describe("SettingsUsersPage API access", () => {
  const apiSwitch = () => screen.queryByRole("switch", { name: /personal api keys for/i });

  beforeEach(() => {
    state.billing = null;
    state.members = [buildUserCommunityMember({ api_keys_allowed: true })];
    state.authOptions = ["restrictions"];
    setApiAccess.mockReset();
  });

  it("lets the seat turn one member's API access off", async () => {
    const community = setup({});
    const member = state.members[0];

    // The page's reads land and redraw it; click the switch that stays.
    await screen.findByRole("button", { name: "Generate invite" });
    await settled();
    await userEvent.click(screen.getByRole("switch", { name: /personal api keys for/i }));

    expect(setApiAccess).toHaveBeenCalledWith({
      communityId: community.id,
      userId: member.id,
      allowed: false,
    });
  });

  it("is the seat's, not an ordinary admin's", async () => {
    setup({ role: "admin" });

    await screen.findByText("Admin");
    expect(apiSwitch()).not.toBeInTheDocument();
  });

  it("is not offered while the community does not hold restrictions", async () => {
    state.authOptions = ["providers"];
    setup({});

    await screen.findByText("Superadmin");
    expect(apiSwitch()).not.toBeInTheDocument();
  });
});

describe("SettingsUsersPage custom roles", () => {
  beforeEach(() => {
    state.billing = null;
    state.authOptions = [];
  });

  it("gives a member one of the community's custom roles", async () => {
    state.members = [buildUserCommunityMember({ display_name: "Ada" })];
    const member = state.members[0];
    const assigned: { userId: string; body: unknown }[] = [];
    server.use(
      communityHttp.get("/custom-roles/", () =>
        HttpResponse.json([{ id: 3, name: "Greeter", base_rung: "member", surfaces: ["invites"] }])
      ),
      communityHttp.put("/custom-roles/holders/:userId", async ({ request, params }) => {
        assigned.push({ userId: String(params.userId), body: await request.json() });
        return new HttpResponse(null, { status: 204 });
      })
    );
    setup({ role: "admin" });

    await screen.findByRole("combobox", { name: /custom role for/i });
    await settled();
    await userEvent.click(screen.getByRole("combobox", { name: /custom role for/i }));
    await userEvent.click(await screen.findByRole("option", { name: "Greeter" }));

    await waitFor(() =>
      expect(assigned).toEqual([{ userId: String(member.id), body: { role_id: 3 } }])
    );
  });
});

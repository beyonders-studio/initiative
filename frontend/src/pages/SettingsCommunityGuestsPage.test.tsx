import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative, buildUserCommunityMember } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  CommunityInviteRead,
  CommunityRead,
  SearchSuggestion,
  UserCommunityMember,
} from "@/api/generated/initiativeAPI.schemas";

const state = vi.hoisted(() => ({
  guests: [] as UserCommunityMember[],
  invites: [] as CommunityInviteRead[],
}));

vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ guestsEnabled: true }) }));

const createInvite = vi.hoisted(() => vi.fn());
const extendGuest = vi.hoisted(() => vi.fn());
vi.mock(import("@/api/generated/communities/communities"), async (importOriginal) => ({
  ...(await importOriginal()),
  createCommunityInvite: createInvite,
  extendCommunityGuest: extendGuest,
  useListCommunityInvites: (() => ({
    data: state.invites,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  })) as never,
}));

const listUsers = vi.hoisted(() => vi.fn());
vi.mock(import("@/hooks/useUsers"), async (importOriginal) => ({
  ...(await importOriginal()),
  useUsers: ((params: unknown) => {
    listUsers(params);
    return {
      data: {
        items: state.guests,
        total_count: state.guests.length,
        page: 1,
        page_size: 20,
        has_next: false,
        has_prev: false,
      },
      isLoading: false,
      isError: false,
    };
  }) as never,
}));

vi.mock(import("@/hooks/useInitiatives"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunityInitiatives: (() => ({
    data: [buildInitiative({ id: 3, name: "Launch" })],
  })) as never,
}));

const roadmap: SearchSuggestion = {
  entity_type: "project",
  entity_id: 21,
  title: "Roadmap",
  initiative_id: 3,
  initiative_name: "Launch",
};
vi.mock(import("@/hooks/useSearch"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunityPickerSuggestions: () => ({
    items: [roadmap],
    searched: false,
    stale: false,
    isLoading: false,
    isFetching: false,
  }),
}));

import { SettingsCommunityGuestsPage } from "./SettingsCommunityGuestsPage";

// The page's last render, whose reads are waited on before clicking into a
// table row: each read that lands redraws the rows.
let rendered: ReturnType<typeof renderPage>;

const setup = () => {
  const community = buildCommunity({ role: "admin" }) as CommunityRead;
  rendered = renderPage(() => <SettingsCommunityGuestsPage />, {
    communities: {
      communities: [community],
      activeCommunityId: community.id,
      activeCommunity: community,
    },
  });
  return community;
};

beforeEach(() => {
  state.guests = [];
  state.invites = [];
  createInvite.mockReset();
  extendGuest.mockReset();
  listUsers.mockReset();
});

describe("SettingsCommunityGuestsPage", () => {
  it("lists the guests with when their time ends", async () => {
    state.guests = [
      buildUserCommunityMember({
        username: "visitor",
        guest_until: new Date(Date.now() + (3 * 24 + 1) * 60 * 60 * 1000).toISOString(),
      }),
    ];
    setup();

    expect(await screen.findByText("visitor")).toBeInTheDocument();
    expect(screen.getByText("in 3 days")).toBeInTheDocument();
    expect(listUsers).toHaveBeenCalledWith(expect.objectContaining({ guests: true }));
  });

  it("makes a guest invite with its days and what it gives, and shows the link once", async () => {
    const user = userEvent.setup();
    const community = setup();
    createInvite.mockResolvedValue({ id: 9, code: "guest-code" });

    const days = await screen.findByLabelText("Days the guest stays");
    await user.clear(days);
    await user.type(days, "5");

    await user.click(screen.getByLabelText("Initiatives they join"));
    await user.click(await screen.findByRole("button", { name: "Select all" }));
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("combobox", { name: "Thing" }));
    await user.click(await screen.findByText("Roadmap"));
    await user.click(screen.getByRole("combobox", { name: "Access to Roadmap" }));
    await user.click(await screen.findByRole("option", { name: "Editor" }));

    await user.click(screen.getByRole("button", { name: "Generate guest invite" }));

    await waitFor(() =>
      expect(createInvite).toHaveBeenCalledWith(community.id, {
        max_uses: 1,
        expires_at: expect.any(String),
        guest_days: 5,
        grants: [
          { initiative_id: 3 },
          { initiative_id: 3, resource_type: "project", resource_id: 21, level: "write" },
        ],
      })
    );
    expect(await screen.findByText(/\/invite\/guest-code$/)).toBeInTheDocument();
  });

  it("extends a guest's time", async () => {
    const user = userEvent.setup();
    const guest = buildUserCommunityMember({
      username: "visitor",
      guest_until: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    });
    state.guests = [guest];
    const community = setup();
    extendGuest.mockResolvedValue(undefined);

    await screen.findByRole("button", { name: /actions for/i });
    await waitFor(() => expect(rendered.queryClient.isFetching()).toBe(0));
    await user.click(screen.getByRole("button", { name: /actions for/i }));
    await user.click(await screen.findByRole("menuitem", { name: "Extend" }));
    const days = await screen.findByLabelText("Days from now");
    await user.clear(days);
    await user.type(days, "14");
    await user.click(screen.getByRole("button", { name: "Extend" }));

    await waitFor(() =>
      expect(extendGuest).toHaveBeenCalledWith(community.id, guest.id, { days: 14 })
    );
  });
});

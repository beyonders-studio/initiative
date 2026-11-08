/**
 * The transfer dialog offers the community's admins, and beside them the
 * installed plug-ins the server says may own everything that moves.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUserCommunityMember, buildUserSummary } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { OwnedContentResponse } from "@/api/generated/initiativeAPI.schemas";

const api = vi.hoisted(() => ({
  listOwned: vi.fn(),
  listUnowned: vi.fn(),
  transfer: vi.fn(),
  claim: vi.fn(),
}));

vi.mock("@/api/generated/users/users", () => ({
  listOwnedContent: api.listOwned,
  listUnownedContent: api.listUnowned,
  transferOwnership: api.transfer,
  claimUnownedContent: api.claim,
}));

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 7 }));

// The community's members matching the search: the dialog offers the admins among them.
const search = vi.hoisted(() => ({ items: [] as unknown[] }));
vi.mock("@/hooks/useUsers", () => ({
  USER_ID_LOOKUP_MAX: 100,
  useUserSearch: () => ({ data: { items: search.items }, isFetching: false }),
}));

import { TransferContentOwnershipDialog } from "./TransferContentOwnershipDialog";

const admin = buildUserSummary({ id: 11, display_name: "Ada Admin", community_role: "admin" });
const member = buildUserCommunityMember({ id: 12, display_name: "Mel Member" });
search.items = [
  admin,
  buildUserSummary({ id: 12, display_name: "Mel Member", community_role: "member" }),
];

const content = (overrides: Partial<OwnedContentResponse> = {}): OwnedContentResponse => ({
  items: [{ tool: "project", id: 5, name: "Roadmap" }],
  counts: { project: 1 },
  total: 1,
  eligible_plugins: [],
  ...overrides,
});

describe("TransferContentOwnershipDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.transfer.mockResolvedValue({ counts: { project: 1 }, total: 1 });
    api.claim.mockResolvedValue({ counts: { project: 1 }, total: 1 });
  });

  it("offers a plug-in the server lists and hands the content to it", async () => {
    api.listOwned.mockResolvedValue(
      content({ eligible_plugins: [{ id: 301, name: "Automations", avatar_url: null }] })
    );

    renderWithProviders(
      <TransferContentOwnershipDialog open onOpenChange={vi.fn()} member={member} />
    );

    await userEvent.click(await screen.findByRole("combobox"));
    expect(await screen.findByRole("option", { name: "Ada Admin" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Mel Member" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: /Automations/ }));
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() =>
      expect(api.transfer).toHaveBeenCalledWith(7, member.id, { new_owner_plugin_id: 301 })
    );
  });

  it("offers only admins when no plug-in may own it, and names a person by id", async () => {
    api.listUnowned.mockResolvedValue(content());

    renderWithProviders(
      <TransferContentOwnershipDialog
        open
        onOpenChange={vi.fn()}
        member={null}
        defaultRecipient={admin}
      />
    );

    await userEvent.click(await screen.findByRole("combobox", { name: "New owner" }));
    expect(await screen.findByRole("option", { name: "Ada Admin" })).toBeInTheDocument();
    expect(screen.queryByText("Plug-in")).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() => expect(api.claim).toHaveBeenCalledWith(7, { new_owner_id: admin.id }));
  });
});

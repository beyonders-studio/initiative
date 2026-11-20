import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, communityCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityEntry } from "@/hooks/useCommunities";

const state = vi.hoisted(() => ({
  billing: null as { url: string } | null,
  // The phone app, where nothing may be sold.
  native: false,
  support: { mode: "none", contact: null } as { mode: string; contact: string | null } | undefined,
}));
const askMock = vi.hoisted(() => vi.fn());
const openPortalMock = vi.hoisted(() => vi.fn());
const openHelpMock = vi.hoisted(() => vi.fn());
vi.mock("@/components/help/helpStore", () => ({ openHelp: openHelpMock }));

vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({
    billing: state.billing,
    canSell: state.billing != null && !state.native,
    openPortal: openPortalMock,
  }),
}));
vi.mock("@/hooks/useTickets", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets");
  return {
    ...actual,
    useTicketAvailability: () => ({
      data: state.support && { support: state.support, moderation: state.support },
      isPending: false,
    }),
  };
});
vi.mock("@/api/generated/communities/communities", () => ({
  getReadCommunityPaymentIssueQueryKey: (id: number) => [
    `/api/v1/communities/${id}/billing/payment-issue`,
  ],
  readCommunityPaymentIssue: askMock,
}));

import { CommunityStatusNotice, communityStatusNoticeApplies } from "./CommunityStatusNotice";

const seatCommunity = (overrides: Partial<CommunityEntry> = {}): CommunityEntry =>
  ({
    ...buildCommunity({ id: 7, name: "Acme", role: "superadmin", status: "read_only" }),
    ...overrides,
  }) as CommunityEntry;

describe("communityStatusNoticeApplies", () => {
  it("applies to the seat of a read-only community", () => {
    expect(communityStatusNoticeApplies(seatCommunity())).toBe(true);
  });

  it("does not apply to an active or suspended community, an admin, or a grant", () => {
    expect(communityStatusNoticeApplies(seatCommunity({ status: "active" }))).toBe(false);
    // A suspended community is closed rather than noticed: its seat reaches nothing in it.
    expect(communityStatusNoticeApplies(seatCommunity({ status: "suspended" }))).toBe(false);
    expect(
      communityStatusNoticeApplies(seatCommunity({ role: "admin", can: communityCan("admin") }))
    ).toBe(false);
    expect(communityStatusNoticeApplies(seatCommunity({ accessType: "grant" }))).toBe(false);
  });
});

describe("CommunityStatusNotice", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    state.native = false;
    state.billing = null;
    state.support = { mode: "none", contact: null };
    askMock.mockReset();
    openPortalMock.mockReset();
  });

  it("shows the default notice and asks nothing when no portal is configured", async () => {
    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
    expect(screen.getByText("Contact your platform operator.")).toBeInTheDocument();
    expect(askMock).not.toHaveBeenCalled();
    // Help is off, so only OK.
    expect(screen.getByRole("button", { name: "OK" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Contact support" })).toBeNull();
  });

  it("offers to update the card when the payment was declined", async () => {
    state.billing = { url: "https://billing.example.com" };
    askMock.mockResolvedValue({ payment_failed: true });
    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    expect(await screen.findByText("The payment for Acme was declined")).toBeInTheDocument();
    expect(screen.queryByText("Something is wrong")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Update payment method" }));
    expect(openPortalMock).toHaveBeenCalledWith(7, "manage");
  });

  it("says the payment was declined in the app without offering to fix it there", async () => {
    state.billing = { url: "https://billing.example.com" };
    state.native = true;
    askMock.mockResolvedValue({ payment_failed: true });
    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    expect(await screen.findByText("The payment for Acme was declined")).toBeInTheDocument();
    expect(screen.getByText("Payment details can't be changed in the app.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update payment method" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(openPortalMock).not.toHaveBeenCalled();
  });

  it.each([
    ["the payment is not the problem", () => askMock.mockResolvedValue({ payment_failed: false })],
    ["the question fails", () => askMock.mockRejectedValue(new Error("unreachable"))],
  ])("falls back to the default notice when %s", async (_label, answer) => {
    state.billing = { url: "https://billing.example.com" };
    answer();
    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update payment method" })).toBeNull();
  });

  it("asks the team about this community when help is on", async () => {
    state.support = { mode: "form", contact: null };
    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Contact support" }));
    expect(openHelpMock).toHaveBeenCalledWith({ topic: "community", communityId: 7 });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("opens Help, with the address the deployment gave, when it takes no requests", async () => {
    state.support = { mode: "email", contact: "help@example.org" };
    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Contact support" }));
    expect(openHelpMock).toHaveBeenCalledWith();
  });

  it("shows once per community in a session, and again in a new one", async () => {
    const first = renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    await userEvent.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(screen.queryByText("Something is wrong")).toBeNull());
    first.unmount();

    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    expect(screen.queryByText("Something is wrong")).toBeNull();

    const other = renderWithProviders(
      <CommunityStatusNotice community={seatCommunity({ id: 8 })} />
    );
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
    other.unmount();

    // And again in a new browser session.
    window.sessionStorage.clear();
    renderWithProviders(<CommunityStatusNotice community={seatCommunity()} />);
    expect(await screen.findByText("Something is wrong")).toBeInTheDocument();
  });
});

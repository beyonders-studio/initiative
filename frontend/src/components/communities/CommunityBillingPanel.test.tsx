import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, communityCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityBillingSummaryRead } from "@/api/generated/initiativeAPI.schemas";
import { dateTimeFormat } from "@/lib/intl";

// Mutable state the mocked hooks read, so each test can vary billing config,
// the active community, and what the summary route answered.
const state = vi.hoisted(() => ({
  community: null as ReturnType<typeof Object> | null,
  billing: null as { url: string } | null,
  summary: undefined as CommunityBillingSummaryRead | undefined,
  summaryError: false,
}));

vi.mock("@/hooks/useCommunities", async () => {
  const actual =
    await vi.importActual<typeof import("@/hooks/useCommunities")>("@/hooks/useCommunities");
  // Keep CommunityContext (the render helper's provider imports it); override the hook.
  return { ...actual, useCommunities: () => ({ activeCommunity: state.community }) };
});
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: state.billing }),
}));
const mintMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/communities/communities", () => ({
  createCommunityBillingHandoff: mintMock,
}));
// Who is asked, and when, is the hook's (useCommunityBillingSummary.test.tsx);
// this is what the panel makes of the answer.
vi.mock("@/hooks/useCommunityBillingSummary", () => ({
  useCommunityBillingSummary: () => ({ data: state.summary, isError: state.summaryError }),
}));

import { asPhoneThatMayNotSell } from "@/__tests__/helpers/storeSelling";

import { CommunityBillingPanel } from "./CommunityBillingPanel";

const EMPTY: CommunityBillingSummaryRead = {
  available: true,
  tier_name: null,
  trial_ends_on: null,
  renews_on: null,
  next_charge: null,
  scheduled_change: null,
  payment_failed: false,
  can_upgrade: true,
  can_cancel: false,
};

const CANCEL_NOTE = /read-only for 30 days so you can export it, then put on hold and deleted/;

/** A local calendar day `days` from today, as the API sends a DATE. */
const dayFromToday = (days: number): string => {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const longDate = (value: string): string => {
  const [y, m, d] = value.split("-").map(Number);
  return dateTimeFormat("en", { dateStyle: "long" }).format(new Date(y, m - 1, d));
};

describe("CommunityBillingPanel", () => {
  beforeEach(() => {
    state.community = buildCommunity({ id: 42, role: "superadmin", tier_name: "Tin" });
    state.billing = { url: "https://billing.example.com" };
    state.summary = { ...EMPTY };
    state.summaryError = false;
    mintMock.mockReset();
  });

  it("renders nothing without a billing portal", () => {
    state.billing = null;
    const { container } = renderWithProviders(<CommunityBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows support the plan when they hold the seat with write access", () => {
    // A superadmin settings grant beside a read_write content grant: what
    // support does with it happens in the billing portal, under its controls.
    state.community = {
      ...buildCommunity({
        id: 42,
        role: "superadmin",
        can: communityCan("superadmin", { configure: true }),
      }),
      accessType: "grant",
      grantSettingsLevel: "superadmin",
    };
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText("Plan")).toBeInTheDocument();
  });

  it("renders nothing for support whose grant only reads", () => {
    state.community = {
      ...buildCommunity({
        id: 42,
        role: "superadmin",
        can: communityCan("superadmin", { configure: false }),
      }),
      accessType: "grant",
      grantSettingsLevel: "superadmin",
    };
    const { container } = renderWithProviders(<CommunityBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a seat whose session only reads", () => {
    state.community = buildCommunity({
      id: 42,
      role: "superadmin",
      can: communityCan("superadmin", { configure: false }),
    });
    const { container } = renderWithProviders(<CommunityBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an ordinary admin", () => {
    state.community = buildCommunity({ id: 42, role: "admin" });
    const { container } = renderWithProviders(<CommunityBillingPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows just the plan name on a free plan, with plans above it and nothing to cancel", () => {
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText("Tin")).toBeInTheDocument();
    expect(screen.queryByText(/Renews|Trial|Ends|Payment failed/)).not.toBeInTheDocument();
    expect(screen.getByText("Upgrade")).toBeInTheDocument();
    expect(screen.getByText("Manage billing")).toBeInTheDocument();
    expect(screen.queryByText(CANCEL_NOTE)).not.toBeInTheDocument();
    expect(screen.getByText(/Change your plan or payment method/)).toBeInTheDocument();
  });

  it("offers no upgrade and no cancel on the top plan", () => {
    state.summary = { ...EMPTY, tier_name: "Enterprise", can_upgrade: false };
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText("Enterprise")).toBeInTheDocument();
    expect(screen.queryByText("Upgrade")).not.toBeInTheDocument();
    expect(screen.getByText("Manage billing")).toBeInTheDocument();
    expect(screen.queryByText(CANCEL_NOTE)).not.toBeInTheDocument();
  });

  it("shows when a running trial ends", () => {
    const end = dayFromToday(3);
    state.summary = { ...EMPTY, tier_name: "Gold", trial_ends_on: end };
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText("Gold")).toBeInTheDocument();
    expect(
      screen.getByText(`Trial ends on ${longDate(end)}; billing starts then.`)
    ).toBeInTheDocument();
  });

  it("says so on a trial's last day", () => {
    const end = dayFromToday(0);
    state.summary = { ...EMPTY, trial_ends_on: end };
    renderWithProviders(<CommunityBillingPanel />);
    expect(
      screen.getByText(`Trial ends on ${longDate(end)}; billing starts then.`)
    ).toBeInTheDocument();
  });

  it("shows the renewal date and amount in the currency's own units", () => {
    const renews = dayFromToday(20);
    state.summary = {
      ...EMPTY,
      tier_name: "Gold",
      renews_on: renews,
      next_charge: { total: 1250, currency: "USD" },
      can_cancel: true,
    };
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText(`Renews ${longDate(renews)} · $12.50`)).toBeInTheDocument();
    // A card subscription is running, so the portal can cancel it.
    expect(screen.getByText(CANCEL_NOTE)).toBeInTheDocument();
  });

  it("reads minor units by the currency's fraction digits", () => {
    const renews = dayFromToday(20);
    state.summary = { ...EMPTY, renews_on: renews, next_charge: { total: 1200, currency: "JPY" } };
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText(`Renews ${longDate(renews)} · ¥1,200`)).toBeInTheDocument();
  });

  it("shows a scheduled cancelation over the renewal", () => {
    const ends = dayFromToday(20);
    state.summary = {
      ...EMPTY,
      renews_on: ends,
      next_charge: { total: 1250, currency: "USD" },
      scheduled_change: { action: "cancel", on: ends },
    };
    renderWithProviders(<CommunityBillingPanel />);
    expect(
      screen.getByText(
        `Your plan ends on ${longDate(ends)}. After that the community is read-only for 30 days, then put on hold.`
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/Renews/)).not.toBeInTheDocument();
  });

  it("puts a failed payment first and sends the seat to fix it", async () => {
    state.summary = {
      ...EMPTY,
      renews_on: dayFromToday(20),
      next_charge: { total: 1250, currency: "USD" },
      payment_failed: true,
    };
    mintMock.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText("Payment failed")).toBeInTheDocument();
    expect(screen.getByText(/read-only 14 days after the payment failed/)).toBeInTheDocument();
    expect(screen.queryByText(/Renews/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Update payment method"));

    expect(mintMock).toHaveBeenCalledWith(42);
    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/manage?lang=en#handoff=TOK")
    );
    openSpy.mockRestore();
  });

  it("shows the plan in the phone app without anything to buy", () => {
    asPhoneThatMayNotSell();
    const phone = { server: { isNativePlatform: true } };
    const trialEnd = dayFromToday(3);
    state.summary = { ...EMPTY, tier_name: "Gold", trial_ends_on: trialEnd };
    const { unmount } = renderWithProviders(<CommunityBillingPanel />, phone);
    expect(screen.getByText("Gold")).toBeInTheDocument();
    expect(
      screen.getByText(`Trial ends on ${longDate(trialEnd)}; billing starts then.`)
    ).toBeInTheDocument();
    expect(screen.getByText("Plan changes aren't available in the app.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/billing portal|Subscribe/)).toBeNull();
    unmount();

    // A renewal names no amount, and a failed payment asks for no card.
    const renews = dayFromToday(20);
    state.summary = {
      ...EMPTY,
      renews_on: renews,
      next_charge: { total: 1250, currency: "USD" },
    };
    const renewal = renderWithProviders(<CommunityBillingPanel />, phone);
    expect(screen.getByText(`Renews ${longDate(renews)}`)).toBeInTheDocument();
    expect(screen.queryByText(/\$12\.50/)).toBeNull();
    renewal.unmount();

    state.summary = { ...EMPTY, payment_failed: true };
    renderWithProviders(<CommunityBillingPanel />, phone);
    expect(
      screen.getByText("The community becomes read-only 14 days after the payment failed.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(mintMock).not.toHaveBeenCalled();
  });

  it("says billing is unavailable, and still offers the portal", () => {
    state.summary = { ...EMPTY, available: false };
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText("Billing details are unavailable right now.")).toBeInTheDocument();
    // The plan name falls back to what the community itself carries.
    expect(screen.getByText("Tin")).toBeInTheDocument();
    expect(screen.getByText("Manage billing")).toBeInTheDocument();
  });

  it("treats a refused summary as unavailable", () => {
    state.summary = undefined;
    state.summaryError = true;
    renderWithProviders(<CommunityBillingPanel />);
    expect(screen.getByText("Billing details are unavailable right now.")).toBeInTheDocument();
  });

  it("falls back to the anonymous link if the mint fails", async () => {
    mintMock.mockRejectedValue(new Error("nope"));
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    renderWithProviders(<CommunityBillingPanel />);
    await userEvent.click(screen.getByText("Upgrade"));

    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/upgrade?lang=en")
    );
    openSpy.mockRestore();
  });
});

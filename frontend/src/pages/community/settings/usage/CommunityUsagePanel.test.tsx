import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, communityCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityEntry } from "@/hooks/useCommunities";

// Mutable state the mocked hooks read, so each test can vary billing config,
// the active community, and the storage-usage response.
const state = vi.hoisted(() => ({
  community: null as unknown as CommunityEntry,
  billing: null as { url: string } | null,
  guestsEnabled: true,
  usage: { usage_bytes: 0 } as { usage_bytes: number } | undefined,
  usageError: false,
  usageEnabled: [] as boolean[],
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: state.billing, guestsEnabled: state.guestsEnabled }),
}));
vi.mock("@/api/generated/storage/storage", () => ({
  useReadStorageUsage: (_communityId: number, options: { query: { enabled: boolean } }) => {
    state.usageEnabled.push(options.query.enabled);
    return { data: state.usage, isError: state.usageError };
  },
}));

import { CommunityUsagePanel } from "./CommunityUsagePanel";

const render = () =>
  renderWithProviders(<CommunityUsagePanel />, {
    communities: { activeCommunity: state.community },
  });

// The panel is a community-admin surface: it lives on the admin-gated settings
// page and renders fields the API sends to admins only, so every fixture here
// is an admin's payload.
describe("CommunityUsagePanel", () => {
  beforeEach(() => {
    state.community = buildCommunity({
      id: 7,
      role: "superadmin",
      max_storage_bytes: 1000,
      max_users: 10,
      member_count: 4,
      tier_name: null,
    });
    state.billing = null;
    state.guestsEnabled = true;
    state.usage = { usage_bytes: 500 };
    state.usageError = false;
    state.usageEnabled = [];
  });

  it("renders storage and member usage against caps (FOSS, billing absent)", () => {
    render();
    expect(screen.getByText("Storage")).toBeInTheDocument();
    expect(screen.getByText("Members")).toBeInTheDocument();
    // Members: 4 of 10 — the usage number renders from the community's own row.
    expect(screen.getByText("4 of 10")).toBeInTheDocument();
  });

  it.each([
    [null, "Unlimited"],
    [3, "Up to 3 at a time"],
  ])("states a guest cap of %s as its effect", (maxGuests, said) => {
    state.community = { ...state.community, max_guests: maxGuests };
    render();
    expect(screen.getByText("Guests").parentElement).toHaveTextContent(said);
  });

  it.each([
    ["a community that takes no guests", 0, true],
    ["a deployment without guests", null, false],
  ])("says nothing about guests to %s", (_who, maxGuests, enabled) => {
    state.community = { ...state.community, max_guests: maxGuests };
    state.guestsEnabled = enabled;
    render();
    expect(screen.queryByText("Guests")).toBeNull();
  });

  it("shows no plan or portal UI, even to the seat of a billed deployment", () => {
    // The plan lives on the seat-only Billing tab (CommunityBillingPanel); this
    // panel is usage alone.
    state.billing = { url: "https://billing.example.com" };
    state.community = buildCommunity({
      id: 42,
      role: "superadmin",
      member_count: 4,
      tier_name: "gold",
    });
    render();
    expect(screen.getByText("Storage")).toBeInTheDocument();
    expect(screen.queryByText("Upgrade")).not.toBeInTheDocument();
    expect(screen.queryByText("Manage billing")).not.toBeInTheDocument();
    expect(screen.queryByText(/Current plan/)).not.toBeInTheDocument();
  });

  it("renders unlimited caps without a hard limit", () => {
    state.community = buildCommunity({
      id: 7,
      role: "superadmin",
      max_storage_bytes: null,
      max_users: null,
      member_count: 3,
    });
    render();
    expect(screen.getAllByText(/Unlimited/).length).toBeGreaterThan(0);
  });

  it("says the storage figure is unavailable rather than showing nothing stored", () => {
    // A refused or failed read is not zero bytes.
    state.usage = undefined;
    state.usageError = true;
    render();
    expect(screen.getByText("Unavailable right now")).toBeInTheDocument();
    expect(screen.queryByText(/^0 B/)).not.toBeInTheDocument();
    // The member figure needs no request and still shows.
    expect(screen.getByText("4 of 10")).toBeInTheDocument();
  });

  it("shows no storage figure while it is still loading", () => {
    state.usage = undefined;
    render();
    expect(screen.queryByText(/of 1000 B|0 B/)).not.toBeInTheDocument();
    expect(screen.queryByText("Unavailable right now")).not.toBeInTheDocument();
  });

  it("asks for the figure on a settings grant too, which may read it", () => {
    // Support lent the seat sees the Usage tab without reaching the content.
    state.community = {
      ...buildCommunity({
        id: 7,
        role: "superadmin",
        can: communityCan("superadmin", { content: false }),
      }),
      accessType: "grant",
      grantSettingsLevel: "superadmin",
    };
    render();
    expect(state.usageEnabled.every(Boolean)).toBe(true);
    expect(screen.getByText(/500 B/)).toBeInTheDocument();
  });
});

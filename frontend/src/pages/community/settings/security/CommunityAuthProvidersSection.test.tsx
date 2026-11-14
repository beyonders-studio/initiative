/**
 * What a community does with its connections, and with an arrangement it did
 * not make.
 *
 * An inherited row is the deployment's answer for a provider this community
 * has said nothing about. It has nothing of the community's own to switch or
 * disconnect — what it has is the offer to take the arrangement over, which
 * writes a connection that shadows the default from then on. A connection of
 * the community's own carries one menu: edit, placement, on or off,
 * disconnect.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityProviderConnectionRead } from "@/api/generated/initiativeAPI.schemas";

const updateConnection = vi.fn();

const row = (
  overrides: Partial<CommunityProviderConnectionRead> = {}
): CommunityProviderConnectionRead => ({
  id: 1,
  provider_id: 11,
  provider_slug: "entra",
  provider_display_name: "Entra",
  provider_icon: null,
  claim: null,
  claim_values: [],
  enabled: true,
  auto_join: false,
  narrowing_approved: false,
  accepts_provider_placement: false,
  login_ready: true,
  inherited: false,
  ...overrides,
});

let connections: CommunityProviderConnectionRead[] = [];

vi.mock("@/hooks/useCommunityAuthPolicy", () => ({
  useCommunityProviderConnections: () => ({ data: connections, isLoading: false }),
  useConnectableProviders: () => ({
    data: [{ id: 11, display_name: "Entra", icon: null, login_ready: true }],
    isLoading: false,
  }),
  useConnectProvider: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCreateClaimRule: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateCommunityAuthSettings: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateProviderConnection: () => ({
    mutate: updateConnection,
    mutateAsync: updateConnection,
    isPending: false,
  }),
  useDisconnectProvider: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { CommunityAuthProvidersSection } from "./CommunityAuthProvidersSection";

const render = () =>
  renderWithProviders(<CommunityAuthProvidersSection communityId={1} communityName="Larkspur" />, {
    auth: { user: buildUser() },
  });

/** Open a connection's menu. */
const openMenu = async (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole("button", { name: "Actions for Entra" }));

describe("CommunityAuthProvidersSection", () => {
  beforeEach(() => {
    connections = [];
    updateConnection.mockReset();
  });

  it("marks an inherited arrangement as the server's, naming its claim", () => {
    connections = [row({ id: null, inherited: true, claim: "tid", claim_values: ["acme-tenant"] })];
    render();

    expect(screen.getByText("From your server")).toBeInTheDocument();
    expect(screen.getByText("Microsoft Entra tenant: acme-tenant")).toBeInTheDocument();
  });

  it("says a connection of its own is on, and that new arrivals join", () => {
    connections = [
      row({ claim: "hd", claim_values: ["acme.com"], auto_join: true, narrowing_approved: true }),
    ];
    render();

    expect(screen.getByText("On")).toBeInTheDocument();
    expect(
      screen.getByText("Google Workspace domain: acme.com · new arrivals join")
    ).toBeInTheDocument();
    // The sign-in link sits under the providers it offers.
    expect(screen.getByText(/\/community\/1\/login$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
  });

  it("offers to take an inherited arrangement over, rather than to switch it off", () => {
    connections = [row({ id: null, inherited: true })];
    render();

    expect(screen.getByRole("button", { name: /make it ours/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Actions for Entra" })).not.toBeInTheDocument();
  });

  it("opens the wizard on the arrangement it is taking over", async () => {
    const user = userEvent.setup();
    connections = [row({ id: null, inherited: true, claim: "tid", claim_values: ["acme-tenant"] })];
    render();

    await user.click(screen.getByRole("button", { name: /make it ours/i }));

    // One flow, not two: the wizard opens past the picker, seeded from what
    // the deployment answered.
    expect(await screen.findByText("Whose people")).toBeInTheDocument();
    expect(screen.getByDisplayValue("acme-tenant")).toBeInTheDocument();
  });

  it("edits a connection of its own in the same wizard", async () => {
    const user = userEvent.setup();
    connections = [row({ id: 5, claim: "tid", claim_values: ["acme-tenant"] })];
    render();

    await openMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));

    expect(await screen.findByText("Whose people")).toBeInTheDocument();
    expect(screen.getByDisplayValue("acme-tenant")).toBeInTheDocument();
  });

  it("turns a connection of its own off from its menu", async () => {
    const user = userEvent.setup();
    connections = [row({ id: 5 })];
    render();

    await openMenu(user);
    expect(screen.getByRole("menuitem", { name: "Disconnect" })).toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: "Turn off" }));

    expect(updateConnection).toHaveBeenCalledWith({ connectionId: 5, data: { enabled: false } });
  });

  it("lets a connection of its own accept the server's placement rules", async () => {
    const user = userEvent.setup();
    connections = [row({ id: 5, accepts_provider_placement: false })];
    render();

    await openMenu(user);
    const accepts = screen.getByRole("menuitemcheckbox", { name: "Let your server place people" });
    expect(accepts).not.toBeChecked();
    await user.click(accepts);

    expect(updateConnection).toHaveBeenCalledWith({
      connectionId: 5,
      data: { accepts_provider_placement: true },
    });
  });

  it("still offers a provider it only inherits in the picker", () => {
    connections = [row({ id: null, inherited: true })];
    render();

    // Taking an inherited arrangement over is a connect, so the provider has
    // to stay choosable — only what the community said itself is filtered out.
    expect(screen.getByRole("button", { name: /connect a provider/i })).toBeEnabled();
  });
});

/**
 * Four questions, in order, and what each answer turns into.
 *
 * The wizard is the only place a community answers all of connect, rule and
 * requirement in one sitting, so what is worth pinning down is the order the
 * three calls go out in, and the two answers that are allowed to be "nothing":
 * a narrowing nobody needs, and a requirement nobody may set. Editing a
 * connection walks the same wizard, asking only the connection's own two.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityProviderConnectionRead } from "@/api/generated/initiativeAPI.schemas";

const connect = vi.fn();
const createRule = vi.fn();
const updatePolicy = vi.fn();
const updateConnection = vi.fn();

const inheritedRow = (
  overrides: Partial<CommunityProviderConnectionRead> = {}
): CommunityProviderConnectionRead => ({
  id: null,
  inherited: true,
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
  ...overrides,
});

let connections: unknown[] = [];
let available: unknown[] = [];

vi.mock("@/hooks/useCommunityAuthPolicy", () => ({
  useConnectableProviders: () => ({ data: available, isLoading: false }),
  useCommunityProviderConnections: () => ({ data: connections, isLoading: false }),
  useConnectProvider: () => ({ mutateAsync: connect, isPending: false }),
  useCreateClaimRule: () => ({ mutateAsync: createRule, isPending: false }),
  useUpdateCommunityAuthSettings: () => ({ mutateAsync: updatePolicy, isPending: false }),
  useUpdateProviderConnection: () => ({ mutateAsync: updateConnection, isPending: false }),
}));

import { ConnectSignInWizard } from "./ConnectSignInWizard";

const render = (canRequire = true, connection: CommunityProviderConnectionRead | null = null) =>
  renderWithProviders(
    <ConnectSignInWizard
      communityId={1}
      open
      onOpenChange={vi.fn()}
      canRequire={canRequire}
      connection={connection}
    />,
    { auth: { user: buildUser() } }
  );

/** Answer the narrowing step's claim select. */
const pickClaim = async (user: ReturnType<typeof userEvent.setup>, label: RegExp) => {
  await user.click(await screen.findByRole("combobox"));
  await user.click(await screen.findByRole("option", { name: label }));
};

describe("ConnectSignInWizard", () => {
  beforeEach(() => {
    connections = [];
    available = [
      { id: 11, display_name: "Entra", icon: null, login_ready: true },
      { id: 12, display_name: "Keycloak", icon: null, login_ready: false },
    ];
    connect.mockReset().mockResolvedValue({});
    createRule.mockReset().mockResolvedValue({});
    updatePolicy.mockReset().mockResolvedValue({});
    updateConnection.mockReset().mockResolvedValue({});
  });

  it("walks the four steps and connects the provider that was chosen", async () => {
    const user = userEvent.setup();
    render();

    expect(screen.getByText("Which way in")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /entra/i }));

    expect(await screen.findByText("Whose people")).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: /whose accounts count as yours/i }));
    await user.click(await screen.findByRole("option", { name: /microsoft entra tenant/i }));
    await user.type(screen.getByLabelText(/values that count/i), "acme-tenant");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    expect(await screen.findByText("Where they land")).toBeInTheDocument();
    await user.click(screen.getByRole("switch"));
    await user.type(screen.getByLabelText(/a first group/i), "eng-platform");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    expect(await screen.findByText("Do we insist")).toBeInTheDocument();
    await user.click(screen.getByRole("switch"));
    await user.click(screen.getByRole("button", { name: /connect provider/i }));

    expect(connect).toHaveBeenCalledWith({
      provider_id: 11,
      claim: "tid",
      claim_values: ["acme-tenant"],
      auto_join: true,
      enabled: true,
    });
    expect(createRule).toHaveBeenCalledWith({
      provider_id: 11,
      claim_value: "eng-platform",
      community_role: "member",
    });
    expect(updatePolicy).toHaveBeenCalledWith({
      auth_policy: { policy: "required", provider_id: 11, require_methods: [] },
    });
  });

  it("will not connect without saying who on the provider counts", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /entra/i }));

    // Communities here are separate tenants, so a provider vouching for
    // somebody is not the same as them belonging to this one. There is no
    // way past this step that leaves the question unanswered.
    expect(await screen.findByRole("button", { name: /^next$/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /skip this/i })).not.toBeInTheDocument();
  });

  it("will not go on from half a narrowing", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /entra/i }));
    await pickClaim(user, /microsoft entra tenant/i);

    // A claim with nothing counting against it reads on nobody.
    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
  });

  it("asks three questions of somebody who may not set the requirement", async () => {
    const user = userEvent.setup();
    render(false);

    await user.click(screen.getByRole("button", { name: /entra/i }));
    await pickClaim(user, /microsoft entra tenant/i);
    await user.type(await screen.findByLabelText(/values that count/i), "acme-tenant");
    await user.click(await screen.findByRole("button", { name: /^next$/i }));

    expect(await screen.findByText("Where they land")).toBeInTheDocument();
    expect(screen.getByText("Step 3 of 3")).toBeInTheDocument();
    // The last step finishes rather than leading anywhere.
    await user.click(screen.getByRole("button", { name: /connect provider/i }));

    expect(connect).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Do we insist")).not.toBeInTheDocument();
    expect(updatePolicy).not.toHaveBeenCalled();
  });

  it("starts the narrowing from what the deployment already answered", async () => {
    const user = userEvent.setup();
    connections = [inheritedRow({ claim: "tid", claim_values: ["acme-tenant"] })];
    render();

    expect(screen.getByText("From your server")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /entra/i }));

    expect(await screen.findByText("Microsoft Entra tenant")).toBeInTheDocument();
    expect(screen.getByDisplayValue("acme-tenant")).toBeInTheDocument();
  });

  it("edits a connection's narrowing and joining, and nothing else", async () => {
    const user = userEvent.setup();
    render(
      true,
      inheritedRow({
        id: 5,
        inherited: false,
        claim: "org",
        claim_values: ["acme", "acme-labs"],
        auto_join: true,
      })
    );

    expect(await screen.findByText("Whose people")).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 2")).toBeInTheDocument();
    // A claim that is none of the shortcuts is shown as typed.
    expect(screen.getByDisplayValue("org")).toBeInTheDocument();
    expect(screen.getByDisplayValue("acme, acme-labs")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    expect(await screen.findByText("Where they land")).toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeChecked();
    expect(screen.queryByLabelText(/a first group/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(updateConnection).toHaveBeenCalledWith({
      connectionId: 5,
      data: { claim: "org", claim_values: ["acme", "acme-labs"], auto_join: true },
    });
    expect(connect).not.toHaveBeenCalled();
    expect(createRule).not.toHaveBeenCalled();
  });

  it("offers no provider the deployment cannot sign anybody in with", () => {
    render();

    expect(screen.getByRole("button", { name: /keycloak/i })).toBeDisabled();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});

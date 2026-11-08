import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { ProviderPlacementRuleRead } from "@/api/generated/initiativeAPI.schemas";

const createRule = vi.fn();
const updateRule = vi.fn();
const deleteRule = vi.fn();

const connection = (providerId: number, name: string) => ({
  id: providerId,
  provider_id: providerId,
  provider_slug: name.toLowerCase(),
  provider_display_name: name,
  provider_icon: null,
  claim: null,
  claim_values: [],
  enabled: true,
  auto_join: false,
  login_ready: true,
});

let rules: unknown[] = [];
const ownRule = {
  id: 3,
  provider_id: 11,
  provider_display_name: "Entra",
  provider_icon: null,
  claim_value: "eng-platform",
  community_role: "member",
  initiative_id: null,
  initiative_name: null,
  initiative_role_id: null,
  initiative_role_name: null,
};
let reportingIds: number[] = [];
let providerRules: ProviderPlacementRuleRead[] = [];
let placementEverywhere = false;
let connections = [connection(11, "Entra")];

vi.mock("@/hooks/useCommunityAuthPolicy", () => ({
  useCommunityClaimRules: () => ({
    data: {
      rules,
      reporting_provider_ids: reportingIds,
      provider_rules: providerRules,
      placement_everywhere: placementEverywhere,
    },
    isLoading: false,
  }),
  useCommunityProviderConnections: () => ({ data: connections, isLoading: false }),
  useCreateClaimRule: () => ({ mutate: createRule, isPending: false }),
  useDeleteClaimRule: () => ({ mutate: deleteRule, isPending: false }),
  useUpdateClaimRule: () => ({ mutate: updateRule, isPending: false }),
}));

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiativesForCommunity: () => ({ data: [{ id: 7, name: "Platform" }], isLoading: false }),
}));

vi.mock("@/hooks/useInitiativeRoles", () => ({
  useInitiativeRoles: (initiativeId: number | null) => ({
    data: initiativeId ? [{ id: 70, display_name: "Contributor" }] : [],
  }),
}));

import { CommunityClaimRulesSection } from "./CommunityClaimRulesSection";

const render = () =>
  renderWithProviders(<CommunityClaimRulesSection communityId={1} />, {
    auth: { user: buildUser() },
  });

describe("CommunityClaimRulesSection", () => {
  beforeEach(() => {
    rules = [];
    reportingIds = [11];
    connections = [connection(11, "Entra")];
    providerRules = [];
    placementEverywhere = false;
    createRule.mockReset();
    updateRule.mockReset();
    deleteRule.mockReset();
  });

  it("sends a group and where it lands", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /add a rule/i }));
    await user.click(await screen.findByLabelText(/^provider$/i));
    await user.click(await screen.findByRole("option", { name: "Entra" }));
    await user.type(screen.getByLabelText(/^group$/i), "eng-platform");
    await user.click(screen.getAllByRole("button", { name: /add a rule/i }).at(-1)!);

    await waitFor(() => expect(createRule).toHaveBeenCalled());
    expect(createRule.mock.calls[0][0]).toMatchObject({
      provider_id: 11,
      claim_value: "eng-platform",
      community_role: "member",
      initiative_id: null,
      initiative_role_id: null,
    });
  });

  it("asks for a role once an initiative is named", async () => {
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: /add a rule/i }));
    expect(screen.queryByLabelText(/in that initiative/i)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(/and start in/i));
    await user.click(await screen.findByRole("option", { name: "Platform" }));

    expect(await screen.findByLabelText(/in that initiative/i)).toBeInTheDocument();
  });

  it("says when a provider reports no groups, rather than hiding it", async () => {
    reportingIds = [];
    rules = [ownRule];
    render();

    expect(screen.getByText("eng-platform")).toBeInTheDocument();
    expect(screen.getByText(/no groups reported/i)).toBeInTheDocument();
  });

  it("edits a rule in the dialog it was added in, its provider shown rather than offered", async () => {
    const user = userEvent.setup();
    rules = [ownRule];
    render();

    await user.click(screen.getByRole("button", { name: "Actions for eng-platform" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Edit rule")).toBeInTheDocument();
    expect(within(dialog).getByText("Entra")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/^provider$/i)).not.toBeInTheDocument();
    const group = within(dialog).getByLabelText(/^group$/i);
    expect(group).toHaveValue("eng-platform");

    await user.clear(group);
    await user.type(group, "eng-core");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(updateRule).toHaveBeenCalledWith(
      {
        ruleId: 3,
        data: {
          claim_value: "eng-core",
          community_role: "member",
          initiative_id: null,
          initiative_role_id: null,
        },
      },
      expect.anything()
    );
    expect(createRule).not.toHaveBeenCalled();
  });

  it("folds the deployment's rules under their count, marking one that is not applying", async () => {
    const user = userEvent.setup();
    providerRules = [
      {
        id: 40,
        provider_id: 21,
        provider_display_name: "Keycloak",
        provider_icon: null,
        claim_value: "eng",
        scope_claim: "idp",
        scope_value: "acme-adfs",
        community_id: 1,
        community_name: "Engineering",
        community_role: "member",
        initiative_id: null,
        initiative_name: null,
        initiative_role_id: null,
        initiative_role_name: null,
        applies: false,
      },
    ];
    render();

    expect(screen.queryByText("Group eng in idp = acme-adfs")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "1 rule from your server" }));

    expect(screen.getByText("Group eng in idp = acme-adfs")).toBeInTheDocument();
    expect(screen.getByText(/through keycloak/i)).toBeInTheDocument();
    expect(screen.getByText("Not applying")).toBeInTheDocument();
    // Shown, not changed: the only menus are on the community's own rules.
    expect(screen.queryByRole("button", { name: /actions for/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/applies its placement rules to every community/i)).toBeNull();
  });

  it("says when the deployment applies its rules to every community", async () => {
    const user = userEvent.setup();
    placementEverywhere = true;
    providerRules = [
      {
        id: 41,
        provider_id: 21,
        provider_display_name: "Keycloak",
        provider_icon: null,
        claim_value: null,
        scope_claim: "idp",
        scope_value: "acme-adfs",
        community_id: 1,
        community_name: "Engineering",
        community_role: "admin",
        initiative_id: null,
        initiative_name: null,
        initiative_role_id: null,
        initiative_role_name: null,
        applies: true,
      },
    ];
    render();
    await user.click(screen.getByRole("button", { name: "1 rule from your server" }));

    expect(screen.getByText("Everybody from idp = acme-adfs")).toBeInTheDocument();
    expect(screen.getByText(/applies its placement rules to every community/i)).toBeInTheDocument();
    expect(screen.queryByText("Not applying")).not.toBeInTheDocument();
  });
});

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const orderRules = vi.fn();

let roles: unknown[] = [];
const rules = [
  { id: 1, provider_id: 11, claim_value: "staff", role_id: 3, position: 1 },
  { id: 2, provider_id: 11, claim_value: "crew", role_id: 3, position: 2 },
];

vi.mock("@/hooks/useCommunityAuthPolicy", () => ({
  useCustomRoleClaimRules: () => ({ data: rules, isLoading: false }),
  useCommunityProviderConnections: () => ({
    data: [{ provider_id: 11, provider_display_name: "Entra" }],
    isLoading: false,
  }),
  useCreateCustomRoleClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
  useOrderCustomRoleClaimRules: () => ({ mutate: orderRules, isPending: false }),
  useDeleteCustomRoleClaimRule: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useCustomRoles", () => ({
  useCustomRoles: () => ({ data: roles }),
}));

import { CustomRoleClaimRulesSection } from "./CustomRoleClaimRulesSection";

const render = () =>
  renderWithProviders(<CustomRoleClaimRulesSection communityId={1} />, {
    auth: { user: buildUser() },
  });

describe("CustomRoleClaimRulesSection", () => {
  beforeEach(() => {
    orderRules.mockReset();
    roles = [{ id: 3, name: "Door person", base_rung: "member", surfaces: ["invites"] }];
  });

  it("stays out of the way where the community has no custom roles", () => {
    roles = [];
    const { container } = render();
    expect(container).toBeEmptyDOMElement();
  });

  it("lists the rules in order, and moves one", async () => {
    const user = userEvent.setup();
    render();

    expect(screen.getAllByText("Through Entra, gives Door person")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Move crew up" }));
    expect(orderRules).toHaveBeenCalledWith([2, 1], expect.anything());
    expect(screen.getByRole("button", { name: "Move staff up" })).toBeDisabled();
  });
});

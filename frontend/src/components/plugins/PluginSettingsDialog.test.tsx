/**
 * The community's own credential is the seat's to fill in: a superadmin gets
 * its form, and an admin below the seat is told whether it is set.
 *
 * A plug-in whose plan has ended says so here too, and the seat is offered
 * how to get it again.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityPluginDetail } from "@/api/generated/initiativeAPI.schemas";

import { PluginSettingsDialog } from "./PluginSettingsDialog";

const ACTION = "https://billing.example.com/manage?app=SHOP0000000001";

let entitlement: CommunityPluginDetail["entitlement"] = null;

const detail = {
  id: 3,
  name: "Shop",
  listing_uid: "SHOP0000000001",
  definition: {},
  requested_scopes: [],
  consents: [],
  connections: [
    {
      id: "admin",
      scope: "static",
      label: { en: "Admin API" },
      fields: [{ key: "shop_domain", type: "string", label: { en: "Shop domain" } }],
      access_hint: null,
      values: {},
      has_value: { shop_domain: true },
      satisfied: true,
      runs_flow: false,
      status: null,
      account_label: null,
      blocked: false,
    },
  ],
} as unknown as CommunityPluginDetail;

vi.mock("@/hooks/useCommunityPluginDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPluginDetail")>()),
  useCommunityPluginDetail: () => ({ data: { ...detail, entitlement }, isLoading: false }),
}));

const openAddress = vi.fn();
vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({ canSell: true, openAddress }),
}));

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListingByUid: () => ({
    data: {
      unavailable: {
        reason: "entitlement_required",
        action_url: ACTION,
        offer: {
          charge: "one_time",
          way: "buy",
          upgrade: false,
          lines: [{ id: "pack", name: "Pack", display: "$30" }],
        },
      },
    },
    isLoading: false,
  }),
}));

beforeEach(() => {
  entitlement = null;
  openAddress.mockReset();
});

vi.mock("./PluginMembersPanel", () => ({ PluginMembersPanel: () => null }));

const renderAs = (role: "superadmin" | "admin") => {
  const community = buildCommunity({ role });
  renderWithProviders(
    <PluginSettingsDialog pluginId={3} isCommunityAdmin open onOpenChange={() => {}} />,
    {
      communities: {
        communities: [community],
        activeCommunityId: community.id,
        activeCommunity: community,
      },
    }
  );
};

describe("PluginSettingsDialog", () => {
  it("gives the seat the community credential's form", async () => {
    renderAs("superadmin");
    expect(await screen.findByLabelText("Shop domain")).toBeInTheDocument();
  });

  it("tells an admin below the seat whether it is set", async () => {
    renderAs("admin");
    expect(await screen.findByText(/community admin has set this up/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Shop domain")).not.toBeInTheDocument();
  });
});

describe("a plug-in whose plan has ended", () => {
  beforeEach(() => {
    entitlement = { active: false, reason: null, action_url: ACTION };
  });

  it("says so, and lets the seat get it again", async () => {
    const user = userEvent.setup();
    renderAs("superadmin");

    expect(await screen.findByText("This plug-in's plan has ended.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Buy" }));
    expect(openAddress).toHaveBeenCalledWith(expect.any(Number), ACTION);
  });

  it("tells an admin below the seat, with nothing to press", async () => {
    renderAs("admin");

    expect(await screen.findByText("This plug-in's plan has ended.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Buy" })).toBeNull();
  });

  it("says nothing of a full term, which is a different thing", async () => {
    entitlement = { active: false, reason: "term_full", action_url: null };
    renderAs("superadmin");

    expect(await screen.findByLabelText("Shop domain")).toBeInTheDocument();
    expect(screen.queryByText("This plug-in's plan has ended.")).toBeNull();
  });
});

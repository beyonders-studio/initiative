/**
 * The install dialog is the seat's consent, sent with the install.
 *
 * What matters is what reaches the server: every scope the server allows is
 * granted unless the seat unticks it, a scope it does not allow can never be
 * sent, placement is asked of a plug-in with a page inside initiatives or access
 * to reach there, and the plug-ins here that ask to use it may unless the seat
 * unticks them. Who uses it is the roles' answer afterwards, so the dialog says
 * which permissions there are and where each is changed.
 */

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildMarketplaceListingDetail } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  CommunityPluginInstall,
  MarketplaceListingDetail,
} from "@/api/generated/initiativeAPI.schemas";

import { InstallPluginDialog } from "./InstallPluginDialog";

const sent: CommunityPluginInstall[] = [];

vi.mock("@/hooks/useCommunityPlugins", () => ({
  useInstallCommunityPlugin: () => ({
    isPending: false,
    mutate: (body: CommunityPluginInstall) => sent.push(body),
  }),
}));

vi.mock("@/hooks/useInitiatives", () => ({
  useCommunityInitiatives: () => ({
    isLoading: false,
    data: [
      { id: 11, name: "Garden" },
      { id: 12, name: "Kitchen" },
    ],
  }),
}));

const listing = (overrides: Partial<MarketplaceListingDetail> = {}) =>
  buildMarketplaceListingDetail({
    uid: "WIDGETCO000001",
    kind: "plugin",
    name: "WidgetCo",
    requested_scopes: ["projects:read", "projects:write", "members:read"],
    grantable_scopes: ["projects:read", "members:read"],
    has_initiative_surfaces: true,
    ...overrides,
  });

const open = (overrides: Partial<MarketplaceListingDetail> = {}) =>
  renderPage(() => (
    <InstallPluginDialog listing={listing(overrides)} open onOpenChange={() => undefined} />
  ));

const install = async () => {
  (await screen.findByRole("button", { name: "Add to community" })).click();
  await waitFor(() => expect(sent).toHaveLength(1));
  return sent[0];
};

beforeEach(() => {
  sent.length = 0;
});

describe("InstallPluginDialog", () => {
  it("grants everything the server allows, everywhere, by default", async () => {
    open();

    expect(await screen.findByLabelText("Read projects")).toBeChecked();
    expect(screen.getByLabelText("See who is in your community, by name")).toBeChecked();

    expect(await install()).toEqual({
      listing_uid: "WIDGETCO000001",
      name: "WidgetCo",
      granted_scopes: ["projects:read", "members:read"],
      placements: "all",
      callers: [],
    });
  });

  it("shows a scope the server does not allow, and cannot tick it", async () => {
    open();

    const change = await screen.findByLabelText("Read and change projects");
    expect(change).toBeDisabled();
    expect(change).not.toBeChecked();
    expect(screen.getByText("This server doesn't allow it")).toBeInTheDocument();
  });

  it("sends what the seat unticked as not granted", async () => {
    open();

    (await screen.findByLabelText("See who is in your community, by name")).click();
    await waitFor(() =>
      expect(screen.getByLabelText("See who is in your community, by name")).not.toBeChecked()
    );

    expect((await install()).granted_scopes).toEqual(["projects:read"]);
  });

  it("places it in the initiatives picked", async () => {
    open();

    (await screen.findByLabelText("Only the initiatives I choose")).click();
    (await screen.findByLabelText("Kitchen")).click();
    await waitFor(() => expect(screen.getByLabelText("Kitchen")).toBeChecked());

    expect((await install()).placements).toEqual([12]);
  });

  it("places a plug-in with access but no page", async () => {
    open({ has_initiative_surfaces: false });

    expect(await screen.findByText("Where it works")).toBeInTheDocument();
    expect(
      screen.getByText("It reads and changes things only in the initiatives you choose.")
    ).toBeInTheDocument();

    expect((await install()).placements).toEqual("all");
  });

  it("names each permission, whether members start with it, and where it is changed", async () => {
    open({
      definition: {
        permissions: [
          { id: "export", level: "initiative", name: { en: "Export builds" }, members: true },
          { id: "settings", level: "community", name: { en: "Settings" } },
        ],
      },
    });

    expect(await screen.findByText("Who can use it")).toBeInTheDocument();
    // Use at each level, named by the app where the plug-in names it not.
    expect(screen.getAllByText("Use")).toHaveLength(2);
    expect(screen.getByText("Export builds")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(
      screen.getByText(
        "In each initiative, managers start with it. Give it to other roles on the initiative's Roles screen."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "In each initiative, every role starts with it. Change that on the initiative's Roles screen."
      )
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Across the community, admins hold it. Choose the custom admin roles that keep it on the community's Roles screen."
      )
    ).toHaveLength(2);
  });

  it("asks to use another plug-in by that plug-in's name, and grants it", async () => {
    open({
      requested_scopes: ["projects:read", "plugins:acme.github"],
      grantable_scopes: ["projects:read", "plugins:acme.github"],
      plugin_names: { "acme.github": "GitHub" },
    });

    expect(await screen.findByLabelText("Use GitHub in this community")).toBeChecked();
    expect((await install()).granted_scopes).toEqual(["projects:read", "plugins:acme.github"]);
  });

  it("asks whether the plug-ins already here may use it, each ticked", async () => {
    open({
      callers: [
        { id: 7, name: "Automations" },
        { id: 9, name: "Reports" },
      ],
    });

    expect(await screen.findByText("Plug-ins that can use it")).toBeInTheDocument();
    expect(screen.getByLabelText("Automations")).toBeChecked();
    screen.getByLabelText("Reports").click();
    await waitFor(() => expect(screen.getByLabelText("Reports")).not.toBeChecked());

    expect((await install()).callers).toEqual([7]);
  });

  it("leaves acting as a moderator or an admin for the seat to tick", async () => {
    const standings = ["initiatives:moderate", "community:admin"];
    open({
      requested_scopes: ["projects:read", ...standings],
      grantable_scopes: ["projects:read", ...standings],
    });

    const moderate = await screen.findByLabelText(
      "Act as a moderator in the initiatives it's placed in"
    );
    const admin = screen.getByLabelText("Act as an admin across your whole community");
    expect(moderate).not.toBeChecked();
    expect(admin).not.toBeChecked();

    moderate.click();
    await waitFor(() => expect(moderate).toBeChecked());
    expect((await install()).granted_scopes).toEqual(["projects:read", "initiatives:moderate"]);
  });

  it("says a plug-in with no name by its public id", async () => {
    open({ requested_scopes: ["plugins:acme.github"], grantable_scopes: [] });

    const use = await screen.findByLabelText("Use acme.github in this community");
    expect(use).toBeDisabled();
  });

  it("asks nothing about placement for a plug-in with no page and no access", async () => {
    open({ has_initiative_surfaces: false, requested_scopes: [], grantable_scopes: [] });

    await screen.findByRole("button", { name: "Add to community" });
    expect(screen.queryByText("Where it works")).not.toBeInTheDocument();
    expect((await install()).placements).toEqual([]);
  });
});

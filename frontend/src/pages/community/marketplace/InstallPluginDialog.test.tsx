/**
 * The install dialog is the seat's consent, sent with the install.
 *
 * What matters is what reaches the server: every scope the server allows is
 * granted unless the seat unticks it, a scope it does not allow can never be
 * sent, placement is asked of a plug-in with a page inside initiatives or access
 * to reach there, moderators open a page unless the seat says otherwise, and the
 * plug-ins here that ask to use it may unless the seat unticks them.
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
  it("grants everything the server allows, everywhere, to moderators by default", async () => {
    open();

    expect(await screen.findByLabelText("Read projects")).toBeChecked();
    expect(screen.getByLabelText("See who is in your community, by name")).toBeChecked();

    expect(await install()).toEqual({
      listing_uid: "WIDGETCO000001",
      name: "WidgetCo",
      granted_scopes: ["projects:read", "members:read"],
      placements: "all",
      role_kinds: ["moderator"],
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

  it("places it in the initiatives picked, for the roles chosen", async () => {
    open();

    (await screen.findByLabelText("Only the initiatives I choose")).click();
    (await screen.findByLabelText("Kitchen")).click();
    (await screen.findByLabelText("Project managers")).click();
    await waitFor(() => expect(screen.getByLabelText("Kitchen")).toBeChecked());

    const body = await install();
    expect(body.placements).toEqual([12]);
    expect(body.role_kinds).toEqual(["moderator", "project_manager"]);
  });

  it("places a plug-in with access but no page, and asks nothing about roles", async () => {
    open({ has_initiative_surfaces: false });

    expect(await screen.findByText("Where it works")).toBeInTheDocument();
    expect(
      screen.getByText("It reads and changes things only in the initiatives you choose.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Who can open it there")).not.toBeInTheDocument();

    const body = await install();
    expect(body.placements).toEqual("all");
    expect(body.role_kinds).toEqual([]);
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
    expect(screen.queryByText("Who can open it there")).not.toBeInTheDocument();
    expect((await install()).placements).toEqual([]);
  });
});

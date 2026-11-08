/**
 * The two things this panel decides: what the switch sends, and whether there
 * is an update to offer at all.
 *
 * Both are easy to get backwards. The switch reflects an install that is
 * already tracking, so an admin's first interaction with it is turning it
 * *off* — a panel that sent `auto_update: true` there would silently confirm
 * the state it was meant to leave. And the Update button is drawn from the
 * server's `update_version` rather than from a comparison invented here, so an
 * install on the newest version must not offer one, and one whose newer version
 * cannot run here says so rather than "Up to date".
 */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type {
  CommunityPluginDetail,
  CommunityPluginUpgradeAsks,
} from "@/api/generated/initiativeAPI.schemas";

import { PluginPendingUpdate, PluginUpdatesPanel } from "./PluginUpdatesPanel";

const patched: unknown[] = [];
const upgraded = vi.fn();

vi.mock("@/hooks/useCommunityPlugins", () => ({
  useUpdateCommunityPlugin: () => ({
    isPending: false,
    mutate: (body: unknown) => patched.push(body),
  }),
}));

const declined = vi.fn();

vi.mock("@/hooks/useCommunityPluginDetail", () => ({
  useUpgradePlugin: () => ({ isPending: false, mutate: upgraded }),
  useDeclinePluginUpgrade: () => ({ isPending: false, mutate: declined }),
}));

const plugin = (overrides: Partial<CommunityPluginDetail>) =>
  ({
    id: 7,
    name: "Community calendar",
    listing_version: "1.0.0",
    auto_update: true,
    ...overrides,
  }) as unknown as CommunityPluginDetail;

const asks = (overrides: Partial<CommunityPluginUpgradeAsks>): CommunityPluginUpgradeAsks => ({
  version: "1.2.0",
  added_scopes: ["files:read"],
  added_surfaces: [],
  declined: false,
  ...overrides,
});

beforeEach(() => {
  patched.length = 0;
  upgraded.mockClear();
  declined.mockClear();
});

describe("PluginUpdatesPanel", () => {
  it("shows an install as tracking, and turns that off when asked", async () => {
    renderPage(() => <PluginUpdatesPanel plugin={plugin({})} />);

    const toggle = await screen.findByLabelText("Update automatically");
    expect(toggle).toBeChecked();

    toggle.click();
    expect(patched).toEqual([{ auto_update: false }]);
  });

  it("turns tracking back on from the manual state", async () => {
    renderPage(() => <PluginUpdatesPanel plugin={plugin({ auto_update: false })} />);

    const toggle = await screen.findByLabelText("Update automatically");
    expect(toggle).not.toBeChecked();

    toggle.click();
    expect(patched).toEqual([{ auto_update: true }]);
  });

  it("offers the version the server named, and applies it", async () => {
    renderPage(() => <PluginUpdatesPanel plugin={plugin({ update_version: "1.2.0" })} />);

    const button = await screen.findByRole("button", { name: "Update to 1.2.0" });
    button.click();
    expect(upgraded).toHaveBeenCalledOnce();
  });

  it("offers nothing when the server named no version", async () => {
    renderPage(() => <PluginUpdatesPanel plugin={plugin({ update_version: null })} />);

    expect(await screen.findByText("Up to date")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Update to/ })).not.toBeInTheDocument();
  });

  it("names a newer version this server cannot run, and why", async () => {
    renderPage(() => (
      <PluginUpdatesPanel
        plugin={plugin({
          update_version: null,
          update_refused: {
            version: "1.3.0",
            reason: "MARKETPLACE_LISTING_PLUGIN_API_INCOMPATIBLE",
          },
        })}
      />
    ));

    expect(await screen.findByText(/Version 1\.3\.0 can't run on this server\./)).toHaveTextContent(
      "built for a plug-in API this server doesn't provide"
    );
    expect(screen.queryByText("Up to date")).not.toBeInTheDocument();
  });

  it("says what a version asking for more wants, and accepts it with its scopes", async () => {
    const wanted = asks({
      added_scopes: ["files:write"],
      added_surfaces: [{ id: "planner", name: { en: "Planner" } }],
    });
    renderPage(() => (
      <>
        <PluginUpdatesPanel plugin={plugin({ update_version: "1.2.0", pending_update: wanted })} />
        <PluginPendingUpdate pluginId={7} asks={wanted} />
      </>
    ));

    expect(await screen.findByText("Version 1.2.0 wants to:")).toBeInTheDocument();
    expect(screen.getByText("Read and change files")).toBeInTheDocument();
    expect(screen.getByText("Show “Planner” inside initiatives")).toBeInTheDocument();
    // The plain Update button is not offered beside the question.
    expect(screen.queryByRole("button", { name: /Update to/ })).not.toBeInTheDocument();

    screen.getByRole("button", { name: "Accept and update" }).click();
    expect(upgraded).toHaveBeenCalledWith(
      { version: "1.2.0", add_scopes: ["files:write"] },
      expect.anything()
    );
  });

  it("says a version asking to use another plug-in names that plug-in", async () => {
    renderPage(() => (
      <PluginPendingUpdate
        pluginId={7}
        asks={asks({ version: "1.3.0", added_scopes: ["plugins:acme.github"] })}
        pluginNames={{ "acme.github": "GitHub" }}
      />
    ));

    expect(await screen.findByText("Use GitHub in this community")).toBeInTheDocument();
  });

  it("declines the version it was shown", async () => {
    renderPage(() => <PluginPendingUpdate pluginId={7} asks={asks({})} />);

    (await screen.findByRole("button", { name: "Decline" })).click();
    expect(declined).toHaveBeenCalledWith("1.2.0", expect.anything());
  });

  it("says a declined version was declined, and offers only to accept it", async () => {
    renderPage(() => <PluginPendingUpdate pluginId={7} asks={asks({ declined: true })} />);

    expect(
      await screen.findByText(
        "You declined version 1.2.0. The plug-in stays on its current version."
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Decline" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept and update" })).toBeInTheDocument();
  });
});

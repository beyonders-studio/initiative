/**
 * Removing a plug-in whose charges somebody else manages.
 *
 * The confirmation says what removing any plug-in does, and for one the
 * community's provider has a say about, what that provider says too: its own
 * sentence when it answered, a neutral one when it did not. Nothing extra for
 * any other plug-in. An admin may also have the plug-in erase what it holds
 * about the community.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { communityCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityPluginUninstallNotice } from "@/api/generated/initiativeAPI.schemas";

import { SettingsCommunityPluginsPage } from "./SettingsCommunityPluginsPage";

let notice: CommunityPluginUninstallNotice | undefined;
let closedSurfaces: string[] | null = null;
const openAddress = vi.fn();
const uninstall = vi.hoisted(() => vi.fn());

vi.mock(import("@/api/generated/plugins/plugins"), async (importOriginal) => ({
  ...(await importOriginal()),
  uninstallCommunityPlugin: uninstall,
}));

vi.mock("@/hooks/useCommunities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunities")>()),
  useCommunities: () => ({
    activeCommunityId: 1,
    activeCommunity: {
      id: 1,
      role: "superadmin",
      can: communityCan("superadmin"),
      closed_surfaces: closedSurfaces,
    },
  }),
}));
vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({ canSell: true, openAddress }),
}));
vi.mock("@/hooks/useCommunityPlugins", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPlugins")>()),
  useCommunityPlugins: () => ({
    data: {
      items: [{ id: 4, name: "PaidCo", enabled: true, created_at: "2026-10-01T00:00:00Z" }],
    },
    isLoading: false,
  }),
  useUninstallNotice: () => ({ data: notice }),
}));

beforeEach(() => {
  notice = undefined;
  closedSurfaces = null;
  openAddress.mockReset();
  uninstall.mockReset();
  uninstall.mockResolvedValue(undefined);
});

async function openRemoval() {
  renderPage(SettingsCommunityPluginsPage);
  await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
  return screen.findByRole("alertdialog");
}

describe("the removal dialog", () => {
  it("shows the provider's own words, and where to go about it", async () => {
    notice = {
      managed: true,
      message: "PaidCo keeps working until 30 November.",
      action_url: "https://portal.test/apps/x",
    };
    await openRemoval();

    expect(screen.getByText(/PaidCo keeps working until 30 November\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Manage" }));
    expect(openAddress).toHaveBeenCalledWith(1, "https://portal.test/apps/x");
  });

  it("says something neutral when the provider did not answer", async () => {
    notice = { managed: true, message: null, action_url: null };
    await openRemoval();

    expect(
      screen.getByText(/Charges for this plug-in are managed by your provider\./)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Manage" })).toBeNull();
  });

  it("adds nothing for a plug-in nobody else manages", async () => {
    notice = { managed: false, message: null, action_url: null };
    await openRemoval();

    expect(screen.queryByText(/managed by your provider/)).toBeNull();
  });
});

describe("erasing its data", () => {
  it("keeps it unless the admin asks for it to be erased", async () => {
    await openRemoval();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(uninstall).toHaveBeenCalledWith(1, 4, undefined));
  });

  it("erases it when the admin ticks the box", async () => {
    await openRemoval();
    await userEvent.click(screen.getByRole("checkbox", { name: "Also erase its data" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove and erase" }));

    await waitFor(() => expect(uninstall).toHaveBeenCalledWith(1, 4, { erase: true }));
  });
});

describe("when whoever runs the server manages plug-ins", () => {
  it("lists what is installed, says so, and offers nothing to change", async () => {
    closedSurfaces = ["plugins"];
    renderPage(SettingsCommunityPluginsPage);

    expect(
      await screen.findByText("Whoever runs this server manages plug-ins for this community.")
    ).toBeInTheDocument();
    expect(screen.getByText("PaidCo")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Rename" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Turn off" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });
});

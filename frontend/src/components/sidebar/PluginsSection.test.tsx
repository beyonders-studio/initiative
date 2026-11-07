/**
 * Who sees the Plug-ins section, and when.
 *
 * The section shows for everyone, because everyone can do something with it:
 * an admin adds a plug-in, and a member browses the same shelf to see what exists
 * and who to ask for it. What differs is the invitation at the bottom.
 *
 * Disabled plug-ins belong in community settings, not here — the sidebar shows what is
 * on.
 *
 * An admin-only plug-in is hidden from members for the same reason an empty section
 * is: it has no sharing to widen, so the entry would refuse everyone who clicked
 * it. The server says which plug-ins those are; this only honors the answer.
 *
 * And every visible entry leads somewhere: a plug-in with a surface opens it, an
 * plug-in with a credential to supply opens that form, and a plug-in with neither
 * waits under "show more" rather than spending a row on a dead click.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityPluginRead } from "@/api/generated/initiativeAPI.schemas";
import { SidebarProvider } from "@/components/sidebar/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

import { PluginsSection } from "./PluginsSection";

let plugins: Partial<CommunityPluginRead>[] = [];

vi.mock("@/hooks/useCommunityPlugins", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPlugins")>()),
  useCommunityPlugins: () => ({ data: { items: plugins }, isLoading: false }),
}));

const plugin = (overrides: Partial<CommunityPluginRead> = {}) =>
  ({
    id: 1,
    name: "Community calendar",
    tool: "calendar",
    enabled: true,
    artifacts: [{ type: "calendar", id: 12 }],
    ...overrides,
  }) as CommunityPluginRead;

// The section is built from sidebar primitives, so it needs the providers it
// would have in the real shell.
const render = (isCommunityAdmin: boolean) =>
  renderPage(() => (
    <TooltipProvider>
      <SidebarProvider>
        <PluginsSection isCommunityAdmin={isCommunityAdmin} open onOpenChange={() => {}} />
      </SidebarProvider>
    </TooltipProvider>
  ));

beforeEach(() => {
  plugins = [];
});

describe("PluginsSection", () => {
  it("points a member at the store when the community has no plug-ins", async () => {
    // They cannot add one, but they can look and ask, so the shelf is worth
    // pointing at rather than hiding.
    render(false);
    expect(await screen.findByText("Plug-ins")).toBeInTheDocument();
    expect(screen.getByText("Browse the marketplace")).toBeInTheDocument();
    expect(screen.queryByText("Add a plug-in")).toBeNull();
  });

  it("invites an admin to add one when the community has no plug-ins", async () => {
    render(true);
    expect(await screen.findByText("Plug-ins")).toBeInTheDocument();
    expect(screen.getByText("Add a plug-in")).toBeInTheDocument();
    expect(screen.queryByText("Browse the marketplace")).toBeNull();
  });

  it("lists installed plug-ins for a member", async () => {
    plugins = [plugin()];
    render(false);
    expect(await screen.findByText("Community calendar")).toBeInTheDocument();
    // No add affordance: installing is a community-admin action.
    expect(screen.queryByText("Add a plug-in")).toBeNull();
    expect(screen.getByText("Browse the marketplace")).toBeInTheDocument();
  });

  it("links a plug-in to what it mounted", async () => {
    plugins = [plugin()];
    render(false);
    const link = (await screen.findByText("Community calendar")).closest("a");
    // The list, not one of them: a member may add calendars to the plug-in, so its
    // entry leads to everything it holds.
    expect(link?.getAttribute("href")).toContain("/calendars");
    expect(link?.getAttribute("href")).not.toContain("/calendars/12");
  });

  it("still links a tool-instance plug-in that holds nothing yet", async () => {
    // Its home is where the first one gets made, so an empty plug-in is the one
    // that most needs a row.
    plugins = [plugin({ artifacts: [] })];
    render(false);
    const link = (await screen.findByText("Community calendar")).closest("a");
    expect(link?.getAttribute("href")).toContain("/calendars");
  });

  it("hides a disabled plug-in", async () => {
    // Turned off means gone from the sidebar; community settings is where it comes
    // back, which is also the only place the switch lives.
    plugins = [plugin({ enabled: false })];
    render(true);
    await screen.findByText("Plug-ins");
    expect(screen.queryByText("Community calendar")).toBeNull();
  });

  it("still offers the store to a member when every plug-in is disabled", async () => {
    plugins = [plugin({ enabled: false })];
    render(false);
    expect(await screen.findByText("Browse the marketplace")).toBeInTheDocument();
    expect(screen.queryByText("Community calendar")).toBeNull();
  });

  it("opens a service plug-in's own page", async () => {
    plugins = [
      plugin({
        id: 7,
        name: "Automations",
        tool: null,
        artifacts: [],
        definition: { pages: [{ id: "automations", path: "/page" }] },
        // The server's answer for this reader: the surface opens community-wide.
        surface_access: [
          { surface_id: "automations", openable_community_wide: true, openable_initiatives: [] },
        ],
      }),
    ];
    render(false);
    const link = (await screen.findByText("Automations")).closest("a");
    expect(link?.getAttribute("href")).toContain("/plugins/7");
  });

  it("draws the listing's artwork rather than a generic icon", async () => {
    plugins = [plugin({ avatar_url: "/marketplace/calendar.svg" })];
    render(false);
    const entry = await screen.findByText("Community calendar");
    const artwork = entry.closest("a")?.querySelector("img");
    expect(artwork?.getAttribute("src")).toBe("/marketplace/calendar.svg");
  });

  it("folds a plug-in with nothing to open under 'show more'", async () => {
    // A plug-in that mounts no tool, declares no surface this reader may open and
    // asks for no credential has nowhere to lead, so it is not worth a row
    // until asked for.
    plugins = [plugin({ name: "Widgets only", tool: null, artifacts: [] })];
    render(false);
    await screen.findByText("Plug-ins");
    expect(screen.queryByText("Widgets only")).toBeNull();

    (await screen.findByText("1 more")).click();
    const entry = await screen.findByText("Widgets only");
    expect(entry.closest("a")).toBeNull();
  });

  it("keeps the add affordance below the plug-ins, 'show more' included", async () => {
    // Same shape as the initiatives list: adding one is always in the same
    // place, whether or not the collapsed plug-ins are expanded.
    plugins = [plugin(), plugin({ id: 2, name: "Widgets only", tool: null, artifacts: [] })];
    render(true);
    const add = await screen.findByText("Add a plug-in");
    const more = await screen.findByText("1 more");
    // eslint-disable-next-line no-bitwise -- DOCUMENT_POSITION_FOLLOWING
    expect(more.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps a plug-in that only has a credential to supply in the list", async () => {
    plugins = [
      plugin({
        id: 9,
        name: "GitHub",
        tool: null,
        artifacts: [],
        definition: { connections: [{ id: "token", scope: "interactive" }] },
      }),
    ];
    render(false);
    // Listed, and not behind "show more" — there is something to open.
    expect(await screen.findByText("GitHub")).toBeInTheDocument();
    expect(screen.queryByText("1 more")).toBeNull();
  });

  it("gives every plug-in a settings gear, whatever else its entry does", async () => {
    // Three shapes of entry — a page, a credential form, nothing at all — and
    // the gear is on all of them, because every plug-in has something a person may
    // want to check or take back.
    plugins = [
      plugin(),
      plugin({
        id: 9,
        name: "GitHub",
        tool: null,
        artifacts: [],
        definition: { connections: [{ id: "token", scope: "interactive" }] },
      }),
    ];
    render(false);
    await screen.findByText("Community calendar");
    expect(screen.getByLabelText("Community calendar settings")).toBeInTheDocument();
    expect(screen.getByLabelText("GitHub settings")).toBeInTheDocument();
  });

  it("gives the gear to a plug-in with nothing to open, once it is shown", async () => {
    plugins = [plugin({ name: "Widgets only", tool: null, artifacts: [] })];
    render(false);
    (await screen.findByText("1 more")).click();
    expect(await screen.findByLabelText("Widgets only settings")).toBeInTheDocument();
  });
});

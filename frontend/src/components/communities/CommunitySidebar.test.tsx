/**
 * Reordering communities on a touch screen.
 *
 * Touch has one press-and-hold, and the context menu owns it. Wiring a drag
 * sensor to the same gesture meant a long press on a community started a reorder
 * instead of opening the menu, so the menu was unreachable on a phone. Touch
 * dragging now waits behind an explicit "Reorder communities" action, and while it
 * is on a tap moves the community rather than switching to it.
 *
 * A community reached through a temporary access grant is not part of the user's
 * order, so it offers no reorder action.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import { buildCommunity } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { asPhoneThatMayNotSell } from "@/__tests__/helpers/storeSelling";
import { SidebarProvider } from "@/components/sidebar/sidebar";
import type { CommunityEntry, useCommunities } from "@/hooks/useCommunities";
import { toast } from "@/lib/mascotToast";

import { CommunitySidebar } from "./CommunitySidebar";

// Deployment config, mocked so a test can put the sidebar in whichever shape it
// is about: no billing portal (self-hosted) or one configured, and a community
// directory the platform owner is running or has switched off.
const state = vi.hoisted(() => ({
  billing: null as { url: string } | null,
  communityDirectory: true,
}));
const mintMock = vi.hoisted(() => vi.fn());
const waiting = vi.hoisted(() => vi.fn());
// The mark on the logo is a count, and the count is a read of its own.
vi.mock("@/hooks/useMyMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useMessagesWaiting: () => waiting(),
}));
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    billing: state.billing,
    communityDirectoryEnabled: state.communityDirectory,
  }),
}));
vi.mock("@/api/generated/communities/communities", async () => {
  const actual = await vi.importActual<typeof import("@/api/generated/communities/communities")>(
    "@/api/generated/communities/communities"
  );
  return {
    ...actual,
    createCommunityBillingHandoff: mintMock,
  };
});
vi.mock("@/lib/mascotToast", () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}));

beforeEach(() => {
  waiting.mockReturnValue(0);
});

const entry = (overrides: Partial<CommunityEntry> = {}): CommunityEntry =>
  ({ ...buildCommunity(), accessType: "member", ...overrides }) as CommunityEntry;

const setup = (communities: CommunityEntry[]) => {
  const switchCommunity = vi.fn();
  const { router } = renderPage(
    () => (
      <SidebarProvider>
        <CommunitySidebar />
      </SidebarProvider>
    ),
    { communities: { communities, activeCommunityId: communities[0]?.id ?? null, switchCommunity } }
  );
  return { router, switchCommunity };
};

// The router mounts asynchronously, so the first query in each test waits.
const railButton = (name: string) => screen.findByRole("button", { name: `Switch to ${name}` });

// The flyout repeats every community the rail shows, so queries against it are
// scoped to the panel that owns the "Communities" heading.
const openFlyout = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "Expand community list" }));
  const heading = await screen.findByRole("heading", { name: "Communities" });
  const header = heading.parentElement as HTMLElement;
  return { header, panel: header.parentElement as HTMLElement };
};

describe("CommunitySidebar reorder mode", () => {
  it("offers a reorder action in a member community's context menu", async () => {
    const communities = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    setup(communities);

    fireEvent.contextMenu(await railButton("Alpha"));

    expect(
      await screen.findByRole("menuitem", { name: "Reorder communities" })
    ).toBeInTheDocument();
  });

  it("does not offer it for a community held through a temporary grant", async () => {
    const communities = [
      entry({ name: "Alpha" }),
      entry({ name: "Loaner", accessType: "grant", grantExpiresAt: null }),
    ];
    setup(communities);

    // Grant communities only get a full row in the expanded flyout.
    const { panel } = await openFlyout();
    fireEvent.contextMenu(within(panel).getByRole("button", { name: "Switch to Loaner" }));

    expect(await screen.findByRole("menuitem", { name: "Copy community ID" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Reorder communities" })).not.toBeInTheDocument();
  });

  it("does not offer it when there is only one community to order", async () => {
    setup([entry({ name: "Alpha" })]);

    fireEvent.contextMenu(await railButton("Alpha"));

    expect(await screen.findByRole("menuitem", { name: "Copy community ID" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Reorder communities" })).not.toBeInTheDocument();
  });

  it("turns taps into drags while reordering, and hands them back on Done", async () => {
    const communities = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    const { switchCommunity } = setup(communities);

    fireEvent.contextMenu(await railButton("Alpha"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Reorder communities" }));

    const done = await screen.findByRole("button", { name: "Done" });
    fireEvent.click(screen.getByRole("button", { name: "Drag to reorder Beta" }));
    expect(switchCommunity).not.toHaveBeenCalled();

    fireEvent.click(done);
    fireEvent.click(await railButton("Beta"));
    expect(switchCommunity).toHaveBeenCalledWith(communities[1].id);
  });

  it("exposes the same reorder toggle in the expanded community list", async () => {
    const communities = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    setup(communities);

    const { header } = await openFlyout();

    fireEvent.click(within(header).getByRole("button", { name: "Reorder" }));

    expect(
      screen.getByText("Drag communities to reorder them, then tap Done.")
    ).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Done" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });
});

describe("CommunitySidebar settings grants", () => {
  it("lands a settings-only superadmin grant on its usable page", async () => {
    const communities = [
      entry({ id: 1, name: "Alpha" }),
      entry({
        id: 8,
        name: "Loaner",
        accessType: "grant",
        grantAccessLevel: null,
        grantSettingsLevel: "superadmin",
      }),
    ];
    const { router, switchCommunity } = setup(communities);
    const { panel } = await openFlyout();

    fireEvent.click(within(panel).getByRole("button", { name: "Switch to Loaner" }));

    expect(switchCommunity).toHaveBeenCalledWith(8);
    await waitFor(() => expect(router.state.location.pathname).toBe("/c/8/settings"));
  });
});

/**
 * Creating a community on a deployment that has a billing portal.
 *
 * A new community starts on the deployment's default plan, so the flow hands the
 * creator straight to the portal to see that plan and add payment details.
 * With no portal configured (the self-hosted default) creation just finishes.
 */
type CreateCommunity = ReturnType<typeof useCommunities>["createCommunity"];

describe("CommunitySidebar community creation", () => {
  const createNamedCommunity = async (
    createCommunity: Mock<CreateCommunity>,
    { native = false } = {}
  ) => {
    if (native) asPhoneThatMayNotSell();
    const { router } = renderPage(
      () => (
        <SidebarProvider>
          <CommunitySidebar />
        </SidebarProvider>
      ),
      {
        communities: {
          communities: [entry({ name: "Alpha" })],
          activeCommunityId: 1,
          createCommunity,
        },
        server: { isNativePlatform: native },
      }
    );
    fireEvent.click(await screen.findByRole("button", { name: "Create Community" }));
    fireEvent.change(await screen.findByLabelText("Community name"), {
      target: { value: "Beta" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create community" }));
    return router;
  };

  beforeEach(() => {
    state.billing = null;
    mintMock.mockReset();
  });

  it("sends the creator to the portal with the minted token in the fragment", async () => {
    state.billing = { url: "https://billing.example.com" };
    mintMock.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const createCommunity = vi
      .fn<CreateCommunity>()
      .mockResolvedValue(buildCommunity({ id: 42, name: "Beta" }));
    const tab = { location: { href: "" }, opener: {} as unknown, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    await createNamedCommunity(createCommunity);

    await waitFor(() => expect(mintMock).toHaveBeenCalledWith(42));
    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/upgrade?lang=en#handoff=TOK")
    );
    openSpy.mockRestore();
  });

  it("opens nothing when the deployment has no billing portal", async () => {
    const createCommunity = vi
      .fn<CreateCommunity>()
      .mockResolvedValue(buildCommunity({ id: 42, name: "Beta" }));
    const openSpy = vi.spyOn(window, "open");

    await createNamedCommunity(createCommunity);

    await waitFor(() => expect(createCommunity).toHaveBeenCalled());
    expect(openSpy).not.toHaveBeenCalled();
    expect(mintMock).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("lands the creator in the community they just made", async () => {
    const createCommunity = vi
      .fn<CreateCommunity>()
      .mockResolvedValue(buildCommunity({ id: 42, name: "Beta" }));

    const router = await createNamedCommunity(createCommunity);

    // A new community is empty, so being dropped anywhere but inside it leaves
    // the creator hunting for the thing they just made.
    await waitFor(() => expect(router.state.location.pathname).toBe("/c/42"));
    // …and naming its first initiative is the next thing to do either way, so
    // the wizard is the arrival rather than something to go and find.
    expect(router.state.location.search).toMatchObject({ create: "true" });
  });

  it("keeps a failed create on its error instead of navigating away", async () => {
    const createCommunity = vi.fn<CreateCommunity>().mockRejectedValue(new Error("nope"));

    const router = await createNamedCommunity(createCommunity);

    await waitFor(() => expect(createCommunity).toHaveBeenCalled());
    // The dialog owns the failure: leaving the page would throw away the
    // message the creator needs in order to try again.
    expect(router.state.location.pathname).toBe("/");
  });

  it("opens nothing in the phone app, which may not sell", async () => {
    state.billing = { url: "https://billing.example.com" };
    const createCommunity = vi
      .fn<CreateCommunity>()
      .mockResolvedValue(buildCommunity({ id: 42, name: "Beta" }));
    const openSpy = vi.spyOn(window, "open");
    vi.mocked(toast.info).mockClear();

    const router = await createNamedCommunity(createCommunity, { native: true });

    await waitFor(() => expect(router.state.location.pathname).toBe("/c/42"));
    expect(openSpy).not.toHaveBeenCalled();
    expect(mintMock).not.toHaveBeenCalled();
    expect(toast.info).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("closes the reserved tab when creation fails", async () => {
    state.billing = { url: "https://billing.example.com" };
    const createCommunity = vi.fn<CreateCommunity>().mockRejectedValue(new Error("nope"));
    const tab = { location: { href: "" }, opener: {} as unknown, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    await createNamedCommunity(createCommunity);

    await waitFor(() => expect(tab.close).toHaveBeenCalled());
    expect(mintMock).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});

describe("the way into the community directory", () => {
  beforeEach(() => {
    state.communityDirectory = true;
  });

  it("sits in the rail under the add-a-community button", async () => {
    setup([entry({ id: 1, name: "Alpha" })]);

    const link = await screen.findByRole("link", { name: "Join a community" });
    expect(link).toHaveAttribute("href", "/communities");
  });

  it("is offered even where communities cannot be created", async () => {
    // A deployment with community creation switched off is exactly where joining an
    // existing community is the only way into one.
    renderPage(
      () => (
        <SidebarProvider>
          <CommunitySidebar />
        </SidebarProvider>
      ),
      {
        communities: {
          communities: [entry({ id: 1, name: "Alpha" })],
          canCreateCommunities: false,
        },
      }
    );

    expect(await screen.findByRole("link", { name: "Join a community" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create community" })).not.toBeInTheDocument();
  });

  it("is repeated in the expanded community list", async () => {
    setup([entry({ id: 1, name: "Alpha" })]);
    const { panel } = await openFlyout();

    expect(within(panel).getByRole("link", { name: "Join a community" })).toBeInTheDocument();
  });

  it("is absent where the platform owner runs no directory", async () => {
    state.communityDirectory = false;
    setup([entry({ id: 1, name: "Alpha" })]);
    const { panel } = await openFlyout();

    expect(screen.queryByRole("link", { name: "Join a community" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: "Join a community" })).not.toBeInTheDocument();
  });
});

describe("the mark on the logo", () => {
  it("says how much is waiting in messages", async () => {
    // Inside a community the home link is the only thing pointing at My
    // Messages, so it is the only place the mark can be seen from there.
    waiting.mockReturnValue(3);
    setup([entry({ id: 1, name: "Alpha" })]);

    const home = await screen.findByRole("link", { name: /home/i });
    expect(within(home).getByText(/3/)).toBeInTheDocument();
  });

  it("marks nothing when nothing is waiting", async () => {
    setup([entry({ id: 1, name: "Alpha" })]);

    const home = await screen.findByRole("link", { name: /home/i });
    expect(within(home).queryByText(/waiting/i)).toBeNull();
  });
});

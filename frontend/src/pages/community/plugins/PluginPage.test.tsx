/**
 * Which token reaches which frame.
 *
 * A handoff names one surface and is spent on first use, so the page re-mints
 * when a reloading page asks again. That re-mint is asynchronous, and the tabs
 * of one plug-in all share an origin — so if the reader switches surfaces while it
 * is in flight, the origin check cannot tell the arriving token from a correct
 * one. The delivery has to be dropped instead.
 */

import { Capacitor } from "@capacitor/core";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { setClock } from "@/ui/host";

const mint = vi.fn();

// Whether this host may sell here, as `useBillingPortal` decides it.
const sale = vi.hoisted(() => ({ canSell: false }));
const portal = vi.hoisted(() => ({
  open: null as unknown as ReturnType<typeof vi.fn>,
  address: null as unknown as ReturnType<typeof vi.fn>,
}));
vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({
    billing: { url: "https://billing.example.com" },
    canSell: sale.canSell,
    openAddress: portal.address,
    openPortal: portal.open,
    sellsNow: async () => sale.canSell,
  }),
}));

// The listing behind the install, as its page reads it: how billing sells it
// here, and whether it was asked at all.
const shelf = vi.hoisted(() => ({
  unavailable: null as {
    reason: string;
    action_url: string | null;
    offer: Record<string, unknown> | null;
  } | null,
  asked: [] as boolean[],
}));
vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListingByUid: (_uid: string, options?: { enabled?: boolean }) => {
    shelf.asked.push(options?.enabled ?? true);
    return {
      data: options?.enabled === false ? undefined : { unavailable: shelf.unavailable },
      isLoading: false,
    };
  },
}));

// Who is reading: the seat, or a member who can't open the billing portal.
const reader = vi.hoisted(() => ({ seat: true }));
vi.mock("@/hooks/useCommunities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunities")>()),
  useCommunities: () => ({ activeCommunity: { id: 3, can: { seat: reader.seat } } }),
}));

vi.mock("@/api/generated/plugins/plugins", () => ({
  createCommunityPluginHandoff: (_communityId: number, _pluginId: number, surfaceId: string) =>
    mint(surfaceId, { scope: "community" }),
  createInitiativePluginHandoff: (
    _communityId: number,
    initiativeId: number,
    _pluginId: number,
    surfaceId: string
  ) => mint(surfaceId, { scope: "initiative", initiativeId }),
}));

/** Where the server says this reader may open each surface. */
const ADMIN_ACCESS = [
  { surface_id: "one", openable_community_wide: true, openable_initiatives: [] },
  { surface_id: "two", openable_community_wide: true, openable_initiatives: [] },
  { surface_id: "inside", openable_community_wide: false, openable_initiatives: [4] },
];

let surfaceAccess = ADMIN_ACCESS;

/** The statement held for the install's listing, as the detail read reports it. */
let entitlement: { active: boolean; reason: string | null; action_url?: string | null } | null =
  null;

/** The catalog listing behind the install, as the detail read reports it. */
type ListingRef = { id: number; source: string; publisher: string; first_party: boolean } | null;
let listingRef: ListingRef = null;

const detail = {
  id: 1,
  name: "Automations",
  listing_uid: "AUTOMATIONS001",
  enabled: true,
  available: true,
  definition: {
    pages: [
      { id: "one", path: "/page/one", name: { en: "One" } },
      { id: "two", path: "/page/two", name: { en: "Two" } },
      {
        id: "inside",
        path: "/page/inside",
        name: { en: "Inside" },
        scopes: ["initiative"],
        admin_only: true,
      },
    ],
  },
};

vi.mock("@/hooks/useCommunityPluginDetail", () => ({
  useCommunityPluginDetail: () => ({
    data: { ...detail, surface_access: surfaceAccess, listing: listingRef, entitlement },
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 3 }));

const handoff = (surfaceId: string) => ({
  handoff_token: `token-for-${surfaceId}`,
  expires_in_seconds: 60,
  page_url: `https://plugin.example.com/page/${surfaceId}`,
  allowed_origins: ["https://plugin.example.com"],
  audience: "initiative-plugin:acme.demo",
  surface_id: surfaceId,
});

/** Every token this page handed to a frame, ignoring the locale nudges. */
const delivered = () =>
  postSpy.mock.calls
    .map(([message]) => message as { type: string; handoff_token?: string })
    .filter((message) => message.type === "initiative-plugin:handoff")
    .map((message) => message.handoff_token);

let postSpy: ReturnType<typeof vi.fn>;
let frameWindow: { postMessage: ReturnType<typeof vi.fn> };

beforeEach(() => {
  mint.mockReset();
  portal.open = vi.fn();
  portal.address = vi.fn();
  shelf.unavailable = null;
  shelf.asked = [];
  reader.seat = true;
  entitlement = null;
  sale.canSell = false;
  surfaceAccess = ADMIN_ACCESS;
  listingRef = null;
  postSpy = vi.fn();
  // Every iframe in the page reports the same window, which is the worst case:
  // nothing about the target distinguishes one surface's frame from another's.
  // Stable across reads, the way a real frame's is — the page compares this
  // value against itself to decide what is still current, so a getter handing
  // back a fresh object each time would answer those comparisons by accident.
  frameWindow = { postMessage: postSpy };
  Object.defineProperty(HTMLIFrameElement.prototype, "contentWindow", {
    configurable: true,
    get: () => frameWindow,
  });
});

const ready = () =>
  window.dispatchEvent(
    new MessageEvent("message", {
      origin: "https://plugin.example.com",
      data: { type: "initiative-plugin:ready" },
      // An announcement says which window it came from; the page exchanges
      // only with the frame it mounted.
      source: frameWindow as unknown as Window,
    })
  );

/**
 * Announce until the page answers.
 *
 * `ready` is a one-shot with no retry: the page only listens once it holds a
 * token for the mounted frame, and an announcement that lands before then is
 * gone for good. A real page cannot arrive early — it loads from the src the
 * token produced — but a test dispatching by hand can, since the mounted frame
 * and the listener that serves it settle in that order and a loaded machine can
 * leave a gap between them. Delivery is synchronous inside the listener, so the
 * announcement that lands is the only one that delivers.
 */
const announceReady = () =>
  waitFor(
    () => {
      if (delivered().length === 0) ready();
      expect(delivered()).toEqual(["token-for-one"]);
    },
    { timeout: 5000 }
  );

describe("PluginPage", () => {
  it("hands the first surface's token to the frame that asked", async () => {
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    await announceReady();
  });

  it("sends the reader's appearance with the token", async () => {
    // The page opens already wearing this page's theme: the resolved mode and
    // the effective palette ride the handoff, since an iframe on another
    // origin cannot read this document's custom properties.
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    await announceReady();

    const message = postSpy.mock.calls
      .map(([sent]) => sent as { type: string; theme?: string; theme_colors?: unknown })
      .find((sent) => sent.type === "initiative-plugin:handoff");
    expect(message?.theme).toBe("light");
    expect(message?.theme_colors).toMatchObject({
      "--background": expect.stringMatching(/^oklch\(/),
      "--foreground": expect.stringMatching(/^oklch\(/),
    });
  });

  it("sends the reader's clock with the token, and when it changes", async () => {
    setClock({ timeFormat: "24", weekStart: 1 });
    try {
      mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
      const { PluginPage } = await import("./PluginPage");
      renderPage(() => <PluginPage pluginId={1} />);

      await screen.findByTitle("Automations");
      await announceReady();

      type Sent = { type: string; time_format?: string; week_start?: number };
      const sent = () => postSpy.mock.calls.map(([message]) => message as Sent);
      expect(sent().find((m) => m.type === "initiative-plugin:handoff")).toMatchObject({
        time_format: "24",
        week_start: 1,
      });

      act(() => setClock({ weekStart: 6 }));
      expect(
        sent()
          .filter((m) => m.type === "initiative-plugin:clock")
          .at(-1)
      ).toMatchObject({
        time_format: "24",
        week_start: 6,
      });
    } finally {
      setClock({ timeFormat: "system", weekStart: 0 });
    }
  });

  it("says with the token whether the host may sell here", async () => {
    // A plug-in's page hides its own purchase copy where the host may not sell.
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
    const { PluginPage } = await import("./PluginPage");
    const handoffSent = () =>
      postSpy.mock.calls
        .map(([sent]) => sent as { type: string; sells?: unknown })
        .find((sent) => sent.type === "initiative-plugin:handoff");

    const { unmount } = renderPage(() => <PluginPage pluginId={1} />);
    await screen.findByTitle("Automations");
    await announceReady();
    expect(handoffSent()?.sells).toBe(false);
    unmount();

    postSpy.mockClear();
    sale.canSell = true;
    renderPage(() => <PluginPage pluginId={1} />);
    await screen.findByTitle("Automations");
    await announceReady();
    expect(handoffSent()?.sells).toBe(true);
  });

  it("frames no page served from the app's own origin", async () => {
    mint.mockImplementation((surfaceId: string) =>
      Promise.resolve({ ...handoff(surfaceId), page_url: `${window.location.origin}/page` })
    );
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    expect(await screen.findByText("This plug-in could not be opened")).toBeInTheDocument();
    expect(screen.queryByTitle("Automations")).toBeNull();
  });

  it("ignores an announcement from a window it did not mount", async () => {
    // A plug-in may hold more than one window at its own address, so the page
    // matches an announcement to the frame it mounted rather than to the
    // origin. The token stays unspent for the frame that does ask.
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    await waitFor(() => expect(mint).toHaveBeenCalledWith("one", expect.anything()));

    window.dispatchEvent(
      new MessageEvent("message", {
        origin: "https://plugin.example.com",
        data: { type: "initiative-plugin:ready" },
        source: { postMessage: vi.fn() } as unknown as Window,
      })
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(delivered()).toEqual([]);

    // The real frame still gets its token.
    await announceReady();
  });

  it("drops a re-mint that resolves after the surface changed", async () => {
    // First surface mints immediately; the re-mint it triggers is held open so
    // the tab can change underneath it.
    let releaseStale: (value: unknown) => void = () => {};
    mint
      .mockImplementationOnce((surfaceId: string) => Promise.resolve(handoff(surfaceId)))
      .mockImplementationOnce(() => new Promise((resolve) => (releaseStale = resolve)))
      .mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));

    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    await announceReady(); // spends the first token

    ready(); // the page reloaded: starts the re-mint that will go stale
    (await screen.findByText("Two")).click();
    await waitFor(() => expect(mint).toHaveBeenCalledWith("two", expect.anything()));

    // The held re-mint now answers, for a surface nobody is looking at.
    releaseStale(handoff("one"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Unchanged: the stale token was dropped rather than handed to the frame
    // now showing the other surface. Surface two has minted but not been asked,
    // so nothing has been delivered for it either.
    expect(delivered()).toEqual(["token-for-one"]);
  });
});

describe("PluginPage, read inside an initiative", () => {
  beforeEach(() => {
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
  });

  it("offers the surfaces that asked to render here, and no others", async () => {
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} initiativeId={4} />);

    await screen.findByTitle("Automations");
    // The two community-wide tabs belong to the other page. One surface left means
    // no tab strip at all, so the name appears nowhere.
    expect(screen.queryByText("One")).toBeNull();
    expect(screen.queryByText("Two")).toBeNull();
    await waitFor(() => expect(mint).toHaveBeenCalledWith("inside", expect.anything()));
  });

  it("mints through the route that names the initiative", async () => {
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} initiativeId={4} />);

    await screen.findByTitle("Automations");
    await waitFor(() =>
      expect(mint).toHaveBeenCalledWith("inside", { scope: "initiative", initiativeId: 4 })
    );
  });

  it("says so plainly when nothing here is for this reader", async () => {
    // A plain member of the initiative: the only surface here is for admins,
    // so the server lists no initiative for it — nothing to open or mint.
    surfaceAccess = ADMIN_ACCESS.map((one) =>
      one.surface_id === "inside" ? { ...one, openable_initiatives: [] } : one
    );
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} initiativeId={4} />);

    await screen.findByText(/nothing to show|no page of its own|has no page/i);
    expect(mint).not.toHaveBeenCalled();
  });
});

describe("PluginPage, who a plug-in comes from", () => {
  beforeEach(() => {
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
    listingRef = { id: 9, source: "registry", publisher: "Acme Apps", first_party: false };
  });

  it("offers to report the plug-in on every platform", async () => {
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
  });

  it("opens straight away on the web, with no notice", async () => {
    listingRef = { id: 9, source: "operator", publisher: "Acme Apps", first_party: false };
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    expect(screen.queryByText("Before you open Automations")).toBeNull();
  });

  it("says who made it once per member on an iPhone, before anything opens", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    const user = userEvent.setup();
    const member = { user: buildUser() };
    const { PluginPage } = await import("./PluginPage");
    const { unmount } = renderPage(() => <PluginPage pluginId={1} />, { auth: member });

    expect(await screen.findByText("Before you open Automations")).toBeInTheDocument();
    expect(screen.getByText("Automations is made by Acme Apps.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
    // Nothing is minted, and no frame mounted, until the member continues.
    expect(screen.queryByTitle("Automations")).toBeNull();
    expect(mint).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByTitle("Automations")).toBeInTheDocument();
    await waitFor(() => expect(mint).toHaveBeenCalled());
    unmount();

    // Remembered: the next open goes straight to the plug-in.
    const again = renderPage(() => <PluginPage pluginId={1} />, { auth: member });
    expect(await screen.findByTitle("Automations")).toBeInTheDocument();
    expect(screen.queryByText("Before you open Automations")).toBeNull();
    again.unmount();

    // For that member only: somebody else signed in on this phone is told.
    renderPage(() => <PluginPage pluginId={1} />, { auth: { user: buildUser() } });
    expect(await screen.findByText("Before you open Automations")).toBeInTheDocument();
  });

  it("offers to report it when nothing here is for this reader", async () => {
    surfaceAccess = ADMIN_ACCESS.map((one) => ({
      ...one,
      openable_community_wide: false,
      openable_initiatives: [],
    }));
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByText(/nothing to show|no page of its own|has no page/i);
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
  });

  it("neither introduces nor offers to report a plug-in BeyondersStudio publishes", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    listingRef = { id: 9, source: "registry", publisher: "BeyondersStudio", first_party: true };
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={2} />);

    await screen.findByTitle("Automations");
    expect(screen.queryByText("Before you open Automations")).toBeNull();
    expect(screen.queryByRole("button", { name: "Report" })).toBeNull();
  });
});

describe("a plug-in the deployment's term has no seat free for", () => {
  it("shows the seat a request in place of the plug-in", async () => {
    entitlement = { active: false, reason: "term_full" };
    const user = userEvent.setup();
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    expect(
      await screen.findByText("This deployment's plan has no seat free for Automations.")
    ).toBeInTheDocument();
    expect(mint).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Request" }));
    expect(portal.open).toHaveBeenCalledWith(3, "manage", null, {
      request: "plugin",
      listing: "AUTOMATIONS001",
    });
  });

  it("tells a member to ask the community's admins, with no button", async () => {
    entitlement = { active: false, reason: "term_full" };
    reader.seat = false;
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    expect(
      await screen.findByText("Ask your community's admins to request it.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request" })).toBeNull();
    expect(mint).not.toHaveBeenCalled();
  });
});

describe("a plug-in whose plan has ended", () => {
  const ACTION = "https://billing.example.com/manage?app=AUTOMATIONS001";
  const plans = {
    charge: "subscription",
    way: "buy",
    upgrade: false,
    lines: [{ id: "small", name: "Small", display: "$12/mo" }],
  };

  beforeEach(() => {
    entitlement = { active: false, reason: null, action_url: ACTION };
    sale.canSell = true;
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
  });

  it("still opens, says so above it, and offers the seat a plan", async () => {
    shelf.unavailable = { reason: "entitlement_required", action_url: ACTION, offer: plans };
    const user = userEvent.setup();
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    expect(screen.getByText("This plug-in's plan has ended.")).toBeInTheDocument();
    expect(mint).toHaveBeenCalled();
    expect(screen.getByText("Small")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Choose a plan" }));
    expect(portal.address).toHaveBeenCalledWith(3, ACTION);
  });

  it("leads the seat to the plans when its plan sells none", async () => {
    shelf.unavailable = {
      reason: "entitlement_required",
      action_url: ACTION,
      offer: { ...plans, way: "none", upgrade: true },
    };
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    expect(
      screen.getByText(
        "Your community's plan doesn't include paid plug-ins. Plans that do are on the plans page."
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See plans" })).toBeInTheDocument();
  });

  it("without an answer from billing, sends the seat where the install says", async () => {
    shelf.unavailable = { reason: "entitlement_required", action_url: null, offer: null };
    const user = userEvent.setup();
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    await user.click(screen.getByRole("button", { name: "See options" }));
    expect(portal.address).toHaveBeenCalledWith(3, ACTION);
  });

  it("tells a member it ended, with nothing to press and nothing asked", async () => {
    reader.seat = false;
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    expect(screen.getByText("This plug-in's plan has ended.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /See options|Choose a plan/ })).toBeNull();
    expect(shelf.asked.every((enabled) => !enabled)).toBe(true);
  });

  it("says nothing while its plan is running", async () => {
    entitlement = { active: true, reason: null, action_url: null };
    const { PluginPage } = await import("./PluginPage");
    renderPage(() => <PluginPage pluginId={1} />);

    await screen.findByTitle("Automations");
    expect(screen.queryByText("This plug-in's plan has ended.")).toBeNull();
  });
});

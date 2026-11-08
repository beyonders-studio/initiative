import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http, type JsonBodyType } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { catalogUrl, portalPricingUrl } from "@/hooks/useBillingCatalog";
import { androidApkUrl, DOCS_URL, desktopInstallerUrl, docsUrl, REPO_URL } from "@/lib/links";
import { TOOLS, toolCamelPlural } from "@/lib/tools";

import landing from "../../../public/locales/en/landing.json";
import { DownloadPage } from "./DownloadPage";
import {
  EMBED_CTA,
  EMBED_HEIGHT,
  FRAME_TIMEOUT_MS,
  SELF_HOST_GUIDE,
} from "./pricing/PricingGridFrame";
import { PricingPage } from "./pricing/PricingPage";
import { WhatsNewPage, WhatsNewPostPage } from "./WhatsNewPage";
import { WelcomePage } from "./welcome/WelcomePage";

const PORTAL = "https://billing.example.com";
const NATIVE_FLOOR = "0.69.0";
const DESKTOP_FLOOR = "0.74.0";

const tier = (overrides: Record<string, unknown>) => ({
  tagline: "A tagline",
  audience: "Somebody",
  highlight: false,
  badge: null,
  price: { base_monthly: 0, display: "Free", sub_display: null },
  limits: { storage_display: "1 GB", automations_display: null },
  support: "Peer support",
  features: [],
  feature_keys: [],
  cta: { kind: "checkout", label: "Choose it", note: null },
  ...overrides,
});

/** A price book in the shape the portal serves. Names and numbers are
 *  invented here, because none of them live in this repository. */
const CATALOG = {
  catalog_version: 1,
  updated: "2026-01-01",
  currency: "USD",
  headline: "Where the club keeps its act together",
  subhead: "One community per group, all from the same login.",
  tiers: [
    tier({
      id: "self_hosted",
      name: "Self-Hosted",
      kind: "free_self_hosted",
      cta: { kind: "external", label: "Read the self-host guide", note: null },
    }),
    tier({
      id: "pewter",
      name: "Pewter",
      kind: "free_hosted",
      limits: { storage_display: "100 MB", members_display: "Just you" },
      cta: { kind: "signup", label: "Make your free community", note: "No card." },
    }),
    tier({
      id: "brass",
      name: "Brass",
      kind: "paid",
      highlight: true,
      badge: "Most groups land here",
      price: { base_monthly: 7, display: "$7", sub_display: "per month" },
      cta: { kind: "checkout", label: "Choose Brass", note: null },
    }),
    tier({
      id: "obsidian",
      name: "Obsidian",
      kind: "enterprise",
      price: { base_monthly: null, display: "Contact sales", sub_display: null },
      cta: { kind: "contact", label: "Talk to us", note: null },
    }),
  ],
  features: {},
  footnotes: {},
};

const stubConfig = (billing: { url: string } | null, extra: Record<string, unknown> = {}) =>
  http.get("/api/v1/config", () =>
    HttpResponse.json({
      captcha: null,
      billing: billing ? { ...billing, operator_handoff: false } : null,
      max_upload_bytes: 1024,
      community_directory_enabled: false,
      community_age_gate_enabled: true,
      login_methods: ["password"],
      min_native_version: NATIVE_FLOOR,
      min_desktop_version: DESKTOP_FLOOR,
      ...extra,
    })
  );

const stubBootstrap = (publicRegistrationEnabled: boolean) =>
  http.get("/api/v1/auth/bootstrap", () =>
    HttpResponse.json({ has_users: true, public_registration_enabled: publicRegistrationEnabled })
  );

const stubCatalog = (body: JsonBodyType = CATALOG, status = 200) =>
  http.get(catalogUrl(PORTAL), () => HttpResponse.json(body, { status }));

/** Nobody signed in: the pages' whole audience. */
const signedOut = { auth: { token: null, user: null, loading: false } };

const stubPush = (enabled: boolean) =>
  http.get("/api/v1/settings/fcm-config", () =>
    HttpResponse.json({
      enabled,
      project_id: null,
      application_id: null,
      api_key: null,
      sender_id: null,
    })
  );

beforeEach(() => {
  server.use(stubConfig(null), stubBootstrap(true), stubPush(false));
});

describe("WelcomePage", () => {
  const renderHome = () => renderPage(WelcomePage, signedOut);

  it("leads with signing up, and keeps signing in a link away", async () => {
    renderHome();

    expect(
      await screen.findByRole("heading", { level: 1, name: landing.hero.titleAria })
    ).toBeInTheDocument();
    const signUp = screen.getAllByRole("link", { name: landing.hero.signUp });
    expect(signUp[0]).toHaveAttribute("href", "/start");
    expect(screen.getAllByRole("link", { name: landing.hero.signIn })[0]).toHaveAttribute(
      "href",
      "/login"
    );
    expect(screen.getAllByRole("link", { name: landing.closer.start })[0]).toHaveAttribute(
      "href",
      "/start"
    );
  });

  it("offers only signing in when registration is closed", async () => {
    server.use(stubBootstrap(false));
    renderHome();

    await screen.findByRole("heading", { level: 1, name: landing.hero.titleAria });
    // The bootstrap answer arrives asynchronously; the sign-up buttons leave with it.
    await waitFor(() => {
      expect(screen.queryAllByRole("link", { name: landing.hero.signUp })).toHaveLength(0);
      expect(screen.queryByRole("link", { name: landing.closer.start })).not.toBeInTheDocument();
    });
    expect(screen.getAllByRole("link", { name: landing.hero.signIn }).length).toBeGreaterThan(0);
  });

  it("sends somebody already signed in into the app", async () => {
    const { router } = renderPage(WelcomePage, { auth: { token: "test-token", loading: false } });

    // The app home is My Tasks; the front door is /welcome.
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });

  it("draws one card per tool in the registry", async () => {
    renderHome();

    await waitFor(() => {
      expect(document.querySelectorAll("[data-tool]")).toHaveLength(TOOLS.length);
    });
  });

  it("draws people working on the same page at once", async () => {
    renderHome();

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: `${landing.together.titleStart} ${landing.together.titleHighlight}`,
      })
    ).toBeInTheDocument();
    const drawing = screen.getByRole("img", { name: landing.together.drawingAria });
    // Three people on it: Maya typing, Dev selecting, Priya commenting.
    expect(within(drawing).getByText(landing.together.people.maya)).toBeInTheDocument();
    expect(within(drawing).getByText(landing.together.people.dev)).toBeInTheDocument();
    expect(within(drawing).getByText(landing.together.comments.text)).toBeInTheDocument();
  });

  it("says accounts are free only where this deployment sells plans", async () => {
    renderHome();
    await screen.findByRole("heading", { level: 1, name: landing.hero.titleAria });
    expect(screen.queryByText(landing.hero.freeTitle)).not.toBeInTheDocument();
  });

  it("says accounts are free where a billing portal is set up", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog());
    renderHome();

    expect(await screen.findByText(landing.hero.freeTitle)).toBeInTheDocument();
  });

  it("offers Pricing in the header once there is a price book", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog());
    renderHome();

    const pricing = await screen.findAllByRole("link", { name: landing.nav.pricing });
    expect(pricing[0]).toHaveAttribute("href", "/pricing");
  });

  it("offers no Pricing link when the portal cannot be reached", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog({ detail: "down" }, 503));
    renderHome();

    await screen.findByRole("heading", { level: 1, name: landing.hero.titleAria });
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: landing.nav.pricing })).not.toBeInTheDocument();
    });
  });

  it("shows the community directory only where the server runs one", async () => {
    renderHome();
    await screen.findByRole("heading", { level: 1, name: landing.hero.titleAria });
    expect(screen.queryByText(landing.directory.title)).not.toBeInTheDocument();
  });

  it("brings a category's community to the front of the deck", async () => {
    server.use(stubConfig(null, { community_directory_enabled: true }));
    renderHome();

    const music = await screen.findByRole("button", { name: landing.directory.producers.category });
    expect(music).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(music);
    expect(music).toHaveAttribute("aria-pressed", "true");
    // Only the card in front is read out.
    const deck = screen.getByRole("list", { name: landing.directory.deckAria });
    expect(within(deck).getByText(landing.directory.producers.name)).toBeVisible();
    expect(screen.getByRole("link", { name: landing.directory.signUp })).toHaveAttribute(
      "href",
      "/start"
    );
  });

  it("names itself to the browser and search engines", async () => {
    renderHome();
    await waitFor(() => {
      expect(document.title).toBe(landing.meta.homeTitle);
    });
  });

  it("lets a keyboard skip straight to the content", async () => {
    renderHome();
    expect(await screen.findByRole("link", { name: landing.nav.skip })).toHaveAttribute(
      "href",
      "#landing-main"
    );
  });

  it("can pause the scrolling communities", async () => {
    renderHome();
    const pause = await screen.findByRole("button", { name: landing.communities.pause });
    fireEvent.click(pause);
    expect(screen.getByRole("button", { name: landing.communities.play })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("keeps what's new in the app, and GitHub under socials", async () => {
    renderHome();
    expect(await screen.findByRole("link", { name: landing.footer.changelog })).toHaveAttribute(
      "href",
      "/whats-new"
    );
    expect(screen.getByRole("heading", { name: landing.footer.socials })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute("href", REPO_URL);
  });

  it("links the docs", async () => {
    renderHome();

    expect((await screen.findAllByRole("link", { name: landing.nav.docs }))[0]).toHaveAttribute(
      "href",
      docsUrl()
    );
    expect(screen.getByRole("link", { name: landing.footer.faq })).toHaveAttribute(
      "href",
      docsUrl("faq/")
    );
  });
});

describe("DownloadPage", () => {
  const renderDownload = () => renderPage(DownloadPage, signedOut);

  it("offers the Android app from the release this server's floor names", async () => {
    renderDownload();

    const apk = await screen.findByTestId("android-apk");
    expect(apk).toHaveAttribute("href", androidApkUrl(NATIVE_FLOOR));
    expect(apk).toHaveAttribute("download");
  });

  it("features the visitor's own device and lists every way to get it", async () => {
    renderDownload();

    // jsdom is not a phone.
    expect(
      await screen.findByRole("heading", { name: landing.download.desktopTitle })
    ).toBeInTheDocument();
    const cards = screen.getByRole("list", { name: landing.download.cardsAria });
    expect(cards.querySelectorAll("[data-platform]")).toHaveLength(4);
  });

  it("promises push notifications only where the server sends them", async () => {
    renderDownload();
    expect(await screen.findByText(landing.download.description)).toBeInTheDocument();

    server.use(stubPush(true));
    renderDownload();
    expect(await screen.findByText(landing.download.descriptionPush)).toBeInTheDocument();
  });

  it("offers this computer's installer from the release its own floor names", async () => {
    renderDownload();

    // jsdom says Linux.
    const [installer] = await screen.findAllByTestId("desktop-installer");
    expect(installer).toHaveAttribute("href", desktopInstallerUrl(DESKTOP_FLOOR, "linux"));
    expect(installer).toHaveAttribute("download");
  });

  it("shows the browser's install prompt once, then points at the guide", async () => {
    renderDownload();
    const [install] = await screen.findAllByRole("link", {
      name: landing.download.browserInstall,
    });

    const prompt = vi.fn().mockResolvedValue(undefined);
    act(() => {
      window.dispatchEvent(Object.assign(new Event("beforeinstallprompt"), { prompt }));
    });
    const [button] = await screen.findAllByRole("button", {
      name: landing.download.browserInstall,
    });
    fireEvent.click(button);
    expect(prompt).toHaveBeenCalledTimes(1);

    // Spent after one use, whatever the answer: the guide again.
    const [again] = await screen.findAllByRole("link", { name: landing.download.browserInstall });
    expect(again).toHaveAttribute("href", install.getAttribute("href"));
  });

  it("mentions passkeys only where the server offers them", async () => {
    renderDownload();
    await screen.findByTestId("android-apk");
    expect(screen.queryByText(landing.download.passkeysTitle)).not.toBeInTheDocument();
  });
});

describe("PricingPage", () => {
  const renderPricing = () => renderPage(PricingPage, { ...signedOut, initialRoute: "/pricing" });

  it("sends the visitor to the front page where no plans are sold", async () => {
    const { router } = renderPricing();

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/welcome");
    });
  });

  const frameOf = async () =>
    (await screen.findByTitle(landing.pricing.tierListAria)) as HTMLIFrameElement;

  const fromFrame = (frame: HTMLIFrameElement, data: unknown, origin = PORTAL) =>
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", { data, origin, source: frame.contentWindow })
      );
    });

  it("frames the portal's grid in the reader's language and theme", async () => {
    const asked: string[] = [];
    server.use(
      stubConfig({ url: PORTAL }),
      http.get(catalogUrl(PORTAL), ({ request }) => {
        asked.push(request.url);
        return HttpResponse.json(CATALOG);
      })
    );
    renderPricing();

    expect(await screen.findByRole("heading", { name: CATALOG.headline })).toBeInTheDocument();
    const frame = await frameOf();
    const src = new URL(frame.src);
    expect(`${src.origin}${src.pathname}`).toBe(`${PORTAL}/embed/pricing`);
    expect(src.searchParams.get("lang")).toBe("en");
    expect(["light", "dark"]).toContain(src.searchParams.get("theme"));
    expect(new URL(asked[0]).searchParams.get("lang")).toBe("en");
  });

  it("fits the frame to the grid", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog());
    renderPricing();

    const frame = await frameOf();
    fromFrame(frame, { type: EMBED_HEIGHT, height: 1834.4 });
    await waitFor(() => expect(frame.style.height).toBe("1835px"));
  });

  it("sends each plan's button where it belongs", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog());
    const tab = { opener: {} as unknown };
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const before = window.location.href;
    const { router } = renderPricing();

    const frame = await frameOf();
    // Buying goes to the portal; running it yourself goes to the install
    // guide; signing up is this app's own door.
    fromFrame(frame, { type: EMBED_CTA, tier: "brass", kind: "checkout" });
    expect(open).toHaveBeenLastCalledWith(portalPricingUrl(PORTAL), "_blank");
    // A new tab, cut loose from this page, and this page stays put.
    expect(tab.opener).toBeNull();
    expect(window.location.href).toBe(before);
    fromFrame(frame, { type: EMBED_CTA, tier: "self_hosted", kind: "external" });
    expect(open).toHaveBeenLastCalledWith(SELF_HOST_GUIDE, "_blank");
    expect(SELF_HOST_GUIDE).toBe(docsUrl("running-a-server/installation/"));
    fromFrame(frame, { type: EMBED_CTA, tier: "pewter", kind: "signup" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/start"));
    open.mockRestore();
  });

  it("offers a link to the plans when the grid never arrives", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      server.use(stubConfig({ url: PORTAL }), stubCatalog());
      renderPricing();

      await frameOf();
      act(() => {
        vi.advanceTimersByTime(FRAME_TIMEOUT_MS);
      });
      const fallback = await screen.findByRole("status");
      expect(within(fallback).getByText(landing.pricing.unavailableTitle)).toBeInTheDocument();
      expect(within(fallback).getByRole("link", { name: /See every plan/ })).toHaveAttribute(
        "href",
        portalPricingUrl(PORTAL)
      );
      expect(screen.queryByTitle(landing.pricing.tierListAria)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the grid once it has arrived", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      server.use(stubConfig({ url: PORTAL }), stubCatalog());
      renderPricing();

      const frame = await frameOf();
      fromFrame(frame, { type: EMBED_HEIGHT, height: 1200 });
      act(() => {
        vi.advanceTimersByTime(FRAME_TIMEOUT_MS * 2);
      });
      expect(screen.getByTitle(landing.pricing.tierListAria)).toBe(frame);
    } finally {
      vi.useRealTimers();
    }
  });

  it("sends a free plan's sign-up to the login page when registration is closed", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog(), stubBootstrap(false));
    const { router } = renderPricing();

    const frame = await frameOf();
    await waitFor(async () => {
      fromFrame(frame, { type: EMBED_CTA, tier: "pewter", kind: "signup" });
      expect(router.state.location.pathname).toBe("/login");
    });
  });

  it("ignores messages from anywhere but the portal's frame", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog());
    const open = vi.spyOn(window, "open").mockReturnValue({} as Window);
    const { router } = renderPricing();

    const frame = await frameOf();
    fromFrame(frame, { type: EMBED_CTA, kind: "checkout" }, "https://elsewhere.example.com");
    fromFrame(frame, { type: EMBED_HEIGHT, height: 50 }, "https://elsewhere.example.com");
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: EMBED_CTA, kind: "signup" },
          origin: PORTAL,
          source: window,
        })
      );
    });
    expect(open).not.toHaveBeenCalled();
    expect(frame.style.height).not.toBe("50px");
    expect(router.state.location.pathname).toBe("/pricing");
    open.mockRestore();
  });

  it("says so when the price book cannot be read", async () => {
    server.use(stubConfig({ url: PORTAL }), stubCatalog({ detail: "down" }, 503));
    renderPricing();

    expect(await screen.findByText(landing.pricing.unavailableTitle)).toBeInTheDocument();
  });

  // The cards reach straight through to these, so a tier arriving without
  // one would throw mid-render and take the page down with it.
  it.each([
    ["price", { ...CATALOG.tiers[2], price: undefined }],
    ["cta", { ...CATALOG.tiers[2], cta: undefined }],
    ["limits", { ...CATALOG.tiers[2], limits: undefined }],
    ["name", { ...CATALOG.tiers[2], name: 7 }],
  ])("refuses a price book whose tier is missing %s", async (_field, broken) => {
    server.use(
      stubConfig({ url: PORTAL }),
      stubCatalog({ ...CATALOG, tiers: [CATALOG.tiers[1], broken] })
    );
    renderPricing();

    expect(await screen.findByText(landing.pricing.unavailableTitle)).toBeInTheDocument();
  });
});

const RELEASES = [
  {
    version: "0.73.2",
    date: "2026-09-29",
    changes:
      "### Fixed\n\n- **Uploads resume after a dropped connection.** See [Installation](docs/en/running-a-server/installation.md#checking-an-image-is-ours).\n- **Calendars load faster.**",
  },
  {
    version: "0.73.1",
    date: "2026-09-28",
    changes: "### Fixed\n\n- **Search finds archived wikis.**",
  },
];

const stubChangelog = () =>
  http.get("/api/v1/changelog", ({ request }) => {
    const version = new URL(request.url).searchParams.get("version");
    return HttpResponse.json({
      entries: version ? RELEASES.filter((entry) => entry.version === version) : RELEASES,
    });
  });

describe("WhatsNewPage", () => {
  it("lists each release as a post with its headlines", async () => {
    server.use(stubChangelog());
    renderPage(WhatsNewPage, signedOut);

    const post = await screen.findByRole("link", {
      name: landing.whatsNew.postTitle.replace("{{version}}", "0.73.2"),
    });
    expect(post).toHaveAttribute("href", "/whats-new/0.73.2");
    expect(screen.getByText("Uploads resume after a dropped connection")).toBeInTheDocument();
    expect(screen.getByText("Search finds archived wikis")).toBeInTheDocument();
  });

  it("says so when the changelog can't be read", async () => {
    server.use(http.get("/api/v1/changelog", () => HttpResponse.json({}, { status: 500 })));
    renderPage(WhatsNewPage, signedOut);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("shows a whole release, with its docs links pointing at the docs site", async () => {
    server.use(stubChangelog());
    renderPage(WhatsNewPostPage, {
      ...signedOut,
      initialRoute: "/whats-new/$version",
      routeParams: { version: "0.73.2" },
    });

    expect(await screen.findByRole("link", { name: "Installation" })).toHaveAttribute(
      "href",
      `${DOCS_URL}running-a-server/installation/#checking-an-image-is-ours`
    );
    expect(screen.getByRole("heading", { level: 2, name: "Fixed" })).toBeInTheDocument();
  });
});

describe("landing copy covers the tool registry", () => {
  it("has a blurb for every tool, keyed by its camel plural", () => {
    const blurbs = landing.tools as Record<string, string>;
    for (const tool of TOOLS) {
      const key = toolCamelPlural(tool);
      expect(blurbs[key], `landing.json tools.${key}`).toBeTypeOf("string");
    }
  });
});

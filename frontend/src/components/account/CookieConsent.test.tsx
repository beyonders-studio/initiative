import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import {
  ConsentCategory,
  dismissReopenedConsent,
  hasConsent,
  KNOWN_CONSENT_CATEGORIES,
  reopenConsent,
} from "@/lib/consent";
import { removeItem, setItem } from "@/lib/storage";

import { CookieConsent } from "./CookieConsent";

const mocks = vi.hoisted(() => ({
  config: {
    captcha: null as { provider: string; site_key: string } | null,
    cookieConsentEnabled: true,
    cookieCategories: ["analytics", "marketing"] as string[],
    isLoading: false,
  },
  legal: { enabled: false, documents: [] as { slug: string; title: string }[] },
}));

vi.mock("@/hooks/useAppConfig", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAppConfig")>()),
  useAppConfig: () => mocks.config,
}));

vi.mock("@/hooks/useLegalDocuments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useLegalDocuments")>()),
  useLegalIndex: () => ({ ...mocks.legal, required: [], isLoading: false }),
}));

const chooser = () => screen.queryByRole("region", { name: /^cookies$/i });

/**
 * Mount the chooser against a browser holding `stored` — no answer by default.
 *
 * The store reads storage through, so seeding it here is what a browser
 * arriving with that answer looks like to everything downstream.
 */
const mount = (options: { stored?: string; native?: boolean } = {}) => {
  if (options.stored === undefined) removeItem("cookie-consent");
  else setItem("cookie-consent", options.stored);

  return renderWithProviders(<CookieConsent />, {
    server: { isNativePlatform: options.native ?? false },
  });
};

const answered = (granted: string[]) =>
  JSON.stringify({ version: 1, decidedAt: "2026-09-20T00:00:00.000Z", granted });

describe("CookieConsent", () => {
  beforeEach(() => {
    mocks.config = {
      captcha: null,
      cookieConsentEnabled: true,
      cookieCategories: ["analytics", "marketing"],
      isLoading: false,
    };
    mocks.legal = { enabled: false, documents: [] };
    // A chooser a test reopened stays open for the next one otherwise.
    dismissReopenedConsent();
  });

  it("puts the question to somebody arriving for the first time", async () => {
    mount();

    expect(chooser()).toBeInTheDocument();
  });

  it("offers refusing and accepting as one click each, at the same weight", async () => {
    mount();

    const reject = screen.getByRole("button", { name: /reject optional/i });
    const accept = screen.getByRole("button", { name: /accept all/i });

    expect(reject.className).toBe(accept.className);
  });

  it("switches nothing on when the answer is no", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /reject optional/i }));

    expect(chooser()).not.toBeInTheDocument();
    for (const category of KNOWN_CONSENT_CATEGORIES) {
      expect(hasConsent(category)).toBe(false);
    }
  });

  it("switches everything on when the answer is yes", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /accept all/i }));

    for (const category of KNOWN_CONSENT_CATEGORIES) {
      expect(hasConsent(category)).toBe(true);
    }
  });

  it("takes a category at a time", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /^choose$/i }));
    await user.click(screen.getByRole("switch", { name: /analytics/i }));
    await user.click(screen.getByRole("button", { name: /save choices/i }));

    expect(hasConsent(ConsentCategory.analytics)).toBe(true);
    expect(hasConsent(ConsentCategory.marketing)).toBe(false);
  });

  it("starts every switch off, so ignoring the question grants nothing", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /^choose$/i }));

    for (const toggle of within(chooser() as HTMLElement).getAllByRole("switch")) {
      expect(toggle).not.toBeChecked();
    }
  });

  it("gives the essential category no switch, because it has no alternative", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /^choose$/i }));

    expect(within(chooser() as HTMLElement).getAllByRole("switch")).toHaveLength(2);
    expect(screen.getByText(/always on/i)).toBeInTheDocument();
  });

  it("stays gone once answered", async () => {
    mount({ stored: answered([]) });

    expect(chooser()).not.toBeInTheDocument();
  });

  it("comes back when asked for again, showing what is in force", async () => {
    mount({ stored: answered(["analytics"]) });

    reopenConsent();

    expect(await screen.findByRole("region", { name: /^cookies$/i })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /analytics/i })).toBeChecked();
    expect(screen.getByRole("switch", { name: /marketing/i })).not.toBeChecked();
  });

  it("can be closed again, leaving the existing answer alone", async () => {
    const user = userEvent.setup();
    mount({ stored: answered(["analytics"]) });
    reopenConsent();
    await screen.findByRole("region", { name: /^cookies$/i });

    await user.click(screen.getByRole("button", { name: /close/i }));

    expect(chooser()).not.toBeInTheDocument();
    expect(hasConsent(ConsentCategory.analytics)).toBe(true);
  });

  it("offers no close while the question is still open", async () => {
    mount();

    expect(screen.queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
  });

  it("offers a switch only for what the deployment actually uses", async () => {
    mocks.config = { ...mocks.config, cookieCategories: ["analytics"] };
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /^choose$/i }));

    expect(screen.getByRole("switch", { name: /analytics/i })).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /marketing/i })).not.toBeInTheDocument();
  });

  it("accepting grants what is in use and nothing else", async () => {
    mocks.config = { ...mocks.config, cookieCategories: ["analytics"] };
    const user = userEvent.setup();
    mount();

    await user.click(screen.getByRole("button", { name: /accept all/i }));

    expect(hasConsent(ConsentCategory.analytics)).toBe(true);
    expect(hasConsent(ConsentCategory.marketing)).toBe(false);
  });

  it("asks nothing where the deployment uses nothing optional", async () => {
    mocks.config = { ...mocks.config, cookieCategories: [] };
    const user = userEvent.setup();
    mount();

    // A question with no answers is not a question: it says what is kept, and
    // the one button agrees to nothing.
    expect(screen.queryByRole("button", { name: /accept all/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^choose$/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /got it/i }));

    expect(chooser()).not.toBeInTheDocument();
    for (const category of KNOWN_CONSENT_CATEGORIES) {
      expect(hasConsent(category)).toBe(false);
    }
  });

  it("shows no essential row where there is nothing to contrast it with", async () => {
    mocks.config = { ...mocks.config, cookieCategories: [] };
    mount();

    expect(screen.queryByText(/always on/i)).not.toBeInTheDocument();
  });

  it("says nothing where the deployment has not asked it to", async () => {
    mocks.config = { ...mocks.config, cookieConsentEnabled: false };

    mount();

    expect(chooser()).not.toBeInTheDocument();
  });

  it("waits for the deployment's answer rather than appearing and then vanishing", async () => {
    mocks.config = { ...mocks.config, isLoading: true };

    mount();

    expect(chooser()).not.toBeInTheDocument();
  });

  it("is not shown in the installed app, which landed on no site", async () => {
    mount({ native: true });

    expect(chooser()).not.toBeInTheDocument();
  });

  it("names the spam check the deployment put in front of sign-up", async () => {
    mocks.config = { ...mocks.config, captcha: { provider: "turnstile", site_key: "k" } };

    mount();

    expect(screen.getByText(/Cloudflare Turnstile/)).toBeInTheDocument();
  });

  it("claims no third party where the deployment configured none", async () => {
    mount();

    expect(screen.queryByText(/spam check/i)).not.toBeInTheDocument();
  });

  it("points at the deployment's own privacy policy where it has one", async () => {
    mocks.legal = { enabled: true, documents: [{ slug: "privacy", title: "Privacy Policy" }] };

    mount();

    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "/legal/privacy"
    );
  });
});

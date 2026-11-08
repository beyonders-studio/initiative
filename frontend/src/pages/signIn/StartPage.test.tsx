/**
 * The start flow, signed out: which paths a deployment offers, and what the
 * account it ends in is sent with.
 */
import { createMemoryHistory, createRouter } from "@tanstack/react-router";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { buildRouterContext, renderPage } from "@/__tests__/helpers/render";
import { asPhoneThatMayNotSell } from "@/__tests__/helpers/storeSelling";
import { catalogUrl } from "@/hooks/useBillingCatalog";
import { clearStart, readPendingStart } from "@/lib/startFlow";
import { routeTree } from "@/routeTree.gen";

import { StartPage } from "./StartPage";

const PORTAL = "https://billing.example.test";

const deployment = {
  registrationOpen: true,
  directory: true,
  billing: false,
};

const stubDeployment = () =>
  server.use(
    http.get("/api/v1/config", () =>
      HttpResponse.json({
        captcha: null,
        billing: deployment.billing ? { url: PORTAL, operator_handoff: false } : null,
        max_upload_bytes: 1024,
        community_directory_enabled: deployment.directory,
        community_age_gate_enabled: true,
        login_methods: ["password"],
      })
    ),
    http.get("/api/v1/legal", () =>
      HttpResponse.json({
        documents: [
          { slug: "terms", title: "Terms of Service" },
          { slug: "privacy", title: "Privacy Policy" },
        ],
        required: ["terms", "privacy"],
      })
    ),
    http.get("/api/v1/auth/bootstrap", () =>
      HttpResponse.json({
        has_users: true,
        public_registration_enabled: deployment.registrationOpen,
      })
    ),
    http.get("/api/v1/auth/username-available", () =>
      HttpResponse.json({ available: true, discriminator: 42, offer: "signed-42" })
    ),
    http.get("/api/v1/auth/username-suggestions", ({ request }) => {
      suggestionSeeds.push(new URL(request.url).searchParams.get("seed"));
      return HttpResponse.json({ suggestions: ["yonderfan", "lidlifter"] });
    }),
    http.get(catalogUrl(PORTAL), () =>
      HttpResponse.json({
        catalog_version: 1,
        currency: "USD",
        headline: "Plans",
        subhead: "",
        footnotes: {},
        tiers: ["free_hosted", "paid"].map((kind) => ({
          id: kind,
          name: kind === "paid" ? "Brass" : "Seedling",
          kind,
          tagline: "",
          audience: "",
          highlight: false,
          badge: null,
          price: { base_monthly: null, display: kind === "paid" ? "$7" : "$0", sub_display: null },
          limits: {},
          support: "",
          features: [],
          cta: { kind: "signup", label: "Start", note: null },
        })),
      })
    )
  );

const register = vi.fn();
/** The seeds the suggestions were asked for, in order. */
const suggestionSeeds: (string | null)[] = [];

const renderStart = (options: { inviteCode?: string; native?: boolean } = {}) => {
  if (options.native) asPhoneThatMayNotSell();
  return renderPage(StartPage, {
    initialRoute: "/start",
    routerSearch: options.inviteCode ? { invite_code: options.inviteCode } : undefined,
    auth: { user: null, token: null, register },
    server: { isNativePlatform: options.native ?? false },
  });
};

const heading = (name: string | RegExp) => screen.findByRole("heading", { name });
const press = (name: string | RegExp) => userEvent.click(screen.getByRole("button", { name }));

/** Reach the date through the app's picker: open it, type the date, commit. */
const enterBirthdate = async (date: string) => {
  await userEvent.click(await screen.findByLabelText("Date of birth"));
  await userEvent.type(await screen.findByLabelText("Type or pick a date"), `${date}{Enter}`);
  await userEvent.keyboard("{Escape}");
};

/** Continue opens once the handle has been checked. */
const continueEnabled = () =>
  waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());

/** The handle is the one thing the You step needs typed. */
const chooseHandle = async () => {
  await heading("About you");
  await userEvent.type(screen.getByLabelText("Username"), "newbie");
};

const createAccount = async () => {
  await heading("Create your account");
  await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
  await userEvent.type(screen.getByLabelText(/^password/i), "a-long-enough-password");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "a-long-enough-password");
  await press("Sign up");
  await heading("Check your email");
};

beforeEach(async () => {
  Object.assign(deployment, { registrationOpen: true, directory: true, billing: false });
  stubDeployment();
  await clearStart();
  suggestionSeeds.length = 0;
  // Made, but its address is unconfirmed: the flow stops at "check your email".
  register.mockReset().mockResolvedValue(buildUser({ status: "active", email_verified: false }));
});

describe("which paths are offered", () => {
  it("offers only the invite where sign-up without one is closed", async () => {
    deployment.registrationOpen = false;
    renderStart();

    expect(await heading("Invite required")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Invite code or link")).toBeInTheDocument();
  });

  it.each([
    [true, true],
    [false, false],
  ])("offers joining only where the directory runs (directory %s)", async (directory, shown) => {
    deployment.directory = directory;
    renderStart();

    await heading("What brings you here?");
    expect(Boolean(screen.queryByRole("radio", { name: /join a community/i }))).toBe(shown);
    expect(screen.getByRole("radio", { name: /just for me/i })).toBeChecked();
  });

  it("asks the native app for no plan, which it may not sell", async () => {
    deployment.billing = true;
    const open = vi.spyOn(window, "open");
    renderStart({ native: true });

    await heading("What brings you here?");
    await userEvent.click(screen.getByRole("radio", { name: /for a group/i }));
    await press("Continue");
    await chooseHandle();
    await continueEnabled();
    await press("Continue");
    await heading("Your community");
    await press("Continue");
    await createAccount();

    expect(register).toHaveBeenCalledWith(
      expect.objectContaining({ community: { name: "newbie's community" } })
    );
    expect(screen.queryByText(/Brass|\$7|Choose a plan/)).toBeNull();
    expect(open).not.toHaveBeenCalled();
  });
});

it("links the privacy policy beside the birthdate where the deployment publishes one", async () => {
  deployment.billing = true;
  renderStart();

  await heading("What brings you here?");
  await press("Continue");
  await heading("About you");

  expect(screen.getByText(/We don't sell your data\./)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
    "href",
    "/legal/privacy"
  );
});

describe("what the account is made with", () => {
  it("takes a suggested handle and sends the space named after it, with no name", async () => {
    renderStart();

    await heading("What brings you here?");
    await press("Continue");
    await heading("About you");
    // Nothing typed yet, so there is no account to make.
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(await screen.findByRole("button", { name: "yonderfan" }));
    expect(screen.getByLabelText("Username")).toHaveValue("yonderfan");
    // The number it will get, shown and locked beside the name.
    expect(await screen.findByText("#0042")).toBeInTheDocument();
    await continueEnabled();
    // A pick is not typing, so it does not seed the next round of suggestions.
    expect(suggestionSeeds).not.toContain("yonderfan");
    await press("Continue");
    await heading("Your space");
    await press("Continue");
    await createAccount();

    const sent = register.mock.calls[0][0];
    expect(sent).toMatchObject({
      email: "new@example.com",
      username: "yonderfan",
      username_offer: "signed-42",
      community: { name: "yonderfan's space" },
    });
  });

  it("holds a handle the server refuses on the step where it can be changed", async () => {
    server.use(
      http.get("/api/v1/auth/username-available", () =>
        HttpResponse.json({ available: false, reason: "USERNAME_RESERVED" })
      )
    );
    renderStart();

    await heading("What brings you here?");
    await press("Continue");
    await heading("About you");
    await userEvent.type(screen.getByLabelText("Username"), "admin");

    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled());
  });

  it("sends the birthdate and no community for joining, and keeps every interest", async () => {
    renderStart();

    await heading("What brings you here?");
    await userEvent.click(screen.getByRole("radio", { name: /join a community/i }));
    await press("Continue");
    await heading("What are you into?");
    // Where they are is asked too, and is theirs to leave blank.
    expect(screen.getByRole("group", { name: "Where are you? (optional)" })).toBeInTheDocument();
    await press("Tabletop RPG");
    await press("Gaming");
    await press("Continue");
    await chooseHandle();
    // Joining a listed community needs the answer, so there is no skipping it.
    expect(screen.queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await enterBirthdate("1990-05-04");
    await continueEnabled();
    await press("Continue");
    await createAccount();

    const sent = register.mock.calls[0][0];
    expect(sent).toMatchObject({ birthdate: "1990-05-04" });
    expect(sent.community).toBeUndefined();
    expect(sent.inviteCode).toBeUndefined();
    // Waiting for the first sign-in, which opens the directory on every pick.
    expect(readPendingStart("new@example.com")?.categories).toEqual(["gaming", "ttrpg"]);
    expect(readPendingStart("new@example.com")?.near.country).toBe("");
  });
});

it("sends /register to /start with its invite", async () => {
  const router = createRouter({
    routeTree,
    context: buildRouterContext(),
    history: createMemoryHistory({ initialEntries: ["/register?invite_code=abc123"] }),
  });
  await router.load();

  await waitFor(() => expect(router.state.location.pathname).toBe("/start"));
  expect(router.state.location.search).toEqual({ invite_code: "abc123" });
});

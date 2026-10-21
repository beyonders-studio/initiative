/**
 * The sign-in card: the password form, and the two steps beyond it — the
 * second factor, and the passkey.
 *
 * For the password form, what is pinned is what a password manager does to it:
 * filling the fields without the change reaching the page's state, and
 * submitting several times in one moment. Each wrong answer counts toward
 * locking the account, so the form sends one sign-in, of what the fields hold.
 *
 * For the factor, what is worth pinning is what the card does with a challenge
 * — that it stops asking for a password, that a refused code leaves the person
 * able to try again, and that starting over really does. Which request each
 * kind of code becomes is the hook's, and is pinned in
 * `src/hooks/useAuth.test.tsx`.
 *
 * For the passkey it is the joins: that the button is there only where both
 * the deployment and the browser offer one, that a press stands down whatever
 * prompt was already waiting, and that the two ways the ceremony can end —
 * a session for this browser, a way back to an app — each go where they go.
 * The prompt that waits in the browser's own autofill is started by the page
 * rather than the person, so what it does when it ends empty-handed — keep to
 * itself, and take one fresh turn when its challenge has lapsed — is pinned
 * here too.
 */
import { Browser } from "@capacitor/browser";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  completeSecondFactor: vi.fn(),
  applyPasskeySignIn: vi.fn(),
  completeOidcLogin: vi.fn(),
  redeemNativeSignIn: vi.fn(),
  get: vi.fn(),
  signInWithPasskey: vi.fn(),
  cancelPendingPasskeyPrompt: vi.fn(),
  browserOffersPasskeys: vi.fn(() => true),
  appRunsPasskeys: vi.fn(() => false),
  browserOffersPasskeyAutofill: vi.fn(() => Promise.resolve(false)),
  /** The real mapping, so the card is asserted on the copy it would show. */
  describePasskeyPromptError: vi.fn((error: unknown) => {
    const name = error instanceof Error ? error.name : "";
    if (name === "AbortError") return null;
    return name === "NotAllowedError" ? "auth:login.passkeyCancelled" : "auth:login.passkeyFailed";
  }),
  /** Read on every render, so a test can say what the deployment offers. */
  config: { passwordLoginEnabled: true, passkeyLoginEnabled: true },
  server: { isNativePlatform: false } as {
    isNativePlatform: boolean;
    isServerConfigured?: boolean;
  },
}));

// The provider list. The bootstrap probe is the default handler's: a server
// that already has users, so the page shows the sign-in card.
vi.mock("@/api/generated/auth/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/auth/auth")>()),
  listLoginProviders: () => mocks.get("/auth/providers").then((r: { data: unknown }) => r.data),
  redeemNativeSignIn: (body: unknown) => mocks.redeemNativeSignIn(body),
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({
    login: mocks.login,
    completeSecondFactor: mocks.completeSecondFactor,
    applyPasskeySignIn: mocks.applyPasskeySignIn,
    completeOidcLogin: mocks.completeOidcLogin,
  }),
}));

vi.mock("@/hooks/useServer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useServer")>()),
  useServer: () => ({
    isNativePlatform: mocks.server.isNativePlatform,
    isServerConfigured: mocks.server.isServerConfigured ?? true,
    getServerHostname: () => "example.com",
    getServerOrigin: () => "https://example.com",
    clearServerUrl: vi.fn(),
    serverUrl: "https://example.com",
  }),
}));

vi.mock("@/hooks/useAppConfig", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAppConfig")>()),
  useAppConfig: () => mocks.config,
}));

// Every conversation with the browser's credential API goes through this one
// module, so the whole ceremony is one mock.
vi.mock("@/lib/passkeys", () => ({
  appRunsPasskeys: () => mocks.appRunsPasskeys(),
  PasskeyNeedsBrowserError: class PasskeyNeedsBrowserError extends Error {},
  browserOffersPasskeys: () => mocks.browserOffersPasskeys(),
  browserOffersPasskeyAutofill: () => mocks.browserOffersPasskeyAutofill(),
  signInWithPasskey: (options?: unknown) => mocks.signInWithPasskey(options),
  cancelPendingPasskeyPrompt: () => mocks.cancelPendingPasskeyPrompt(),
  describePasskeyPromptError: (error: unknown) => mocks.describePasskeyPromptError(error),
}));

import { SecondFactorRequiredError } from "@/hooks/useAuth";
import { takePendingSignIn } from "@/lib/nativeSignIn";
import { PasskeyNeedsBrowserError } from "@/lib/passkeys";

import { LoginPage } from "./LoginPage";

const signIn = async (user: ReturnType<typeof userEvent.setup>) => {
  // The router resolves the route before anything renders.
  await user.type(await screen.findByLabelText(/email/i), "someone@example.com");
  await user.type(screen.getByLabelText(/password/i), "a-password");
  // Anchored: the passkey button beside it also starts with "Sign in with".
  await user.click(screen.getByRole("button", { name: /^sign in$/i }));
};

const renderLogin = (search?: Record<string, unknown>) =>
  renderPage(LoginPage, { initialRoute: "/login", routerSearch: search });

const corp = {
  id: 1,
  slug: "corp",
  display_name: "Corp",
  kind: "oidc",
  login_url: "/api/v1/auth/corp/login",
  icon: null,
  button_style: null,
};

/** The page leaves for the provider by assigning the address, which jsdom will
 *  not follow. Stand a writable one in its place so the departure can be read
 *  back — the real `origin` and all, since that is what a path is judged
 *  against. */
const watchWhereItLeavesFor = () => {
  const original = window.location;
  const stand = { ...original, origin: original.origin, href: original.href };
  Object.defineProperty(window, "location", { value: stand, configurable: true, writable: true });
  return {
    left: () => stand.href,
    restore: () =>
      Object.defineProperty(window, "location", {
        value: original,
        configurable: true,
        writable: true,
      }),
  };
};

const offering = (providers: unknown[]) => {
  mocks.get.mockResolvedValue({ data: { providers } });
};

const passkeyButton = () => screen.findByRole("button", { name: /sign in with a passkey/i });

/** The server's answer when the challenge a prompt was started on has since
 *  lapsed — the browser's own prompt stands as long as the tab does. */
const lapsedChallenge = (): AxiosError => {
  const error = new AxiosError("request failed", "ERR_BAD_REQUEST");
  error.response = {
    status: 400,
    statusText: "",
    data: { detail: "PASSKEY_SIGN_IN_INVALID" },
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
};

/** A prompt the person put down, or that timed out on its own. */
const refusedPrompt = (): Error => {
  const error = new Error("The operation either timed out or was not allowed.");
  error.name = "NotAllowedError";
  return error;
};

/** A prompt the page itself stood down — for the button's, or with the page. */
const abortedPrompt = (): Error => {
  const error = new Error("This operation was aborted.");
  error.name = "AbortError";
  return error;
};

const resetLoginMocks = () => {
  mocks.login.mockReset();
  mocks.completeSecondFactor.mockReset().mockResolvedValue(undefined);
  mocks.applyPasskeySignIn.mockReset().mockResolvedValue(undefined);
  mocks.completeOidcLogin.mockReset().mockResolvedValue(undefined);
  mocks.redeemNativeSignIn.mockReset();
  mocks.appRunsPasskeys.mockReset().mockReturnValue(false);
  mocks.signInWithPasskey.mockReset();
  mocks.cancelPendingPasskeyPrompt.mockReset();
  mocks.browserOffersPasskeys.mockReset().mockReturnValue(true);
  mocks.browserOffersPasskeyAutofill.mockReset().mockResolvedValue(false);
  mocks.config = { passwordLoginEnabled: true, passkeyLoginEnabled: true };
  mocks.server = { isNativePlatform: false };
  vi.mocked(Browser.open).mockClear();
  mocks.get.mockReset().mockResolvedValue({ data: { providers: [] } });
};

/** Put a value in a field the way an autofill can: in the field, with no
 *  event the page hears. */
const fillWithoutTelling = (field: HTMLElement, value: string) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(field, value);
};

describe("LoginPage server", () => {
  beforeEach(resetLoginMocks);

  it("asks the app for a server before anything else", async () => {
    mocks.server = { isNativePlatform: true, isServerConfigured: false };
    renderLogin();

    expect(await screen.findByRole("combobox", { name: /^server$/i })).toHaveTextContent(
      /self-hosted/i
    );
    expect(screen.getByRole("textbox", { name: /server address/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });
});

describe("LoginPage password", () => {
  beforeEach(resetLoginMocks);

  it("sends one sign-in however many times the form is submitted at once", async () => {
    const user = userEvent.setup();
    // Still waiting on the server while the other submits arrive.
    mocks.login.mockReturnValue(new Promise(() => {}));
    renderLogin();
    await user.type(await screen.findByLabelText(/email/i), "someone@example.com");
    await user.type(screen.getByLabelText(/password/i), "a-password");
    const form = screen.getByRole("button", { name: /^sign in$/i }).closest("form");

    for (let i = 0; i < 5; i++) fireEvent.submit(form as HTMLFormElement);

    expect(mocks.login).toHaveBeenCalledTimes(1);
  });

  it("sends what the fields hold, though the fill never reached the page", async () => {
    mocks.login.mockReturnValue(new Promise(() => {}));
    renderLogin();
    const email = await screen.findByLabelText(/email/i);
    const password = screen.getByLabelText(/password/i);

    fillWithoutTelling(email, "Someone@Example.com");
    fillWithoutTelling(password, "the-saved-password");
    fireEvent.submit(password.closest("form") as HTMLFormElement);

    expect(mocks.login).toHaveBeenCalledWith(
      expect.objectContaining({ email: "someone@example.com", password: "the-saved-password" })
    );
    // And the fields keep it once the page renders again.
    await waitFor(() => expect(password).toHaveValue("the-saved-password"));
  });
});

describe("LoginPage second factor", () => {
  beforeEach(resetLoginMocks);

  it("asks for the code once the password is accepted", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();

    await signIn(user);

    await waitFor(() => expect(screen.getByLabelText(/authentication code/i)).toBeInTheDocument());
    // And it has stopped asking for the password it already has.
    expect(screen.queryByLabelText(/^password$/i)).not.toBeInTheDocument();
  });

  it("swaps the code field for the recovery one on asking", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();
    await signIn(user);
    await screen.findByLabelText(/authentication code/i);

    await user.click(screen.getByRole("button", { name: /use a recovery code/i }));

    expect(await screen.findByLabelText(/recovery code/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/authentication code/i)).not.toBeInTheDocument();
  });

  it("lets them try again after a refused code", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    mocks.completeSecondFactor.mockRejectedValueOnce(new Error("That code isn't right."));
    renderLogin();
    await signIn(user);
    await screen.findByLabelText(/authentication code/i);

    await user.type(screen.getByLabelText(/authentication code/i), "000000");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("That code isn't right.")).toBeInTheDocument();
    // Still on the code step, with the field cleared to retype into.
    const field = screen.getByLabelText(/authentication code/i);
    expect(field).toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("sends a code filled in without the page hearing it", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();
    await signIn(user);

    fillWithoutTelling(await screen.findByLabelText(/authentication code/i), "123456");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(mocks.completeSecondFactor).toHaveBeenCalledWith(
      expect.objectContaining({ challenge: "a-challenge", code: "123456" })
    );
  });

  it("starting over puts the password back", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();
    await signIn(user);
    await screen.findByLabelText(/authentication code/i);

    await user.click(screen.getByRole("button", { name: /start over/i }));

    await waitFor(() => expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/authentication code/i)).not.toBeInTheDocument();
  });
});

/**
 * Where signing in leaves you.
 *
 * Somebody who asked for a page and was sent here to sign in should land on
 * the page they asked for — the app sends a phone to a browser for a passkey
 * and that is the whole point of the trip. Only somewhere in this app,
 * though: anything else is dropped for the front page.
 */
describe("LoginPage return path", () => {
  beforeEach(() => {
    resetLoginMocks();
    mocks.login.mockResolvedValue(undefined);
  });

  it("finishes the trip they were on", async () => {
    const user = userEvent.setup();
    const { router } = renderLogin({ next: "/profile/security" });

    await signIn(user);

    await waitFor(() => expect(router.state.location.pathname).toBe("/profile/security"));
  });

  it("keeps a destination outside this app out of it", async () => {
    const user = userEvent.setup();
    const { router } = renderLogin({ next: "//evil.test/take-me" });

    await signIn(user);

    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("carries the same trip into a provider's sign-in", async () => {
    // An account that signs in through SSO only is the case the passkey trip
    // depends on: the app hands the browser the provider, and the provider's
    // callback is what lands somewhere.
    const user = userEvent.setup();
    offering([corp]);
    const departure = watchWhereItLeavesFor();
    try {
      renderLogin({ next: "/profile/security" });

      await user.click(await screen.findByRole("button", { name: /continue with corp/i }));

      expect(departure.left()).toBe("/api/v1/auth/corp/login?next=%2Fprofile%2Fsecurity");
    } finally {
      departure.restore();
    }
  });

  it("leaves for the provider bare when the trip was not one of ours", async () => {
    const user = userEvent.setup();
    offering([corp]);
    const departure = watchWhereItLeavesFor();
    try {
      renderLogin({ next: "//evil.test/take-me" });

      await user.click(await screen.findByRole("button", { name: /continue with corp/i }));

      expect(departure.left()).toBe("/api/v1/auth/corp/login");
    } finally {
      departure.restore();
    }
  });
});

describe("LoginPage passkey", () => {
  let consoleDebug: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetLoginMocks();
    // The quiet prompt's refusals go here rather than to the card.
    consoleDebug = vi.spyOn(console, "debug").mockImplementation(() => {});
  });

  afterEach(() => consoleDebug.mockRestore());

  it("offers one where the deployment and the browser both do", async () => {
    renderLogin();

    expect(await passkeyButton()).toBeEnabled();
  });

  it("offers none where the deployment has withdrawn them", async () => {
    mocks.config = { passwordLoginEnabled: true, passkeyLoginEnabled: false };
    renderLogin();

    await screen.findByLabelText(/email/i);
    expect(screen.queryByRole("button", { name: /passkey/i })).not.toBeInTheDocument();
  });

  it("offers none where this browser cannot present one", async () => {
    mocks.browserOffersPasskeys.mockReturnValue(false);
    renderLogin();

    await screen.findByLabelText(/email/i);
    expect(screen.queryByRole("button", { name: /passkey/i })).not.toBeInTheDocument();
  });

  it("stands the waiting prompt down, signs in, and goes on", async () => {
    const user = userEvent.setup();
    const session = { access_token: "fresh-token", token_type: "bearer" };
    mocks.signInWithPasskey.mockResolvedValue(session);
    const { router } = renderLogin();

    await user.click(await passkeyButton());

    expect(mocks.cancelPendingPasskeyPrompt).toHaveBeenCalled();
    expect(mocks.signInWithPasskey).toHaveBeenCalledWith({ conditional: false });
    await waitFor(() => expect(mocks.applyPasskeySignIn).toHaveBeenCalledWith(session));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("says so when the prompt produces nothing", async () => {
    const user = userEvent.setup();
    mocks.signInWithPasskey.mockRejectedValue(refusedPrompt());
    renderLogin();

    await user.click(await passkeyButton());

    expect(await screen.findByText(/you cancelled/i)).toBeInTheDocument();
    expect(mocks.applyPasskeySignIn).not.toHaveBeenCalled();
  });

  it("waits in the browser's autofill from the moment the page opens", async () => {
    const session = { access_token: "fresh-token", token_type: "bearer" };
    mocks.browserOffersPasskeyAutofill.mockResolvedValue(true);
    mocks.signInWithPasskey.mockResolvedValue(session);
    renderLogin();

    await waitFor(() =>
      expect(mocks.signInWithPasskey).toHaveBeenCalledWith({ conditional: true })
    );
    await waitFor(() => expect(mocks.applyPasskeySignIn).toHaveBeenCalledWith(session));
  });

  it("says nothing on the card when the quiet prompt ends without one", async () => {
    // Nobody pressed anything to start it, so there is nothing to report.
    mocks.browserOffersPasskeyAutofill.mockResolvedValue(true);
    mocks.signInWithPasskey.mockRejectedValue(refusedPrompt());
    renderLogin();

    await waitFor(() =>
      expect(mocks.signInWithPasskey).toHaveBeenCalledWith({ conditional: true })
    );
    await screen.findByLabelText(/email/i);
    expect(screen.queryByText(/you cancelled/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/didn't work/i)).not.toBeInTheDocument();
  });

  it("writes nothing down for a quiet prompt it stood down itself", async () => {
    mocks.browserOffersPasskeyAutofill.mockResolvedValue(true);
    mocks.signInWithPasskey.mockRejectedValue(abortedPrompt());
    renderLogin();

    await waitFor(() =>
      expect(mocks.signInWithPasskey).toHaveBeenCalledWith({ conditional: true })
    );
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(consoleDebug).not.toHaveBeenCalledWith(
      expect.stringContaining("Passkey autofill"),
      expect.anything()
    );
  });

  it("waits in no autofill where there is no address field to wait in", async () => {
    mocks.config = { passwordLoginEnabled: false, passkeyLoginEnabled: true };
    mocks.browserOffersPasskeyAutofill.mockResolvedValue(true);
    renderLogin();

    expect(await passkeyButton()).toBeEnabled();
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(mocks.signInWithPasskey).not.toHaveBeenCalled();
  });

  it("says so where no way in is offered, rather than showing an empty card", async () => {
    mocks.config = { passwordLoginEnabled: false, passkeyLoginEnabled: false };
    renderLogin();

    expect(await screen.findByText(/offers no way to sign in/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });

  it("takes one fresh turn in autofill when the challenge it waited on has lapsed", async () => {
    mocks.browserOffersPasskeyAutofill.mockResolvedValue(true);
    mocks.signInWithPasskey.mockRejectedValue(lapsedChallenge());
    renderLogin();

    await waitFor(() => expect(mocks.signInWithPasskey).toHaveBeenCalledTimes(2));
    expect(mocks.signInWithPasskey).toHaveBeenNthCalledWith(2, { conditional: true });

    // And the second refusal ends it: one fresh turn, not a page that keeps
    // asking, and still nothing on the card.
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(mocks.signInWithPasskey).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/didn't work/i)).not.toBeInTheDocument();
  });

  it("lets the browser offer a passkey beside the saved addresses", async () => {
    renderLogin();

    expect(await screen.findByLabelText(/email/i)).toHaveAttribute(
      "autocomplete",
      "username webauthn"
    );
  });

  it("sends a phone to a browser rather than prompting in the app", async () => {
    // A passkey belongs to the deployment's domain, and the browser is what
    // decides which domain it is in.
    const user = userEvent.setup();
    mocks.server = { isNativePlatform: true };
    renderLogin();

    await user.click(await passkeyButton());
    // The click only starts the trip: the device name and the challenge's
    // digest are awaited before the browser opens.
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(1));

    // The browser is sent the challenge of a sign-in this app has written down,
    // so the code it hands back can only be redeemed here.
    const opened = new URL(vi.mocked(Browser.open).mock.calls[0][0].url);
    expect(`${opened.origin}${opened.pathname}`).toBe("https://example.com/login");
    expect(Object.fromEntries(opened.searchParams)).toMatchObject({
      passkey: "1",
      mobile: "true",
      device_name: "Test Device",
    });
    const pending = takePendingSignIn("https://example.com");
    expect(pending).not.toBeNull();
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(pending?.verifier)
    );
    expect(opened.searchParams.get("code_challenge")).toBe(
      btoa(String.fromCharCode(...new Uint8Array(digest)))
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "")
    );
    expect(mocks.signInWithPasskey).not.toHaveBeenCalled();
  });

  it("runs the ceremony in the app where the app can", async () => {
    // The server hands back a code bound to this app's challenge, as it does
    // for the relay, and the app redeems it itself.
    const user = userEvent.setup();
    mocks.server = { isNativePlatform: true };
    mocks.appRunsPasskeys.mockReturnValue(true);
    mocks.signInWithPasskey.mockResolvedValue({
      redirect_to: "initiative://oidc/callback?code=one-time",
    });
    mocks.redeemNativeSignIn.mockResolvedValue({
      access_token: "access",
      refresh_token: "refresh",
      token_type: "bearer",
    });
    renderLogin();

    await user.click(await passkeyButton());

    await waitFor(() =>
      expect(mocks.completeOidcLogin).toHaveBeenCalledWith({
        accessToken: "access",
        refreshToken: "refresh",
      })
    );
    expect(mocks.signInWithPasskey).toHaveBeenCalledWith(
      expect.objectContaining({ mobile: true, deviceName: "Test Device" })
    );
    expect(mocks.redeemNativeSignIn).toHaveBeenCalledWith(
      expect.objectContaining({ code: "one-time" })
    );
    expect(Browser.open).not.toHaveBeenCalled();
  });

  it("goes to the browser when the phone will not let the app act for the server", async () => {
    const user = userEvent.setup();
    mocks.server = { isNativePlatform: true };
    mocks.appRunsPasskeys.mockReturnValue(true);
    mocks.signInWithPasskey.mockRejectedValue(new PasskeyNeedsBrowserError());
    renderLogin();

    await user.click(await passkeyButton());

    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(1));
    expect(new URL(vi.mocked(Browser.open).mock.calls[0][0].url).pathname).toBe("/login");
    expect(mocks.describePasskeyPromptError).not.toHaveBeenCalled();
  });
});

describe("LoginPage passkey relay", () => {
  const relaySearch = {
    passkey: 1,
    mobile: true,
    device_name: "Pixel",
    code_challenge: "c".repeat(43),
  };
  const originalLocation = Object.getOwnPropertyDescriptor(window, "location");
  let assign: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    resetLoginMocks();
    assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: window.location.href, origin: window.location.origin, assign },
    });
  });

  afterEach(() => {
    if (originalLocation) Object.defineProperty(window, "location", originalLocation);
  });

  it("asks for one press and nothing else", async () => {
    renderLogin(relaySearch);

    expect(
      await screen.findByRole("button", { name: /continue with a passkey/i })
    ).toBeInTheDocument();
    // Not the sign-in card: this browser was opened for one thing.
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    // And nothing starts on its own — the prompt wants a press behind it.
    expect(mocks.signInWithPasskey).not.toHaveBeenCalled();
  });

  it("hands the app the way back", async () => {
    const user = userEvent.setup();
    mocks.signInWithPasskey.mockResolvedValue({
      token_type: "bearer",
      redirect_to: "initiative://oidc/callback?code=abc",
    });
    renderLogin(relaySearch);

    await user.click(await screen.findByRole("button", { name: /continue with a passkey/i }));

    expect(mocks.signInWithPasskey).toHaveBeenCalledWith({
      mobile: true,
      deviceName: "Pixel",
      codeChallenge: "c".repeat(43),
    });
    await waitFor(() => expect(assign).toHaveBeenCalledWith("initiative://oidc/callback?code=abc"));
    expect(await screen.findByText(/go back to the app/i)).toBeInTheDocument();
  });

  it("keeps the button when the ceremony is refused", async () => {
    const user = userEvent.setup();
    mocks.signInWithPasskey.mockRejectedValue(refusedPrompt());
    renderLogin(relaySearch);

    await user.click(await screen.findByRole("button", { name: /continue with a passkey/i }));

    expect(await screen.findByText(/you cancelled/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue with a passkey/i })).toBeEnabled();
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("LoginPage demo samples", () => {
  beforeEach(resetLoginMocks);

  const onTheDemo = () =>
    server.use(
      http.get("/api/v1/auth/bootstrap", () =>
        HttpResponse.json({ has_users: true, public_registration_enabled: true, demo: true })
      ),
      http.get("/api/v1/demo/samples", () =>
        HttpResponse.json([
          {
            display_name: "Rosie Baker",
            email: "bakery@example.com",
            password: "password",
            about: "Owns Rosie's Bakery",
          },
        ])
      )
    );

  it("lists the samples and puts one's address and password in the form", async () => {
    const user = userEvent.setup();
    mocks.login.mockReturnValue(new Promise(() => {}));
    onTheDemo();
    renderLogin();

    expect(await screen.findByText("Rosie Baker")).toBeInTheDocument();
    expect(screen.getByText("bakery@example.com · password")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /sign in as rosie baker/i }));
    expect(screen.getByLabelText(/email/i)).toHaveValue("bakery@example.com");
    expect(screen.getByLabelText(/^password/i)).toHaveValue("password");

    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(mocks.login).toHaveBeenCalledWith(
      expect.objectContaining({ email: "bakery@example.com", password: "password" })
    );
  });

  it("lists nothing where passwords are not offered", async () => {
    onTheDemo();
    mocks.config = { passwordLoginEnabled: false, passkeyLoginEnabled: true };
    try {
      renderLogin();
      expect(await screen.findByRole("button", { name: /passkey/i })).toBeInTheDocument();
      expect(screen.queryByText("Rosie Baker")).not.toBeInTheDocument();
    } finally {
      mocks.config = { passwordLoginEnabled: true, passkeyLoginEnabled: true };
    }
  });
});

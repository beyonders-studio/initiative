/**
 * Signing in with a passkey, in one place.
 *
 * Every conversation with the browser's credential API happens here: the page
 * asks for a sign-in and gets back what the server said, so what it has to
 * reason about is its own card rather than a ceremony. Two shapes of prompt go
 * through the same call — the modal one a button opens, and the quiet one that
 * waits inside the browser's own autofill — because the only thing that
 * separates them is a flag the credential API reads.
 *
 * The Android app and the Windows desktop app run every ceremony themselves,
 * through their Passkeys plug-in: Android through its credential manager when
 * the server names the app in its asset links, Windows through its own passkey
 * dialog. Where an app cannot, sign-in, adding a passkey and step-up go to the
 * system browser.
 */
import { Capacitor } from "@capacitor/core";
import {
  type CreatePasskeyOptions,
  type GetPasskeyOptions,
  Passkeys,
} from "@capawesome/capacitor-passkeys";
import {
  browserSupportsWebAuthn,
  browserSupportsWebAuthnAutofill,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
  startAuthentication,
  startRegistration,
  WebAuthnAbortService,
  WebAuthnError,
} from "@simplewebauthn/browser";

import { beginBreakGlassPasskey } from "@/api/generated/access-grants/access-grants";
import {
  beginPasskeySignIn,
  beginPasskeySignUp,
  beginPasskeyStepUp,
  finishPasskeySignIn,
  finishPasskeySignUp,
  finishPasskeyStepUp,
} from "@/api/generated/auth/auth";
import type {
  PasskeySignInFinishCredential,
  PasskeySignInResult,
  PasskeySignUpFinishCredential,
  PasskeySignUpResult,
  PasskeySignUpStart,
  PasskeyStepUpFinishCredential,
  Token,
} from "@/api/generated/initiativeAPI.schemas";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { getItem, setItem } from "@/lib/storage";

/** Set when the app could not act for a server, which then goes straight to
 *  the browser until it lapses: long enough not to fail first on every press,
 *  short enough that a server put right is tried again. */
const APP_REFUSED_KEY = "initiative-passkey-app-refused";
const APP_REFUSED_TTL_MS = 24 * 60 * 60 * 1000;

/** The app could not run this ceremony for this server; the browser can. */
export class PasskeyNeedsBrowserError extends Error {
  constructor() {
    super("PASSKEY_NEEDS_BROWSER");
    this.name = "PasskeyNeedsBrowserError";
  }
}

/** The apps whose Passkeys plug-in runs ceremonies. An iOS app can act only
 *  for domains its build names, and the desktop app registers the plug-in on
 *  Windows alone. */
const PLUGIN_PLATFORMS = new Set(["android", "electron"]);

const appHasPlugin = (): boolean =>
  PLUGIN_PLATFORMS.has(Capacitor.getPlatform()) && Capacitor.isPluginAvailable("Passkeys");

/**
 * Whether this app runs a passkey ceremony itself, rather than in the system
 * browser. An older app without the plug-in, and a server the app could not
 * act for lately, use the browser.
 */
export const appRunsPasskeys = (): boolean => {
  if (!appHasPlugin()) return false;
  const refusedAt = refusals()[getStoredServerUrl() ?? ""] ?? 0;
  return Date.now() - refusedAt >= APP_REFUSED_TTL_MS;
};

/** When the app last could not act for each server, by its address. */
const refusals = (): Record<string, number> => {
  try {
    return JSON.parse(getItem(APP_REFUSED_KEY) ?? "{}") as Record<string, number>;
  } catch {
    return {};
  }
};

/** Refusals that mean this server's ceremonies belong in the browser. The
 *  Android plug-in reports its own codes; the desktop plug-in passes on the
 *  browser's names for how a prompt ended. */
const NEEDS_BROWSER = new Set([
  "DOMAIN_NOT_ASSOCIATED",
  "NOT_SUPPORTED",
  "SecurityError",
  "NotSupportedError",
]);

/** The browser's names for the Android plug-in's codes, so one message table
 *  reads every refusal. A browser name passes through as it is. */
const BROWSER_NAMES: Record<string, string> = {
  CANCELED: "NotAllowedError",
  NO_CREDENTIAL: "NotAllowedError",
};

/** Ask the app's plug-in, giving its refusals the browser's names. */
const viaApp = async <T>(call: () => Promise<T>): Promise<T> => {
  try {
    return await call();
  } catch (err) {
    const code = (err as { code?: string }).code ?? "";
    if (NEEDS_BROWSER.has(code)) {
      const now = Date.now();
      const fresh = Object.entries(refusals()).filter(([, at]) => now - at < APP_REFUSED_TTL_MS);
      fresh.push([getStoredServerUrl() ?? "", now]);
      void setItem(APP_REFUSED_KEY, JSON.stringify(Object.fromEntries(fresh)));
      throw new PasskeyNeedsBrowserError();
    }
    const error = new Error(code || "PASSKEY_FAILED");
    if (code) error.name = BROWSER_NAMES[code] ?? code;
    throw error;
  }
};

/** What the plug-in is handed: the server's options, and on the desktop the
 *  server's own address, which its plug-in opens to run the ceremony at. A
 *  phone's credential manager takes the options alone. */
const forPlugin = (options: unknown) => {
  if (Capacitor.getPlatform() !== "electron") return options;
  const server = getStoredServerUrl();
  return { ...(options as object), origin: server ? new URL(server).origin : "" };
};

/** Present a credential, from the app or the browser. The server renders the
 *  options the way both want them; the generated schema carries them as open
 *  objects. */
const presentCredential = (options: unknown, conditional = false) =>
  appHasPlugin()
    ? viaApp(() => Passkeys.getPasskey(forPlugin(options) as GetPasskeyOptions))
    : startAuthentication({
        optionsJSON: options as PublicKeyCredentialRequestOptionsJSON,
        useBrowserAutofill: conditional,
      });

/** Make a credential, from the app or the browser. */
export const createCredential = (options: unknown) =>
  appHasPlugin()
    ? viaApp(() => Passkeys.createPasskey(forPlugin(options) as CreatePasskeyOptions))
    : startRegistration({ optionsJSON: options as PublicKeyCredentialCreationOptionsJSON });

/** Whether a ceremony can run here at all: through the app's plug-in, or in a
 *  browser on the server's own page. An app's page is never that page, so an
 *  app without the plug-in has no ceremony to run. */
export const passkeysRunHere = (): boolean =>
  appRunsPasskeys() || (!Capacitor.isNativePlatform() && browserSupportsWebAuthn());

/** Whether a browser on this device may hold passkeys the app can't reach. A
 *  computer's browsers keep their own, in a password manager or an extension;
 *  a phone's browser uses the same credential manager the app does. */
export const browserMayHoldOtherPasskeys = (): boolean => Capacitor.getPlatform() === "electron";

/** Whether this browser can offer one from its own autofill, beside the saved
 *  passwords. Asked before the quiet prompt is started, so a browser without it
 *  is never sent a ceremony it would drop. */
export const browserOffersPasskeyAutofill = (): Promise<boolean> =>
  browserSupportsWebAuthnAutofill();

export interface PasskeySignInOptions {
  /** Wait inside the browser's autofill rather than opening a prompt. */
  conditional?: boolean;
  /** The ceremony belongs to an app: the answer is a way back to it rather
   *  than a session for this browser. */
  mobile?: boolean;
  /** What to call the device the app is running on, for the sign-in record. */
  deviceName?: string;
  /** The app's challenge, which the code handed back to it is bound to. */
  codeChallenge?: string;
}

/**
 * Run a sign-in ceremony end to end.
 *
 * Nobody is named at the start: the authenticator offers what it holds for
 * this site, and the assertion that comes back says which credential answered.
 */
export const signInWithPasskey = async ({
  conditional = false,
  mobile = false,
  deviceName,
  codeChallenge,
}: PasskeySignInOptions = {}): Promise<PasskeySignInResult> => {
  // Nothing to say at the start: the options are the same whoever asked and
  // whatever they are asking for. Where the answer goes — a session for this
  // browser, or a way back to the app that sent it — is settled at the finish.
  const begun = await beginPasskeySignIn({});
  const credential = await presentCredential(begun.options, conditional);
  return finishPasskeySignIn({
    credential: credential as unknown as PasskeySignInFinishCredential,
    mobile,
    device_name: deviceName ?? "",
    code_challenge: codeChallenge ?? "",
  });
};

/**
 * Present a passkey against the session already open.
 *
 * The sign-in above names nobody, because nobody is signed in yet. This one is
 * for a community that asks a member already here for a passkey: the account
 * is known, so the server offers that account's own credentials and answers
 * with a session carrying what was presented — the same answer the
 * authenticator-code step-up gives, applied the same way.
 */
export const stepUpWithPasskey = async (): Promise<Token> => {
  const begun = await beginPasskeyStepUp();
  const credential = await presentCredential(begun.options);
  return finishPasskeyStepUp({
    credential: credential as unknown as PasskeyStepUpFinishCredential,
  });
};

/**
 * Make an account whose way in is a key rather than a password.
 *
 * Two calls, like every ceremony: the first asks the server whether this
 * registration may happen at all — an address already taken, a missing invite,
 * a captcha — so the refusal comes before the authenticator is asked for
 * anything, and the second makes the account and signs it in. The details go
 * out again with the answer; nothing about the account exists in between.
 */
export const signUpWithPasskey = async (
  details: PasskeySignUpStart,
  inviteCode?: string
): Promise<PasskeySignUpResult> => {
  const params = inviteCode ? { invite_code: inviteCode } : undefined;
  const begun = await beginPasskeySignUp(details, params);
  const credential = await createCredential(begun.options);
  return finishPasskeySignUp(
    { ...details, credential: credential as unknown as PasskeySignUpFinishCredential },
    params
  );
};

/**
 * Present a passkey against a break-glass request.
 *
 * Unlike the step-up above, nothing is added to the session: the challenge is
 * issued for the request that will spend it, so what the key proves belongs to
 * the grant being issued rather than to the browser holding it. The assertion
 * goes back in the break-glass body, beside the reason and the community.
 */
export const assertForBreakGlass = async (): Promise<Record<string, unknown>> => {
  const begun = await beginBreakGlassPasskey();
  const credential = await presentCredential(begun.options);
  return credential as unknown as Record<string, unknown>;
};

/** Put down whatever prompt is currently waiting. Only one ceremony runs at a
 *  time, so the quiet one has to go before a button's can start. */
export const cancelPendingPasskeyPrompt = (): void => WebAuthnAbortService.cancelCeremony();

/** The line to show for a prompt that ended without a credential, or null when
 *  there is nothing to say. */
export type PasskeyPromptMessageKey =
  | "auth:login.passkeyCancelled"
  | "auth:login.passkeyFailed"
  | "auth:login.passkeyNotInApp";

/**
 * Which line a prompt that produced nothing deserves.
 *
 * `startAuthentication` raises a {@link WebAuthnError} named after the
 * browser's own exception, and anything else landing in the same catch keeps
 * whatever name it had. A ceremony we put down ourselves — the quiet one,
 * stood aside for a button or gone with the page — is not a failure anybody
 * needs telling about, so it gets no line at all. One the app's plug-in could
 * not run says so; sign-in and adding a passkey open the browser instead and
 * never ask.
 */
export const describePasskeyPromptError = (error: unknown): PasskeyPromptMessageKey | null => {
  const name = error instanceof WebAuthnError || error instanceof Error ? error.name : "";
  if (name === "AbortError") return null;
  if (error instanceof PasskeyNeedsBrowserError) return "auth:login.passkeyNotInApp";
  if (name === "NotAllowedError") return "auth:login.passkeyCancelled";
  return "auth:login.passkeyFailed";
};

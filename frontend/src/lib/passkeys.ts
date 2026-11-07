/**
 * Passkeys, in one place.
 *
 * Every conversation with a credential API happens here: a page asks for a
 * sign-in, an account, a step-up or a key for a request, and gets back what
 * the server said. Two shapes of sign-in prompt go through the same call — the
 * modal one a button opens, and the quiet one that waits inside the browser's
 * own autofill — because the only thing that separates them is a flag the
 * credential API reads.
 *
 * The page begins and finishes every ceremony itself; only the prompt moves.
 * A browser runs it on the page. The Android and Windows apps run it through
 * their Passkeys plug-in: Android through its credential manager when the
 * server names the app in its asset links, Windows through its own passkey
 * dialog. Any other app, and those two where the plug-in can't act for a
 * server, runs it in the system browser on the server's own page, which hands
 * the answer back through {@link PROMPT_CALLBACK}.
 */
import { Browser } from "@capacitor/browser";
import { Capacitor, type PluginListenerHandle } from "@capacitor/core";
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
  PasskeySignUpFinishCredential,
  PasskeySignUpResult,
  PasskeySignUpStart,
  PasskeyStepUpFinishCredential,
  Token,
} from "@/api/generated/initiativeAPI.schemas";
import { pkcePair } from "@/lib/nativeSignIn";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { getItem, removeItem, setItem } from "@/lib/storage";

/** Set when the app could not act for a server, which then goes straight to
 *  the browser until it lapses: long enough not to fail first on every press,
 *  short enough that a server put right is tried again. */
const APP_REFUSED_KEY = "initiative-passkey-app-refused";
const APP_REFUSED_TTL_MS = 24 * 60 * 60 * 1000;

/** What a prompt is asked for: a key the person holds, or a new one. */
export type PromptKind = "get" | "create";

/** The page an app sends the system browser to, to run a prompt for it, with
 *  the options in the fragment. */
export const PROMPT_PATH = "/login?passkey=1";

/** Where that page hands the answer back to the app. */
export const PROMPT_CALLBACK = "initiative://passkey/callback";

/** How long the app waits on the browser: time to reach its button and answer
 *  the prompt, which ends on its own after a minute. */
const BROWSER_WAIT_MS = 2 * 60 * 1000;

/** The apps whose Passkeys plug-in runs prompts. An iOS app can act only for
 *  domains its build names, and the desktop app registers the plug-in on
 *  Windows alone. */
const PLUGIN_PLATFORMS = new Set(["android", "electron"]);

/**
 * Whether this app runs a passkey prompt itself, rather than in the system
 * browser. An app without the plug-in, and a server the app could not act for
 * lately, use the browser.
 */
export const appRunsPasskeys = (): boolean => {
  if (!PLUGIN_PLATFORMS.has(Capacitor.getPlatform()) || !Capacitor.isPluginAvailable("Passkeys")) {
    return false;
  }
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

/** The address of the server the app is on, which every prompt is for. */
const serverOrigin = (): string => {
  const server = getStoredServerUrl();
  return server ? new URL(server).origin : "";
};

/** Refusals that mean this server's prompts belong in the browser. The
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

/** An error under the browser's name for how a prompt ended. */
const promptEnded = (name: string): Error => {
  const error = new Error(name);
  error.name = name;
  return error;
};

/** The plug-in could not act for this server; the browser can. */
class NeedsBrowser extends Error {}

/** Ask the app's plug-in, giving its refusals the browser's names. The
 *  desktop plug-in is told the server's address, which it runs the prompt at;
 *  a phone's credential manager takes the options alone. */
const viaApp = async (kind: PromptKind, options: unknown): Promise<unknown> => {
  const asked =
    Capacitor.getPlatform() === "electron"
      ? { ...(options as object), origin: serverOrigin() }
      : options;
  try {
    return kind === "get"
      ? await Passkeys.getPasskey(asked as GetPasskeyOptions)
      : await Passkeys.createPasskey(asked as CreatePasskeyOptions);
  } catch (err) {
    const code = (err as { code?: string }).code ?? "";
    if (NEEDS_BROWSER.has(code)) {
      const now = Date.now();
      const fresh = Object.entries(refusals()).filter(([, at]) => now - at < APP_REFUSED_TTL_MS);
      fresh.push([getStoredServerUrl() ?? "", now]);
      void setItem(APP_REFUSED_KEY, JSON.stringify(Object.fromEntries(fresh)));
      throw new NeedsBrowser();
    }
    throw promptEnded(code ? (BROWSER_NAMES[code] ?? code) : "UnknownError");
  }
};

/** What finishes a sign-in: the verifier its begin was bound to, and the name
 *  the session is given. */
interface SignInToFinish {
  verifier: string;
  deviceName: string;
}

/** A sign-in whose prompt is in the browser, with the prompt's id. Kept while
 *  the browser is in front, because the phone can close the app meanwhile and
 *  the answer then starts it afresh. */
const SIGN_IN_IN_BROWSER_KEY = "initiative-passkey-sign-in";

/** The browser prompt waiting for its answer, if one is, by the id its page
 *  hands back with the answer. */
let waiting: { prompt: string; settle: (answer: URL | Error) => void } | null = null;

/**
 * Run a prompt in the system browser, on the server's own page, and wait for
 * the answer it hands back. A newer prompt puts an older one down, and one
 * nobody answers ends the way a browser's own prompt does. `signIn` is kept
 * for a launch the answer starts afresh.
 */
const viaBrowser = async (
  kind: PromptKind,
  options: unknown,
  signIn?: SignInToFinish
): Promise<unknown> => {
  const origin = serverOrigin();
  if (!origin) throw promptEnded("NotSupportedError");
  waiting?.settle(promptEnded("AbortError"));
  const prompt = crypto.randomUUID();

  const answered = new Promise<URL>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed: Promise<PluginListenerHandle> | undefined;
    const settle = (answer: URL | Error) => {
      if (waiting?.settle !== settle) return;
      waiting = null;
      void removeItem(SIGN_IN_IN_BROWSER_KEY);
      clearTimeout(timer);
      void closed?.then((handle) => handle.remove());
      if (answer instanceof Error) reject(answer);
      else resolve(answer);
    };
    waiting = { prompt, settle };
    timer = setTimeout(() => settle(promptEnded("NotAllowedError")), BROWSER_WAIT_MS);
    // A phone's in-app browser closed before an answer ends the prompt.
    closed = Browser.addListener("browserFinished", () => settle(promptEnded("NotAllowedError")));
  });

  if (signIn) await setItem(SIGN_IN_IN_BROWSER_KEY, JSON.stringify({ ...signIn, prompt }));
  const fragment = new URLSearchParams({ [kind]: JSON.stringify(options), prompt });
  try {
    await Browser.open({ url: `${origin}${PROMPT_PATH}#${fragment}` });
  } catch {
    waiting?.settle(promptEnded("NotSupportedError"));
  }
  const answer = await answered;
  const credential = answer.searchParams.get("credential");
  if (!credential) throw promptEnded(answer.searchParams.get("error") || "NotAllowedError");
  return JSON.parse(credential) as unknown;
};

/** Finish a sign-in with the credential its prompt produced. */
const finishSignIn = (credential: unknown, { verifier, deviceName }: SignInToFinish) =>
  finishPasskeySignIn({
    credential: credential as PasskeySignInFinishCredential,
    device_name: deviceName,
    code_verifier: verifier,
  });

/**
 * Take a link the app was opened with, when it is a browser prompt's answer.
 *
 * The answer goes to the prompt waiting for it, and one from any other prompt
 * is dropped. Where nothing is waiting, the answer started the app afresh: a
 * sign-in it answers is finished here, and its session is what this resolves
 * to. Null for anything else.
 */
export const takeBrowserAnswer = async (url: URL): Promise<Token | null> => {
  if (url.protocol !== "initiative:" || url.host !== "passkey" || url.pathname !== "/callback") {
    return null;
  }
  void Browser.close().catch(() => undefined);
  const prompt = url.searchParams.get("prompt");
  if (waiting) {
    if (waiting.prompt === prompt) waiting.settle(url);
    return null;
  }
  const kept = getItem(SIGN_IN_IN_BROWSER_KEY);
  void removeItem(SIGN_IN_IN_BROWSER_KEY);
  const credential = url.searchParams.get("credential");
  if (!kept || !credential) return null;
  const signIn = JSON.parse(kept) as SignInToFinish & { prompt: string };
  return signIn.prompt === prompt ? finishSignIn(JSON.parse(credential), signIn) : null;
};

/** Run a prompt wherever it can run here. `inBrowser` sends an app's prompt to
 *  the browser even where its plug-in could run it; `signIn` is the sign-in
 *  the prompt is for, if it is for one. */
export const runPrompt = async (
  kind: PromptKind,
  options: unknown,
  {
    conditional = false,
    inBrowser = false,
    signIn,
  }: { conditional?: boolean; inBrowser?: boolean; signIn?: SignInToFinish } = {}
): Promise<unknown> => {
  if (!inBrowser && appRunsPasskeys()) {
    try {
      return await viaApp(kind, options);
    } catch (err) {
      if (!(err instanceof NeedsBrowser)) throw err;
    }
  }
  if (Capacitor.isNativePlatform()) return viaBrowser(kind, options, signIn);
  return kind === "get"
    ? startAuthentication({
        optionsJSON: options as PublicKeyCredentialRequestOptionsJSON,
        useBrowserAutofill: conditional,
      })
    : startRegistration({ optionsJSON: options as PublicKeyCredentialCreationOptionsJSON });
};

/** Make a credential for the account signed in. */
export const createCredential = (options: unknown) => runPrompt("create", options);

/** Whether a prompt can run here at all: every app has the browser, and a
 *  browser needs the credential API. */
export const passkeysRunHere = (): boolean =>
  Capacitor.isNativePlatform() || browserSupportsWebAuthn();

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
  /** Run an app's prompt in the browser, for passkeys kept there. */
  inBrowser?: boolean;
  /** What to call the device the app is running on, for the sign-in record. */
  deviceName?: string;
}

/**
 * Run a sign-in ceremony end to end.
 *
 * Nobody is named at the start: the authenticator offers what it holds for
 * this site, and the assertion that comes back says which credential answered.
 * The begin carries a PKCE challenge and the finish its verifier.
 */
export const signInWithPasskey = async ({
  conditional = false,
  inBrowser = false,
  deviceName,
}: PasskeySignInOptions = {}): Promise<Token> => {
  const pair = await pkcePair();
  const begun = await beginPasskeySignIn({ code_challenge: pair.challenge });
  const signIn = { verifier: pair.verifier, deviceName: deviceName ?? "" };
  const credential = await runPrompt("get", begun.options, { conditional, inBrowser, signIn });
  return finishSignIn(credential, signIn);
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
  const credential = await runPrompt("get", begun.options);
  return finishPasskeyStepUp({ credential: credential as PasskeyStepUpFinishCredential });
};

/**
 * Make an account whose way in is a key rather than a password.
 *
 * Two calls, like every ceremony: the first asks the server whether this
 * registration may happen at all — an address already taken, a missing invite,
 * a captcha — so the refusal comes before the authenticator is asked for
 * anything, and the second makes the account and signs it in. The details go
 * out again with the answer; nothing about the account exists in between. The
 * two calls carry a PKCE pair, as a sign-in's do.
 */
export const signUpWithPasskey = async (
  details: PasskeySignUpStart,
  inviteCode?: string
): Promise<PasskeySignUpResult> => {
  const params = inviteCode ? { invite_code: inviteCode } : undefined;
  const pair = await pkcePair();
  const begun = await beginPasskeySignUp({ ...details, code_challenge: pair.challenge }, params);
  const credential = await runPrompt("create", begun.options);
  return finishPasskeySignUp(
    {
      ...details,
      credential: credential as PasskeySignUpFinishCredential,
      code_verifier: pair.verifier,
    },
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
  return (await runPrompt("get", begun.options)) as Record<string, unknown>;
};

/** Put down whatever prompt is currently waiting. Only one ceremony runs at a
 *  time, so the quiet one has to go before a button's can start. */
export const cancelPendingPasskeyPrompt = (): void => WebAuthnAbortService.cancelCeremony();

/** The line to show for a prompt that ended without a credential, or null when
 *  there is nothing to say. */
export type PasskeyPromptMessageKey = "auth:login.passkeyCancelled" | "auth:login.passkeyFailed";

/**
 * Which line a prompt that produced nothing deserves.
 *
 * `startAuthentication` raises a {@link WebAuthnError} named after the
 * browser's own exception, and anything else landing in the same catch keeps
 * whatever name it had. A ceremony we put down ourselves — the quiet one,
 * stood aside for a button or gone with the page — is not a failure anybody
 * needs telling about, so it gets no line at all.
 */
export const describePasskeyPromptError = (error: unknown): PasskeyPromptMessageKey | null => {
  const name = error instanceof WebAuthnError || error instanceof Error ? error.name : "";
  if (name === "AbortError") return null;
  if (name === "NotAllowedError") return "auth:login.passkeyCancelled";
  return "auth:login.passkeyFailed";
};

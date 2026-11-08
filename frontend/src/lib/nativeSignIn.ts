/**
 * A sign-in the app finishes in the phone's browser.
 *
 * The app cannot hold an identity provider's redirect itself, so it opens the
 * system browser, and the sign-in comes back to
 * `initiative://oidc/callback` as a one-time code. The code is bound to a PKCE
 * challenge the app made when it began (RFC 8252, RFC 7636): only the verifier
 * kept here redeems it, and a callback that arrives when this app began no
 * sign-in is ignored.
 */
import { redeemNativeSignIn as redeemNativeSignInRequest } from "@/api/generated/auth/auth";
import type { NativeSession } from "@/lib/nativeSession";
import { CREDENTIAL_KEYS, getItem, removeItem, setItem } from "@/lib/storage";

/** As long as the server's own sign-in flow lives. */
const PENDING_TTL_MS = 10 * 60 * 1000;

interface PendingSignIn {
  verifier: string;
  origin: string;
  startedAt: number;
}

const base64url = (bytes: Uint8Array): string =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

/** A PKCE verifier and its S256 challenge (RFC 7636). */
export const pkcePair = async (): Promise<{ verifier: string; challenge: string }> => {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: base64url(new Uint8Array(digest)) };
};

/**
 * Begin a sign-in against `origin` and return the challenge to send with it.
 *
 * The verifier is written before the browser opens: the phone often closes the
 * app while the browser is in front, and the callback then starts it afresh.
 */
export const beginNativeSignIn = async (origin: string): Promise<string> => {
  const { verifier, challenge } = await pkcePair();
  const pending: PendingSignIn = { verifier, origin, startedAt: Date.now() };
  await setItem(CREDENTIAL_KEYS.pendingSignIn, JSON.stringify(pending));
  return challenge;
};

/** The sign-in this app began against `origin`, taken so it is answered once. */
export const takePendingSignIn = (origin: string | null): PendingSignIn | null => {
  const raw = getItem(CREDENTIAL_KEYS.pendingSignIn);
  void removeItem(CREDENTIAL_KEYS.pendingSignIn);
  if (!raw || !origin) return null;
  try {
    const pending = JSON.parse(raw) as PendingSignIn;
    const fresh = Date.now() - pending.startedAt < PENDING_TTL_MS;
    return fresh && pending.origin === origin ? pending : null;
  } catch {
    return null;
  }
};

/** Trade the code a callback carried for the session it earned. */
export const redeemNativeSignIn = async (
  code: string,
  pending: PendingSignIn
): Promise<NativeSession | null> => {
  const token = await redeemNativeSignInRequest({
    code,
    code_verifier: pending.verifier,
  });
  return token.refresh_token
    ? { accessToken: token.access_token, refreshToken: token.refresh_token }
    : null;
};

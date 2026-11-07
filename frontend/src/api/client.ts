import { Capacitor } from "@capacitor/core";
import axios, { type AxiosRequestConfig, type AxiosResponse } from "axios";

import { readRefreshToken, storeRefreshToken } from "@/lib/nativeSession";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { getItem, removeItem, setItem } from "@/lib/storage";

const DEFAULT_API_BASE_URL = "/api/v1";
const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1"]);

/**
 * Resolve the initial API base URL.
 * On native platforms, we return a placeholder - the actual URL
 * will be set by the ServerProvider after loading from storage.
 */
const resolveApiBaseUrl = (): string => {
  const envValue = import.meta.env.VITE_API_URL?.trim();
  const isNative = Capacitor.isNativePlatform();

  // On native, the URL will be set dynamically by ServerProvider
  // We use a placeholder that will fail if used before configuration
  if (isNative) {
    // If env value is set (for dev/testing), use it as initial value
    if (envValue) {
      return envValue;
    }
    return ""; // Will be set by ServerProvider
  }

  if (!envValue) {
    return DEFAULT_API_BASE_URL;
  }

  if (typeof window === "undefined") {
    return envValue;
  }

  try {
    const resolved = new URL(envValue, window.location.origin);
    const envIsLocalhost = LOCAL_HOSTNAMES.has(resolved.hostname.toLowerCase());
    const browserIsLocalhost = LOCAL_HOSTNAMES.has(window.location.hostname.toLowerCase());

    if (envIsLocalhost && !browserIsLocalhost) {
      // A localhost API URL is unreachable when the SPA is served from a remote host.
      return DEFAULT_API_BASE_URL;
    }

    if (resolved.origin === window.location.origin) {
      return `${resolved.pathname}${resolved.search}` || DEFAULT_API_BASE_URL;
    }

    return resolved.toString();
  } catch {
    if (envValue.startsWith("/")) {
      return envValue;
    }
  }

  return DEFAULT_API_BASE_URL;
};

export let API_BASE_URL = resolveApiBaseUrl();

/**
 * Dynamically update the API base URL.
 * Used by ServerProvider on native platforms to set the user-configured server URL.
 */
export const setApiBaseUrl = (url: string) => {
  API_BASE_URL = url;
  apiClient.defaults.baseURL = url;
};

/**
 * Whether an address is on the app's own origin or the server's. A frame that
 * lets its page run scripts with its own origin shows neither.
 */
export const isOwnOrigin = (url: string): boolean => {
  try {
    const origin = new URL(url, window.location.href).origin;
    return (
      origin === window.location.origin ||
      origin === new URL(API_BASE_URL, window.location.href).origin
    );
  } catch {
    return false;
  }
};

export const AUTH_UNAUTHORIZED_EVENT = "initiative:auth:unauthorized";
export const AUTH_STEP_UP_EVENT = "initiative:auth:step-up";
/** A community wants a factor of the account's own on this session. */
export const AUTH_FACTOR_REQUIRED_EVENT = "initiative:auth:factor-required";

/** A listed community wants this account's answer to the age question before
 *  it lets them in. Not the deployment's ask: everywhere else carries on. */
export const AUTH_AGE_REQUIRED_EVENT = "initiative:auth:age-required";

/** The account was suspended: every route but its time-out screen refuses it. */
export const AUTH_ACCOUNT_SUSPENDED_EVENT = "initiative:auth:account-suspended";

export interface AgeChallengeDetail {
  /** True where the account already answered under the minimum. The dialog
   *  explains instead of asking, because that answer stands. */
  answerStands: boolean;
}

/** The factors a community can name as its own requirement. */
export type CommunityFactorKind = "totp" | "passkey";

export interface FactorChallengeDetail {
  communityId: number | null;
  /** True when the deployment itself is asking, rather than a community. The
   *  dialog says so, and offers to sign out rather than to carry on: a
   *  platform refusal is every request, not one page's. */
  platform?: boolean;
  /** Which answer the dialog asks for: a code from the authenticator app, a
   *  passkey, or — for a change to the account's own sign-in — a session
   *  opened a moment ago. Only a community's own two carry a community. */
  kind: CommunityFactorKind | "proof";
}

export interface StepUpEventDetail {
  /** Slug of the provider the community requires (X-Auth-Step-Up header). */
  providerSlug: string;
  /**
   * Community whose login flow serves that provider (X-Auth-Step-Up-Community
   * header); null on servers that predate community-addressed login URLs.
   */
  communityId: number | null;
}

let authToken: string | null = null;
// Tracks whether we currently believe a user session is active. On web the
// in-memory authToken is never set after a page reload (cookie auth is
// HttpOnly, so there's nothing for JS to restore). The 401 interceptor used
// to gate on `authToken` being set, which meant expired-cookie 401s were
// silently swallowed for reloaded tabs — the user had to manually refresh
// again to land on /welcome. An explicit session flag closes that gap.
let hasActiveSession = false;

/** Set the access token sent as `Authorization: Bearer`. */
export const setAuthToken = (token: string | null) => {
  authToken = token;
  if (token) noteSessionClock(token);
};

export const getAuthToken = (): string | null => authToken;

export const setHasActiveSession = (value: boolean) => {
  hasActiveSession = value;
};

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  // Send cookies for web sessions (HttpOnly cookie auth).
  // Disabled on native: Capacitor uses Bearer headers and the
  // backend returns Access-Control-Allow-Origin: * which is incompatible
  // with credentialed requests per the CORS spec.
  withCredentials: !Capacitor.isNativePlatform(),
  paramsSerializer: (params) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined) continue;
      if (Array.isArray(value)) {
        if (value.length > 0 && typeof value[0] === "object") {
          // Arrays of objects (e.g. FilterCondition[]) → JSON string
          searchParams.append(key, JSON.stringify(value));
        } else {
          // Primitive arrays → repeated key format (key=1&key=2)
          value.forEach((v) => {
            searchParams.append(key, String(v));
          });
        }
      } else {
        searchParams.append(key, String(value));
      }
    }
    return searchParams.toString();
  },
});

/**
 * What this copy of the app is called on the server it talks to: made once per
 * server, so no two servers hear the same name, and kept through sign-out. A
 * sign-in from the app carries it, and the server continues this install's
 * session rather than counting another device.
 */
const installId = (): string => {
  const key = `initiative-install:${getStoredServerUrl() ?? "default"}`;
  const held = getItem(key);
  if (held) return held;
  const made = crypto.randomUUID();
  void setItem(key, made);
  return made;
};

apiClient.interceptors.request.use((config) => {
  config.headers = config.headers ?? {};
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`;
  }
  if (Capacitor.isNativePlatform()) {
    config.headers["X-Initiative-Install"] = installId();
  }
  return config;
});

// What keeps a session alive is the person, not the app: polling, socket pushes
// and refetches on focus do not count. Every renewal says how long ago the last
// input was, and the server runs the idle window from then. Ahead of the access
// token running out, the app renews only if there has been input since the
// last renewal, so a session nobody is using ends when its window does.
//
// Both times are shared by every window of this origin and kept across a
// restart: input in any tab is the person being here.
const LAST_INPUT_KEY = "initiative-last-input";
const SESSION_CLOCK_KEY = "initiative-session-clock";
//: How often input is written down; the tab keeps the exact time itself.
const INPUT_WRITE_EVERY_MS = 10_000;
//: How long before the access token runs out the app renews.
const RENEW_AHEAD_MS = 120_000;
const INPUT_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

interface SessionClock {
  issuedAt: number;
  expiresAt: number;
}

let lastInputHere: number | null = null;
let renewTimer: ReturnType<typeof setTimeout> | undefined;

const storedInput = (): number => {
  const stored = Number(getItem(LAST_INPUT_KEY));
  return Number.isFinite(stored) && stored > 0 ? stored : 0;
};

const lastInput = (): number | null => Math.max(lastInputHere ?? 0, storedInput()) || null;

/** When the access token in hand was issued and when it runs out, from its claims. */
function noteSessionClock(token: string): void {
  try {
    const claims = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))) as {
      iat?: unknown;
      exp?: unknown;
    };
    if (typeof claims.iat === "number" && typeof claims.exp === "number") {
      const clock: SessionClock = { issuedAt: claims.iat * 1000, expiresAt: claims.exp * 1000 };
      setItem(SESSION_CLOCK_KEY, JSON.stringify(clock));
    }
  } catch {
    // Not a token this app can read the times of; the next input renews.
  }
}

const sessionClock = (): SessionClock | null => {
  try {
    return JSON.parse(getItem(SESSION_CLOCK_KEY) ?? "null") as SessionClock | null;
  } catch {
    return null;
  }
};

/** Renew if the person has done something since the last renewal and the token is near its end. */
const renewIfDue = (): void => {
  clearTimeout(renewTimer);
  if (!hasActiveSession || !canRenewSession()) return;
  const input = lastInput();
  const clock = sessionClock();
  // Nothing since the last renewal: the next input asks again.
  if (input === null || (clock !== null && input <= clock.issuedAt)) return;
  if (clock !== null) {
    const due = clock.expiresAt - Math.min(RENEW_AHEAD_MS, (clock.expiresAt - clock.issuedAt) / 2);
    if (Date.now() < due) {
      renewTimer = setTimeout(renewIfDue, due - Date.now());
      return;
    }
  }
  void attemptSessionRefresh();
};

const noteInput = (): void => {
  const now = Date.now();
  lastInputHere = now;
  if (now - storedInput() >= INPUT_WRITE_EVERY_MS) setItem(LAST_INPUT_KEY, String(now));
  renewIfDue();
};

/** Count the person's input toward their session while they are signed in. */
export const watchForActivity = (): (() => void) => {
  if (typeof window === "undefined") return () => undefined;
  const onVisible = () => {
    if (document.visibilityState === "visible") noteInput();
  };
  for (const event of INPUT_EVENTS) {
    window.addEventListener(event, noteInput, { passive: true, capture: true });
  }
  document.addEventListener("visibilitychange", onVisible);
  return () => {
    clearTimeout(renewTimer);
    for (const event of INPUT_EVENTS) {
      window.removeEventListener(event, noteInput, { capture: true });
    }
    document.removeEventListener("visibilitychange", onVisible);
  };
};

/** Somebody has just signed in, which is them being here. */
export const startSessionActivity = (): void => {
  lastInputHere = Date.now();
  setItem(LAST_INPUT_KEY, String(lastInputHere));
};

/** Forget both times, for a session that has ended on this device. */
export const forgetSessionActivity = (): void => {
  clearTimeout(renewTimer);
  lastInputHere = null;
  removeItem(LAST_INPUT_KEY);
  removeItem(SESSION_CLOCK_KEY);
};

const emitUnauthorized = () => {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
  }
};

// Silent session renewal. An expired access token is renewable: the refresh
// token issued at login (an HttpOnly cookie on the web, kept by the app on
// native) rotates into a fresh session via POST /auth/refresh, so a 401 gets
// one renewal attempt and a retry before it is surfaced as a signed-out state.
// Concurrent 401s share a single in-flight refresh.
let refreshInFlight: Promise<boolean> | null = null;

// Whether a failed renewal is an answer about the session. Only a 401 is: it
// is what the renewal endpoint answers about a credential. Everything else —
// a timeout, a dropped connection, a 5xx, a 429 — is the request not getting
// through, which says nothing either way, and the next one renews again.
const isCredentialRefused = (error: unknown): boolean =>
  (error as { response?: { status?: number } } | undefined)?.response?.status === 401;

// One renewal at a time across every window of this origin. Windows renew on
// their own schedules and the guard above sees only its own, so something
// shared has to decide whose turn it is.
const REFRESH_LOCK = "initiative:auth:refresh";
//: How long a window waits before deciding it holds the turn. Long enough for
//: a write from a window that started at the same moment to land.
const TURN_SETTLE_MS = 60;
//: How long a window waits for the one holding the turn to report back before
//: renewing itself. Generous: the cost of waiting too briefly is both windows
//: renewing, and the cost of waiting at all is a retry arriving later.
const TURN_WAIT_MS = 10_000;

const TURN_KEY = "initiative-auth-renewal-turn";
const TURN_DONE_KEY = "initiative-auth-renewal-done";

type Renewal = AxiosResponse<{ access_token: string }>;
/** Another window renewed; this one has a fresh cookie and nothing to send. */
const RENEWED_BY_PEER = Symbol("renewed-by-peer");
type TurnResult = Renewal | typeof RENEWED_BY_PEER;

// The browser's refresh token is a cookie it cannot read, so it sends nothing
// and the server reads the jar. The native app keeps its own and has to hand it
// over — and gets the replacement back the same way, because rotation means the
// one it holds is spent.
const renew = async (): Promise<Renewal> => {
  const stored = readRefreshToken();
  const input = lastInput();
  const body = {
    ...(stored ? { refresh_token: stored } : {}),
    // How long ago the person was last here, which is where the idle window
    // runs from.
    ...(input !== null
      ? { idle_seconds: Math.max(0, Math.floor((Date.now() - input) / 1000)) }
      : {}),
  };
  const response = await apiClient.post<{ access_token: string; refresh_token?: string }>(
    "/auth/refresh",
    Object.keys(body).length > 0 ? body : undefined
  );
  if (response.data?.refresh_token) {
    storeRefreshToken(response.data.refresh_token);
  }
  if (response.data?.access_token) {
    noteSessionClock(response.data.access_token);
  }
  return response;
};

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** What the window holding the turn reported, or null if it never did. */
const waitForTurnHolder = (): Promise<string | null> =>
  new Promise((resolve) => {
    if (typeof window === "undefined") {
      resolve(null);
      return;
    }
    const settle = (value: string | null) => {
      window.clearTimeout(timer);
      window.removeEventListener("storage", onStorage);
      resolve(value);
    };
    // Fires in the OTHER windows of this origin, which is this one's position.
    const onStorage = (event: StorageEvent) => {
      if (event.key === TURN_DONE_KEY) settle(event.newValue);
    };
    const timer = window.setTimeout(() => settle(null), TURN_WAIT_MS);
    window.addEventListener("storage", onStorage);
  });

/**
 * Take a turn among the windows of this origin without a lock manager.
 *
 * Every window writes its own claim and the last write wins, so a moment later
 * at most one of them still reads its own back. That one renews and says so;
 * the others wait for it and use what it left. A window that hears nothing, or
 * hears that it did not go well, renews itself — the worst case is the two
 * renewals that would have happened anyway.
 */
const renewTakingTurns = async (): Promise<TurnResult> => {
  const claim = `${Date.now()}:${Math.random().toString(36).slice(2)}`;
  setItem(TURN_KEY, claim);
  await wait(TURN_SETTLE_MS);

  if (getItem(TURN_KEY) !== claim) {
    if ((await waitForTurnHolder())?.endsWith(":ok")) {
      return RENEWED_BY_PEER;
    }
  }

  let outcome = "no";
  try {
    const response = await renew();
    outcome = "ok";
    return response;
  } finally {
    // Written last, and always: it is what the waiting windows are listening
    // for, and a window that never reports leaves them to renew for themselves.
    removeItem(TURN_KEY);
    setItem(TURN_DONE_KEY, `${Date.now()}:${outcome}`);
  }
};

const takeRenewalTurn = (): Promise<TurnResult> => {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  return locks ? locks.request(REFRESH_LOCK, renew) : renewTakingTurns();
};

// The browser always has its refresh cookie to try. The app renews only with a
// refresh token in hand; without one a 401 really is the end of the session.
const canRenewSession = (): boolean => !Capacitor.isNativePlatform() || !!readRefreshToken();

const attemptSessionRefresh = (): Promise<boolean> => {
  if (!refreshInFlight) {
    refreshInFlight = takeRenewalTurn()
      .then((result) => {
        // A Bearer token held in memory (web keeps one until reload) must
        // follow the rotation — the retried request would otherwise resend the
        // stale header, which the backend reads before the fresh cookie. When
        // another window renewed, the token it was handed is not ours to hold,
        // so the retry goes on the cookie that window set.
        if (authToken || readRefreshToken()) {
          setAuthToken(result === RENEWED_BY_PEER ? null : result.data?.access_token || null);
        }
        return true;
      })
      .catch((error: unknown) => {
        // Surfacing the signed-out state lives HERE, not with the callers:
        // however many concurrent 401s share this renewal, the event fires
        // exactly once per failed attempt — and only when the renewal was
        // actually refused.
        if (hasActiveSession && isCredentialRefused(error)) {
          emitUnauthorized();
        }
        return false;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
};

/**
 * Renew now, sharing whatever attempt is already running, and report the access
 * token it produced.
 *
 * For the native app's cold start: it holds a refresh token and no access
 * token, and a refresh token is spent by its first use — two requests carrying
 * the same one read as a replay and revoke the chain. Going through the one
 * coordinator is what makes a second caller wait for the first instead.
 */
export const renewSession = async (): Promise<string | null> =>
  (await attemptSessionRefresh()) ? getAuthToken() : null;

// Auth lifecycle endpoints must not trigger a renewal: /auth/refresh itself
// (recursion), and login/logout, whose 401s mean something other than "the
// access token expired mid-session".
const isAuthLifecyclePath = (url: string | undefined): boolean =>
  !!url && /\/auth\/(token|refresh|logout)(\?|$)/.test(url);

interface RetriableRequestConfig extends AxiosRequestConfig {
  _sessionRefreshRetried?: boolean;
}

// A community step-up 401 means "this community requires another sign-in factor" —
// the session itself is fine, so it must neither trigger a renewal nor the
// signed-out toast; the page handles it.
const isStepUpChallenge = (error: { response?: { data?: { detail?: unknown } } }): boolean =>
  error.response?.data?.detail === "COMMUNITY_AUTH_STEP_UP_REQUIRED";

// Issuing yourself a grant (break glass, a billing visit) takes the account's
// second factor with the request. The session is fine, so it neither renews
// nor reads as signed out; the caller asks for the factor and sends it again.
const isGrantFactorRefusal = (error: { response?: { data?: { detail?: unknown } } }): boolean =>
  error.response?.data?.detail === "ACCESS_GRANT_SECOND_FACTOR_REQUIRED";

// The other half of the same idea: this community wants a factor of the
// account's own — a code from its authenticator app, or a passkey — which no
// provider's sign-in page supplies. The session itself is fine, so like the
// step-up above these must neither renew nor read as signed out; what answers
// them is presented against the session already open.
//
// A change to how the account itself signs in asks for the same thing in a
// different shape: a session opened a moment ago, which presenting a passkey
// (or signing in again) is what opens. Same handling — the session in hand is
// not the problem, so nothing renews and nothing reads as signed out.
const FACTOR_CHALLENGE_KINDS: Record<string, FactorChallengeDetail["kind"]> = {
  COMMUNITY_AUTH_FACTOR_REQUIRED: "totp",
  COMMUNITY_AUTH_PASSKEY_REQUIRED: "passkey",
  RECENT_PROOF_REQUIRED: "proof",
  // And the deployment's own, answered by the same dialog: a factor of the
  // account's, presented against the session already open.
  PLATFORM_AUTH_FACTOR_REQUIRED: "totp",
};

/** Whether the refusal came from the deployment rather than a community. */
const isPlatformFactorChallenge = (error: {
  response?: { data?: { detail?: unknown } };
}): boolean => error.response?.data?.detail === "PLATFORM_AUTH_FACTOR_REQUIRED";

const factorChallengeKind = (error: {
  response?: { data?: { detail?: unknown } };
}): FactorChallengeDetail["kind"] | null => {
  const detail = error.response?.data?.detail;
  return typeof detail === "string" ? (FACTOR_CHALLENGE_KINDS[detail] ?? null) : null;
};

// Community context lives in the request URL (/c/{communityId}/…), per tab — there is
// no ambient community context to guard a response against, so the only response
// concern left is an expired session: try a silent renewal, then surface it.
apiClient.interceptors.response.use(undefined, async (error) => {
  const config = error.config as RetriableRequestConfig | undefined;
  // A listed community asking its own members the age question. The session is
  // fine, so like the challenges below this neither renews nor reads as signed
  // out — and unlike the deployment's ask, it is one community's door rather
  // than every request.
  const ageDetail = error.response?.data?.detail;
  // Suspended since this tab loaded: the account is re-read, and the app
  // shell gives way to the time-out screen.
  if (ageDetail === "ACCOUNT_SUSPENDED") {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(AUTH_ACCOUNT_SUSPENDED_EVENT));
    }
    return Promise.reject(error);
  }
  if (
    ageDetail === "COMMUNITY_AGE_CONFIRMATION_REQUIRED" ||
    ageDetail === "COMMUNITY_AGE_BELOW_MINIMUM"
  ) {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent<AgeChallengeDetail>(AUTH_AGE_REQUIRED_EVENT, {
          detail: { answerStands: ageDetail === "COMMUNITY_AGE_BELOW_MINIMUM" },
        })
      );
    }
    return Promise.reject(error);
  }
  const factorKind = factorChallengeKind(error);
  if (factorKind) {
    if (typeof window !== "undefined") {
      // A proof challenge is the account's own business, and so is the
      // deployment's own rule, so neither names a community.
      const platform = isPlatformFactorChallenge(error);
      const rawCommunityId =
        factorKind === "proof" || platform
          ? null
          : error.response?.headers?.["x-auth-step-up-community"];
      const communityId =
        typeof rawCommunityId === "string" && /^\d+$/.test(rawCommunityId)
          ? Number(rawCommunityId)
          : null;
      window.dispatchEvent(
        new CustomEvent<FactorChallengeDetail>(AUTH_FACTOR_REQUIRED_EVENT, {
          // Carried only when it is true: a community's ask is the ordinary
          // one, and says nothing about the deployment.
          detail: { communityId, kind: factorKind, ...(platform ? { platform: true } : {}) },
        })
      );
    }
    return Promise.reject(error);
  }
  if (isStepUpChallenge(error)) {
    // Announce the challenge so the global step-up dialog can offer the
    // required provider's sign-in; the request itself still rejects (pages
    // render their error state, nothing retries).
    const providerSlug = error.response?.headers?.["x-auth-step-up"];
    const rawCommunityId = error.response?.headers?.["x-auth-step-up-community"];
    const communityId =
      typeof rawCommunityId === "string" && /^\d+$/.test(rawCommunityId)
        ? Number(rawCommunityId)
        : null;
    if (typeof providerSlug === "string" && providerSlug && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent<StepUpEventDetail>(AUTH_STEP_UP_EVENT, {
          detail: { providerSlug, communityId },
        })
      );
    }
    return Promise.reject(error);
  }
  if (isGrantFactorRefusal(error)) return Promise.reject(error);
  if (
    error.response?.status === 401 &&
    canRenewSession() &&
    config &&
    !config._sessionRefreshRetried &&
    !isAuthLifecyclePath(config.url)
  ) {
    if (await attemptSessionRefresh()) {
      config._sessionRefreshRetried = true;
      return apiClient(config);
    }
    // The failed renewal already surfaced the signed-out state (once, from
    // the shared attempt) — just hand the original rejection back.
    return Promise.reject(error);
  }
  // 401s that never entered renewal: a retried request that 401'd again, and
  // native. Lifecycle 401s stay silent — a login/logout 401 is the caller's
  // to handle, not a session expiry.
  if (error.response?.status === 401 && hasActiveSession && !isAuthLifecyclePath(config?.url)) {
    emitUnauthorized();
  }
  return Promise.reject(error);
});

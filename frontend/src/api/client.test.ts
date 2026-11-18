import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { clearRefreshToken, storeRefreshToken } from "@/lib/nativeSession";
import { CREDENTIAL_KEYS, removeItem } from "@/lib/storage";

import {
  AUTH_FACTOR_REQUIRED_EVENT,
  AUTH_STEP_UP_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
  apiClient,
  forgetSessionActivity,
  setAuthToken,
  setHasActiveSession,
  startSessionActivity,
  watchForActivity,
} from "./client";

/**
 * The renewal round trip, as every case here needs it: `/me` answers 401
 * until a refresh has landed, and then answers. What the refresh saw is
 * returned so a test can assert on it; `answer` is how the refresh replies.
 */
function stubRenewal(answer: () => Response = () => HttpResponse.json({ access_token: "fresh" })) {
  const seen = {
    calls: 0,
    body: null as string | null,
    install: null as string | null,
    renewed: false,
  };
  server.use(
    http.get("/api/v1/me", () =>
      seen.renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
    ),
    http.post("/api/v1/auth/refresh", async ({ request }) => {
      seen.calls += 1;
      seen.body = await request.text();
      seen.install = request.headers.get("X-Initiative-Install");
      seen.renewed = true;
      return answer();
    })
  );
  return seen;
}

/** A renewal that is asked for and refused, however it is refused. */
function stubFailedRenewal(answer: () => Response, ...paths: string[]) {
  const seen = { calls: 0 };
  server.use(
    ...paths.map((path) => http.get(path, () => new HttpResponse(null, { status: 401 }))),
    http.post("/api/v1/auth/refresh", () => {
      seen.calls += 1;
      return answer();
    })
  );
  return seen;
}

/** One refusal that is a challenge rather than the end of a session. */
type ChallengeCase = [
  label: string,
  challenge: {
    path: string;
    method?: "post";
    status: number;
    detail: string;
    headers?: Record<string, string>;
  },
  event: string,
  announces: Record<string, unknown>,
];

const listening: Array<[string, EventListener]> = [];

/** Watch one of the client's own announcements; unhooked when the test ends. */
function watch(event: string) {
  const heard = vi.fn();
  window.addEventListener(event, heard);
  listening.push([event, heard]);
  return heard;
}

/** What an announcement carried. */
const announced = (heard: ReturnType<typeof vi.fn>) =>
  (heard.mock.calls[0][0] as CustomEvent).detail;

afterEach(() => {
  for (const [event, heard] of listening.splice(0)) window.removeEventListener(event, heard);
  setHasActiveSession(false);
  setAuthToken(null);
});

// The silent-renewal interceptor: a 401 gets one POST /auth/refresh and a
// retry before it surfaces as a signed-out state (web only — the refresh
// cookie is HttpOnly, so the tests only observe the requests, not the cookie).
// The native app has no cookie to send: it keeps its own refresh token and
// hands it over, and rotation means the replacement has to be kept too.
describe("renewal for a client that holds its own refresh token", () => {
  afterEach(() => {
    clearRefreshToken();
    removeItem(CREDENTIAL_KEYS.refreshToken);
  });

  it("sends the stored token and keeps the one that comes back", async () => {
    storeRefreshToken("rt-old");
    const seen = stubRenewal(() =>
      HttpResponse.json({ access_token: "fresh", refresh_token: "rt-new" })
    );

    await apiClient.get("/me");

    expect(JSON.parse(seen.body ?? "null")).toEqual({ refresh_token: "rt-old" });
    // A browser is not an install; only the app names one.
    expect(seen.install).toBeNull();
    // Spent on use, so the one held has to be the replacement.
    const { readRefreshToken } = await import("@/lib/nativeSession");
    expect(readRefreshToken()).toBe("rt-new");
  });

  it("renews on native rather than signing the app out", async () => {
    // An app holding a refresh token is in the browser's position, and an
    // expired access token has to renew rather than end the session.
    const { Capacitor } = await import("@capacitor/core");
    const native = vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    storeRefreshToken("rt-native");
    setHasActiveSession(true);
    const signedOut = watch(AUTH_UNAUTHORIZED_EVENT);
    const seen = stubRenewal(() =>
      HttpResponse.json({ access_token: "fresh", refresh_token: "rt-next" })
    );

    const response = await apiClient.get("/me");

    expect(response.data).toEqual({ id: 1 });
    expect(signedOut).not.toHaveBeenCalled();
    // The app names its install on every request, the same one each time.
    expect(seen.install).toMatch(/^[0-9a-f-]{36}$/);
    clearRefreshToken();
    const again = stubRenewal();
    storeRefreshToken("rt-again");
    await apiClient.get("/me");
    expect(again.install).toBe(seen.install);
    native.mockRestore();
  });

  it("sends no body when there is nothing stored", async () => {
    const seen = stubRenewal();

    await apiClient.get("/me");

    // The browser's token is a cookie it cannot read; it sends nothing and the
    // server reads the jar.
    expect(seen.body).toBe("");
  });
});

describe("what keeps a session alive", () => {
  /** An access token issued `issued` ms ago that runs out in `left` ms. */
  const accessToken = (issued: number, left: number) => {
    const now = Date.now();
    const claims = { iat: Math.floor((now - issued) / 1000), exp: Math.floor((now + left) / 1000) };
    const encoded = btoa(JSON.stringify(claims)).replace(/=+$/, "");
    return `header.${encoded}.signature`;
  };

  afterEach(() => forgetSessionActivity());

  it("renews ahead of the token only after the person has done something", async () => {
    const seen = stubRenewal(() =>
      HttpResponse.json({ access_token: accessToken(0, 15 * 60_000) })
    );
    setHasActiveSession(true);
    // Issued thirteen minutes ago and running out in one: renewal is due.
    setAuthToken(accessToken(13 * 60_000, 60_000));
    const unwatch = watchForActivity();

    // Background requests and the clock alone renew nothing.
    expect(seen.calls).toBe(0);

    window.dispatchEvent(new Event("pointerdown"));
    await vi.waitFor(() => expect(seen.calls).toBe(1));
    // The idle window runs from the input just made.
    expect(JSON.parse(seen.body ?? "null")).toEqual({ idle_seconds: 0 });

    // Fresh token: more input waits for it to near its end instead of renewing.
    window.dispatchEvent(new Event("keydown"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(seen.calls).toBe(1);
    unwatch();
  });

  it.each([
    ["nothing has been done since it was issued", () => accessToken(16 * 60_000, -60_000)],
    [
      // Its issue time is whole seconds, so it reads as no later than the
      // input that asked for it.
      "the last input asked for it",
      () => {
        startSessionActivity();
        return accessToken(0, 15 * 60_000);
      },
    ],
  ])("holds a hidden window's renewal until somebody looks, when %s", async (_when, token) => {
    const seen = stubRenewal(() =>
      HttpResponse.json({ access_token: accessToken(0, 15 * 60_000) })
    );
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    try {
      setHasActiveSession(true);
      setAuthToken(token());

      const pending = apiClient.get("/me");
      // Past the turn a window without a lock manager waits before renewing.
      await new Promise((resolve) => setTimeout(resolve, 200));
      expect(seen.calls).toBe(0);

      visibility.mockReturnValue("visible");
      document.dispatchEvent(new Event("visibilitychange"));
      expect((await pending).data).toEqual({ id: 1 });
      expect(seen.calls).toBe(1);
    } finally {
      visibility.mockRestore();
    }
  });
});

describe("silent session renewal", () => {
  it("renews the session and retries the failed request", async () => {
    const seen = stubRenewal();

    const response = await apiClient.get("/me");

    expect(response.data).toEqual({ id: 1 });
    expect(seen.calls).toBe(1);
  });

  it("shares one renewal across concurrent 401s", async () => {
    let refreshCalls = 0;
    let renewed = false;
    const gated = () =>
      renewed ? HttpResponse.json({ ok: true }) : new HttpResponse(null, { status: 401 });
    server.use(
      http.get("/api/v1/me", gated),
      http.get("/api/v1/notifications", gated),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        renewed = true;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );

    const [a, b] = await Promise.all([apiClient.get("/me"), apiClient.get("/notifications")]);

    expect(a.data).toEqual({ ok: true });
    expect(b.data).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
  });

  it("surfaces the signed-out state when renewal fails", async () => {
    const seen = stubFailedRenewal(() => new HttpResponse(null, { status: 401 }), "/api/v1/me");
    setHasActiveSession(true);
    const onUnauthorized = watch(AUTH_UNAUTHORIZED_EVENT);

    await expect(apiClient.get("/me")).rejects.toMatchObject({
      response: { status: 401 },
    });
    // Exactly one renewal attempt — the refresh endpoint's own 401 must not
    // recurse into another renewal.
    expect(seen.calls).toBe(1);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("emits one signed-out event when concurrent 401s share a failed renewal", async () => {
    const seen = stubFailedRenewal(
      () => new HttpResponse(null, { status: 401 }),
      "/api/v1/me",
      "/api/v1/notifications"
    );
    setHasActiveSession(true);
    const onUnauthorized = watch(AUTH_UNAUTHORIZED_EVENT);

    const results = await Promise.allSettled([
      apiClient.get("/me"),
      apiClient.get("/notifications"),
    ]);

    expect(results.map((r) => r.status)).toEqual(["rejected", "rejected"]);
    expect(seen.calls).toBe(1);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  // A renewal can fail without saying anything about the session: a restart,
  // a proxy hiccup, a rate limit, a dead network. The session outlives those.
  it.each([
    ["a server error", () => new HttpResponse(null, { status: 503 })],
    ["a rate limit", () => new HttpResponse(null, { status: 429 })],
    ["a request declined before it was handled", () => new HttpResponse(null, { status: 403 })],
    ["nothing answering", () => HttpResponse.error()],
  ])("keeps the session when the renewal fails with %s", async (_label, failure) => {
    stubFailedRenewal(failure, "/api/v1/me");
    setHasActiveSession(true);
    const onUnauthorized = watch(AUTH_UNAUTHORIZED_EVENT);

    // The request still fails — it just doesn't take the session with it.
    await expect(apiClient.get("/me")).rejects.toBeDefined();
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  // The guard above sees only its own window, so renewals are taken in turns
  // through a lock the whole origin shares.
  it("renews under a lock the other windows share", async () => {
    const held: string[] = [];
    let renewedInsideLock = false;
    const request = vi.fn(async (name: string, run: () => Promise<unknown>) => {
      held.push(`held:${name}`);
      const result = await run();
      held.push(`released:${name}`);
      return result;
    });
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });
    stubRenewal(() => {
      // The lock is taken before the renewal and not yet let go.
      renewedInsideLock = held.length === 1 && held[0] === "held:initiative:auth:refresh";
      return HttpResponse.json({ access_token: "fresh" });
    });

    const response = await apiClient.get("/me");

    expect(response.data).toEqual({ id: 1 });
    expect(request).toHaveBeenCalledTimes(1);
    expect(renewedInsideLock).toBe(true);
    expect(held).toEqual(["held:initiative:auth:refresh", "released:initiative:auth:refresh"]);
  });

  // Older browsers and some embedded views have no lock manager, so the turn
  // is taken through storage the windows share instead.
  describe("without a lock manager", () => {
    const TURN_KEY = "initiative-auth-renewal-turn";
    const DONE_KEY = "initiative-auth-renewal-done";

    beforeEach(() => {
      localStorage.clear();
    });

    /** Claim the turn on behalf of another window, once this one has claimed. */
    const takeTurnAsAnotherWindow = async () => {
      await vi.waitFor(() => expect(localStorage.getItem(TURN_KEY)).not.toBeNull(), {
        interval: 1,
      });
      localStorage.setItem(TURN_KEY, "another-window");
    };

    /** Report back, once the waiting window is listening for it. */
    const reportAsAnotherWindow = (outcome: "ok" | "no") => {
      setTimeout(() => {
        window.dispatchEvent(
          new StorageEvent("storage", { key: DONE_KEY, newValue: `${Date.now()}:${outcome}` })
        );
      }, 120);
    };

    it("renews and says so, for the windows waiting on it", async () => {
      stubRenewal();

      await expect(apiClient.get("/me")).resolves.toMatchObject({ data: { id: 1 } });
      // The turn is given up, and how it went is left where peers can read it.
      expect(localStorage.getItem(TURN_KEY)).toBeNull();
      expect(localStorage.getItem(DONE_KEY)).toMatch(/:ok$/);
    });

    it("uses what another window renewed rather than renewing again", async () => {
      const seen = stubRenewal();

      const pending = apiClient.get("/me");
      // Another window claims the turn after this one — the last write wins —
      // and then reports that it went well, which in a real browser is what
      // the storage event carries.
      await takeTurnAsAnotherWindow();
      seen.renewed = true;
      reportAsAnotherWindow("ok");

      await expect(pending).resolves.toMatchObject({ data: { id: 1 } });
      expect(seen.calls).toBe(0);
    });

    it("renews itself when the window holding the turn did not get there", async () => {
      stubRenewal();

      const pending = apiClient.get("/me");
      await takeTurnAsAnotherWindow();
      reportAsAnotherWindow("no");

      // It does not take the other window's word for a renewal that failed.
      await expect(pending).resolves.toMatchObject({ data: { id: 1 } });
    });
  });

  // A challenge is not a signed-out session: nothing renews and nothing reads
  // as signed out. What the client does is announce what is being asked for,
  // and where, so the global dialog can offer the sign-in.
  it.each<ChallengeCase>([
    [
      "a community's step-up, naming the provider whose login flow serves it",
      {
        path: "/c/1/projects/",
        status: 401,
        detail: "COMMUNITY_AUTH_STEP_UP_REQUIRED",
        headers: { "X-Auth-Step-Up": "corp", "X-Auth-Step-Up-Community": "1" },
      },
      AUTH_STEP_UP_EVENT,
      { providerSlug: "corp", communityId: 1 },
    ],
    [
      "COMMUNITY_AUTH_FACTOR_REQUIRED as a challenge naming the factor",
      {
        path: "/c/7/projects/",
        status: 401,
        detail: "COMMUNITY_AUTH_FACTOR_REQUIRED",
        headers: { "X-Auth-Step-Up-Community": "7" },
      },
      AUTH_FACTOR_REQUIRED_EVENT,
      { communityId: 7, kind: "totp" },
    ],
    [
      "COMMUNITY_AUTH_PASSKEY_REQUIRED as a challenge naming the factor",
      {
        path: "/c/7/projects/",
        status: 401,
        detail: "COMMUNITY_AUTH_PASSKEY_REQUIRED",
        headers: { "X-Auth-Step-Up-Community": "7" },
      },
      AUTH_FACTOR_REQUIRED_EVENT,
      { communityId: 7, kind: "passkey" },
    ],
    [
      "the deployment's own ask, which names no community",
      { path: "/communities/", status: 401, detail: "PLATFORM_AUTH_FACTOR_REQUIRED" },
      AUTH_FACTOR_REQUIRED_EVENT,
      { communityId: null, kind: "totp", platform: true },
    ],
    [
      "a change that wants a session opened a moment ago, which is the account's own",
      {
        path: "/auth/passkeys/register/options",
        method: "post",
        status: 403,
        detail: "RECENT_PROOF_REQUIRED",
      },
      AUTH_FACTOR_REQUIRED_EVENT,
      { communityId: null, kind: "proof" },
    ],
  ])("announces %s", async (_label, challenge, event, detail) => {
    const posted = challenge.method === "post";
    const refresh = { calls: 0 };
    server.use(
      (posted ? http.post : http.get)(`/api/v1${challenge.path}`, () =>
        HttpResponse.json(
          { detail: challenge.detail },
          { status: challenge.status, headers: challenge.headers }
        )
      ),
      http.post("/api/v1/auth/refresh", () => {
        refresh.calls += 1;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );
    setHasActiveSession(true);
    const onUnauthorized = watch(AUTH_UNAUTHORIZED_EVENT);
    const onChallenge = watch(event);

    await expect(
      posted ? apiClient.post(challenge.path) : apiClient.get(challenge.path)
    ).rejects.toMatchObject({ response: { status: challenge.status } });

    // The session is fine; what is missing is something else.
    expect(refresh.calls).toBe(0);
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(onChallenge).toHaveBeenCalledTimes(1);
    expect(announced(onChallenge)).toEqual(detail);
  });

  it("leaves a grant's second-factor ask to the caller, signed in", async () => {
    const refresh = { calls: 0 };
    server.use(
      http.post("/api/v1/settings/platform/communities/1/billing/service-handoff", () =>
        HttpResponse.json({ detail: "ACCESS_GRANT_SECOND_FACTOR_REQUIRED" }, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", () => {
        refresh.calls += 1;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );
    setHasActiveSession(true);
    const onUnauthorized = watch(AUTH_UNAUTHORIZED_EVENT);

    await expect(
      apiClient.post("/settings/platform/communities/1/billing/service-handoff")
    ).rejects.toMatchObject({
      response: { status: 401, data: { detail: "ACCESS_GRANT_SECOND_FACTOR_REQUIRED" } },
    });

    expect(refresh.calls).toBe(0);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("does not renew for auth lifecycle endpoints", async () => {
    let refreshCalls = 0;
    server.use(
      http.post("/api/v1/auth/token", () => new HttpResponse(null, { status: 401 })),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );

    await expect(apiClient.post("/auth/token")).rejects.toMatchObject({
      response: { status: 401 },
    });
    expect(refreshCalls).toBe(0);
  });

  it("rotates an in-memory Bearer token so the retry does not resend the stale one", async () => {
    setAuthToken("stale");
    server.use(
      http.get("/api/v1/me", ({ request }) =>
        request.headers.get("Authorization") === "Bearer fresh"
          ? HttpResponse.json({ id: 1 })
          : new HttpResponse(null, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", () => HttpResponse.json({ access_token: "fresh" }))
    );

    const response = await apiClient.get("/me");

    expect(response.data).toEqual({ id: 1 });
  });
});

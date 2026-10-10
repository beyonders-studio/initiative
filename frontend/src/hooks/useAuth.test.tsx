/**
 * Which answer about who is signed in wins.
 *
 * Reading the account is not instant and several reads can be in the air at
 * once — two signals arriving together, a signal beside the catch-up a
 * reconnect does. Responses arrive in whatever order the network gives them,
 * so "last to arrive" is not "last asked for". These pin the orderings that
 * matter, including the one where a slow read must not undo a sign-out.
 */
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { getBootstrapStatusQueryKey } from "@/api/generated/auth/auth";
import { getListNotificationsQueryKey } from "@/api/generated/notifications/notifications";

const get = vi.fn();
const post = vi.fn();
const setAuthToken = vi.fn();
const startSessionActivity = vi.fn();

vi.mock("@/api/client", () => ({
  apiClient: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    defaults: { baseURL: "" },
  },
  AUTH_UNAUTHORIZED_EVENT: "initiative:auth:unauthorized",
  AUTH_STEP_UP_EVENT: "initiative:auth:step-up",
  AUTH_ACCOUNT_SUSPENDED_EVENT: "initiative:auth:account-suspended",
  setApiBaseUrl: vi.fn(),
  setHasActiveSession: vi.fn(),
  setAuthToken: (...args: unknown[]) => setAuthToken(...args),
  getAuthToken: () => null,
  clearUploadToken: vi.fn(),
  watchForActivity: () => () => undefined,
  startSessionActivity: () => startSessionActivity(),
  forgetSessionActivity: vi.fn(),
}));

// Generated calls arrive here: the account read answers from `get`, every POST
// is recorded on `post`, and nothing else answers.
vi.mock("@/api/mutator", () => ({
  apiMutator: async ({ method, url, data }: { method: string; url: string; data?: unknown }) => {
    if (url === "/api/v1/me") return (await get(url)).data;
    if (method === "POST") return (await post(url, data)).data;
    throw new Error(`No answer for ${url}`);
  },
}));

const getItem = vi.fn((_key: string): string | null => null);
// Hoisted: i18n writes its language through storage while the setup file loads.
const setItem = vi.hoisted(() => vi.fn());
vi.mock("@/lib/storage", async (importOriginal) => ({
  CREDENTIAL_KEYS: (await importOriginal<typeof import("@/lib/storage")>()).CREDENTIAL_KEYS,
  getItem: (key: string) => getItem(key),
  setItem: (...args: unknown[]) => setItem(...args),
  removeItem: vi.fn(),
  listKeys: () => [],
}));

const forgetMessages = vi.fn();
const serveAccount = vi.fn();
vi.mock("@/crypto/messaging", () => ({
  forgetMessagesOnThisDevice: () => forgetMessages(),
  serveAccount: (server: string, userId: number) => serveAccount(server, userId),
}));

const platform = vi.hoisted(() => ({ native: false }));
vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => platform.native,
    getPlatform: () => "web",
    convertFileSrc: (url: string) => url,
  },
  registerPlugin: (_name: string, implementations?: { web?: () => unknown }) =>
    implementations?.web?.() ?? {},
}));

// The ceremony belongs to the browser's credential API, which jsdom has none
// of; what this file is about is what the hook does with the answer.
const presentPasskey = vi.fn();
vi.mock("@/lib/passkeys", () => ({
  stepUpWithPasskey: () => presentPasskey(),
}));

import { queryClient } from "@/lib/queryClient";
import { CREDENTIAL_KEYS } from "@/lib/storage";

import { AuthProvider, useAuth } from "./useAuth";

/** Resolvable on demand, so response order can be chosen rather than hoped for. */
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

let auth: ReturnType<typeof useAuth>;

const Probe = () => {
  auth = useAuth();
  return null;
};

const renderAuth = () =>
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );

describe("useAuth identity ordering", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset().mockResolvedValue({ data: {} });
    getItem.mockReset().mockReturnValue(null);
  });

  it("keeps the newer account when an older read finishes last", async () => {
    // Boot, so the provider settles before the interesting part.
    get.mockResolvedValueOnce({ data: buildUser({ username: "At boot" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("At boot"));

    const older = deferred<{ data: unknown }>();
    const newer = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);

    let firstDone: Promise<void>;
    let secondDone: Promise<void>;
    act(() => {
      firstDone = auth.refreshUser();
      secondDone = auth.refreshUser();
    });

    // The newer request answers first; the older one straggles in behind it.
    await act(async () => {
      newer.resolve({ data: buildUser({ username: "Newer" }) });
      await secondDone;
      older.resolve({ data: buildUser({ username: "Older" }) });
      await firstDone;
    });

    expect(auth.user?.username).toBe("Newer");
  });

  it("keeps the newer account when the older read finishes first", async () => {
    // The other order, and the one a turn-counter gets wrong: the older read
    // lands first, and must not make the newer answer look stale.
    get.mockResolvedValueOnce({ data: buildUser({ username: "At boot" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("At boot"));

    const older = deferred<{ data: unknown }>();
    const newer = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);

    let firstDone: Promise<void>;
    let secondDone: Promise<void>;
    act(() => {
      firstDone = auth.refreshUser();
      secondDone = auth.refreshUser();
    });

    await act(async () => {
      older.resolve({ data: buildUser({ username: "Older" }) });
      await firstDone;
      newer.resolve({ data: buildUser({ username: "Newer" }) });
      await secondDone;
    });

    expect(auth.user?.username).toBe("Newer");
  });

  it("hands back the same account object when the re-read says nothing new", async () => {
    // The account is re-read whenever the server says it might have moved, and
    // most of those answers are identical. A fresh object for one of them
    // re-runs every effect keyed on the user — including the socket that asked
    // for the read, which would then ask again, forever.
    const account = buildUser({ username: "Unchanged" });
    get.mockResolvedValue({ data: account });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("Unchanged"));
    const before = auth.user;

    await act(async () => {
      await auth.refreshUser();
    });

    expect(auth.user).toBe(before);
  });

  it("still swaps the object when the account actually moved", async () => {
    get.mockResolvedValueOnce({ data: buildUser({ username: "Before" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("Before"));
    const before = auth.user;

    get.mockResolvedValueOnce({ data: buildUser({ username: "After" }) });
    await act(async () => {
      await auth.refreshUser();
    });

    expect(auth.user).not.toBe(before);
    expect(auth.user?.username).toBe("After");
  });

  it("does not let a read in flight undo a sign-out", async () => {
    get.mockResolvedValueOnce({ data: buildUser({ username: "Signed in" }) });
    renderAuth();
    await waitFor(() => expect(auth.user).not.toBeNull());

    const slow = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(slow.promise);

    let reading: Promise<void>;
    act(() => {
      reading = auth.refreshUser();
    });
    await act(async () => {
      await auth.logout();
    });
    expect(auth.user).toBeNull();

    // The read it never got to finish comes back after the sign-out.
    await act(async () => {
      slow.resolve({ data: buildUser({ username: "Signed in" }) });
      await reading;
    });

    expect(auth.user).toBeNull();
  });

  it.each([
    { where: "a browser", native: false, forgets: true },
    { where: "the phone or desktop app", native: true, forgets: false },
  ])(
    "signs out of $where, taking its messages only from a browser",
    async ({ native, forgets }) => {
      // A browser may be shared, so a decrypted conversation must not outlive the
      // session that read it, and the sign-out must not depend on that going
      // through. A device keeps them, so signing back in reads them straight away.
      platform.native = native;
      forgetMessages.mockClear();
      forgetMessages.mockRejectedValueOnce(new Error("offline"));
      get.mockResolvedValueOnce({ data: buildUser({ username: "Signed in" }) });
      renderAuth();
      await waitFor(() => expect(auth.user).not.toBeNull());

      await act(async () => {
        await auth.logout();
      });

      expect(forgetMessages).toHaveBeenCalledTimes(forgets ? 1 : 0);
      expect(auth.user).toBeNull();
      platform.native = false;
    }
  );

  it("names the session it is ending so the server revokes only that one", async () => {
    // A native client's refresh token is the only thing that tells the server
    // which of the account's sessions is going; without it the others would
    // have to go too.
    getItem.mockImplementation((key) =>
      key === CREDENTIAL_KEYS.refreshToken ? "rt-this-device" : null
    );
    get.mockResolvedValueOnce({ data: buildUser({ username: "Signed in" }) });
    renderAuth();
    await waitFor(() => expect(auth.user).not.toBeNull());

    await act(async () => {
      await auth.logout();
    });

    expect(post).toHaveBeenCalledWith("/api/v1/auth/logout", { refresh_token: "rt-this-device" });
  });

  it.each([
    { where: "a browser", native: false, forgets: true },
    { where: "the phone or desktop app", native: true, forgets: false },
  ])(
    "ends an expired session in $where without telling the server to sign out",
    async ({ native, forgets }) => {
      // Signing out is a deliberate act that revokes the session server-side,
      // and nothing here asked for that one — the session is already gone.
      platform.native = native;
      forgetMessages.mockClear();
      get.mockResolvedValueOnce({ data: buildUser({ username: "Signed in" }) });
      renderAuth();
      await waitFor(() => expect(auth.user).not.toBeNull());
      post.mockClear();

      await act(async () => {
        window.dispatchEvent(new CustomEvent("initiative:auth:unauthorized"));
        // Let the local teardown, which awaits the message store, settle.
        await Promise.resolve();
      });

      await waitFor(() => expect(auth.user).toBeNull());
      expect(post).not.toHaveBeenCalledWith("/api/v1/auth/logout");
      // A browser may be shared, so its messages go. A device keeps them for its
      // owner's next sign-in.
      expect(forgetMessages).toHaveBeenCalledTimes(forgets ? 1 : 0);
      platform.native = false;
    }
  );

  it("applies a read that nothing overtook", async () => {
    const atBoot = buildUser({ username: "At boot" });
    get.mockResolvedValueOnce({ data: atBoot });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("At boot"));
    // The message store is settled on whoever is signed in before it is read.
    expect(serveAccount).toHaveBeenCalledWith("default", atBoot.id);

    get.mockResolvedValueOnce({ data: buildUser({ username: "Fresh" }) });
    await act(async () => {
      await auth.refreshUser();
    });

    expect(auth.user?.username).toBe("Fresh");
  });
});

describe("useAuth second factor", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset().mockResolvedValue({ data: {} });
    getItem.mockReset().mockReturnValue(null);
  });

  /** The 401 both sign-in routes answer with when a factor is outstanding. */
  const challengeRefusal = (challenge: string) => ({
    response: { status: 401, data: { detail: "TOTP_REQUIRED", challenge } },
  });

  it("hands the page the challenge instead of an error message", async () => {
    get.mockResolvedValue({ data: buildUser() });
    renderAuth();
    post.mockRejectedValueOnce(challengeRefusal("challenge-value"));

    await expect(auth.login({ email: "a@example.com", password: "pw" })).rejects.toMatchObject({
      name: "SecondFactorRequiredError",
      challenge: "challenge-value",
    });
  });

  it("still reports an ordinary refusal as one", async () => {
    get.mockResolvedValue({ data: buildUser() });
    renderAuth();
    post.mockRejectedValueOnce({
      response: { status: 400, data: { detail: "INCORRECT_CREDENTIALS" } },
    });

    const failure = auth.login({ email: "a@example.com", password: "wrong" });
    await expect(failure).rejects.toThrow();
    await expect(failure).rejects.not.toMatchObject({
      name: "SecondFactorRequiredError",
    });
  });

  it("does not mistake a 401 that carries no challenge for one", async () => {
    get.mockResolvedValue({ data: buildUser() });
    renderAuth();
    post.mockRejectedValueOnce({
      response: { status: 401, data: { detail: "TOTP_REQUIRED" } },
    });

    await expect(auth.login({ email: "a@example.com", password: "pw" })).rejects.not.toMatchObject({
      name: "SecondFactorRequiredError",
    });
  });

  it("answers the challenge with the code and signs in", async () => {
    get.mockResolvedValue({ data: buildUser({ username: "Signed in" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("Signed in"));

    post.mockResolvedValueOnce({ data: { access_token: "fresh-token" } });
    await act(async () => {
      await auth.completeSecondFactor({ challenge: "c", code: "123456" });
    });

    expect(post).toHaveBeenCalledWith("/api/v1/auth/token/totp", {
      challenge: "c",
      code: "123456",
      recovery_code: null,
    });
    // Signing in is the person being here: the session's idle window starts now.
    expect(startSessionActivity).toHaveBeenCalled();
  });

  it("sends a recovery code as one, not as a live code", async () => {
    get.mockResolvedValue({ data: buildUser() });
    renderAuth();

    post.mockResolvedValueOnce({ data: { access_token: "fresh-token" } });
    await act(async () => {
      await auth.completeSecondFactor({ challenge: "c", recoveryCode: "abcde-fghij" });
    });

    expect(post).toHaveBeenCalledWith("/api/v1/auth/token/totp", {
      challenge: "c",
      code: null,
      recovery_code: "abcde-fghij",
    });
  });
});

describe("useAuth password sign-in on native", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    getItem.mockReset().mockReturnValue(null);
    setItem.mockReset();
  });

  it("posts the browser's form with the device's name and keeps the refresh token", async () => {
    const { Capacitor } = await import("@capacitor/core");
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    get.mockResolvedValue({ data: buildUser() });
    renderAuth();
    await waitFor(() => expect(auth.user).not.toBeNull());

    post.mockResolvedValueOnce({ data: { access_token: "at", refresh_token: "rt" } });
    await act(async () => {
      await auth.login({ email: "a@example.com", password: "pw", deviceName: "Pixel" });
    });

    const [url, form] = post.mock.calls[0] as [string, URLSearchParams];
    expect(url).toBe("/api/v1/auth/token");
    expect(form.get("username")).toBe("a@example.com");
    expect(form.get("device_name")).toBe("Pixel");
    expect(setItem).toHaveBeenCalledWith(CREDENTIAL_KEYS.refreshToken, "rt");
    expect(setAuthToken).toHaveBeenCalledWith("at");
  });
});

describe("useAuth passkey sign-in", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset().mockResolvedValue({ data: {} });
    getItem.mockReset().mockReturnValue(null);
    setAuthToken.mockReset();
  });

  it("takes the session the ceremony produced and reads the account", async () => {
    get.mockResolvedValueOnce({ data: buildUser({ username: "Nobody yet" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("Nobody yet"));

    get.mockResolvedValueOnce({ data: buildUser({ username: "Signed in" }) });
    await act(async () => {
      await auth.applyPasskeySignIn({ access_token: "fresh-token", token_type: "bearer" });
    });

    expect(setAuthToken).toHaveBeenCalledWith("fresh-token");
    expect(auth.token).toBe("fresh-token");
    expect(auth.user?.username).toBe("Signed in");
  });

  it("refuses an answer with no session in it", async () => {
    // The mobile shape: the ceremony was run on behalf of an app, and what
    // comes back is a way home rather than a session for this browser.
    get.mockResolvedValue({ data: buildUser() });
    renderAuth();
    await waitFor(() => expect(auth.user).not.toBeNull());

    await expect(
      auth.applyPasskeySignIn({ token_type: "bearer", redirect_to: "initiative://oidc/callback" })
    ).rejects.toThrow();
  });
});

describe("useAuth account switch", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset().mockResolvedValue({ data: {} });
    getItem.mockReset().mockReturnValue(null);
  });

  it("drops the previous account's answers when a sign-in names somebody else", async () => {
    const before = buildUser({ username: "Before" });
    get.mockResolvedValue({ data: before });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("Before"));
    queryClient.setQueryData(getListNotificationsQueryKey(), { items: ["theirs"] });

    // A re-read of the same account keeps what it holds.
    await act(async () => {
      await auth.refreshUser();
    });
    expect(queryClient.getQueryData(getListNotificationsQueryKey())).toBeDefined();

    get.mockResolvedValue({ data: buildUser({ username: "Demo" }) });
    await act(async () => {
      await auth.applySignIn({ access_token: "demo-token", token_type: "bearer" });
    });

    expect(auth.user?.username).toBe("Demo");
    expect(queryClient.getQueryData(getListNotificationsQueryKey())).toBeUndefined();
  });
});

describe("useAuth registration", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    getItem.mockReset().mockReturnValue(null);
  });

  it("asks the server again whether anyone has signed up", async () => {
    get.mockResolvedValue({ data: null });
    renderAuth();
    queryClient.setQueryData(getBootstrapStatusQueryKey(), {
      has_users: false,
      public_registration_enabled: true,
    });

    post.mockResolvedValueOnce({ data: buildUser({ email_verified: false }) });
    await act(async () => {
      await auth.register({ email: "first@example.com", username: "first", password: "pw" });
    });

    // The first account waits on a letter, so nobody is signed in, and /login
    // reads the fresh answer rather than offering first-run registration again.
    expect(queryClient.getQueryState(getBootstrapStatusQueryKey())?.isInvalidated).toBe(true);
  });
});

describe("useAuth passkey step-up", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset().mockResolvedValue({ data: {} });
    getItem.mockReset().mockReturnValue(null);
    setAuthToken.mockReset();
    presentPasskey.mockReset();
  });

  it("takes the session the ceremony produced, as the code step-up does", async () => {
    get.mockResolvedValueOnce({ data: buildUser({ username: "Half in" }) });
    renderAuth();
    await waitFor(() => expect(auth.user?.username).toBe("Half in"));

    presentPasskey.mockResolvedValueOnce({ access_token: "stepped-up", token_type: "bearer" });
    get.mockResolvedValueOnce({ data: buildUser({ username: "All the way in" }) });
    await act(async () => {
      await auth.stepUpWithPasskey();
    });

    expect(setAuthToken).toHaveBeenCalledWith("stepped-up");
    expect(auth.token).toBe("stepped-up");
    expect(auth.user?.username).toBe("All the way in");
  });

  it("leaves the session alone when the ceremony produced nothing", async () => {
    get.mockResolvedValue({ data: buildUser() });
    renderAuth();
    await waitFor(() => expect(auth.user).not.toBeNull());
    setAuthToken.mockClear();

    presentPasskey.mockRejectedValueOnce(new Error("no credential"));
    await expect(auth.stepUpWithPasskey()).rejects.toThrow();
    expect(setAuthToken).not.toHaveBeenCalled();
  });
});

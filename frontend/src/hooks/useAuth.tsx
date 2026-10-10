import { Capacitor } from "@capacitor/core";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  AUTH_ACCOUNT_SUSPENDED_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
  forgetSessionActivity,
  renewSession,
  setAuthToken,
  setHasActiveSession,
  startSessionActivity,
  watchForActivity,
} from "@/api/client";
import {
  answerSecondFactor,
  stepUpWithFactor as answerStepUpWithFactor,
  logout as endServerSession,
  getBootstrapStatusQueryKey,
  loginAccessToken,
  registerUser,
  verifyStepUpCode,
} from "@/api/generated/auth/auth";
import type {
  PasskeySignInResult,
  Token,
  UserCreate,
  UserRead,
} from "@/api/generated/initiativeAPI.schemas";
import { readMe } from "@/api/generated/users/users";
import { clearAllWhiteboardSceneCaches } from "@/components/files/whiteboardSceneCache";
import { forgetMessagesOnThisDevice, serveAccount } from "@/crypto/messaging";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { clearJustSignedIn, markJustSignedIn } from "@/lib/authTransition";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import {
  clearRefreshToken,
  type NativeSession,
  readRefreshToken,
  storeRefreshToken,
} from "@/lib/nativeSession";
import {
  isOfflineCacheEnabled,
  purgeOfflineCache,
  restoredIdentityMismatch,
  setOfflineWritesAllowed,
} from "@/lib/offlineCache";
import {
  clearOfflineSession,
  currentServerKey,
  isNoAnswerError,
  isSessionRejected,
  readOfflineSession,
  saveOfflineSession,
} from "@/lib/offlineSession";
import { stepUpWithPasskey as presentPasskeyForStepUp } from "@/lib/passkeys";
import { forgetPushOnThisDevice } from "@/lib/pushRegistration";
import { queryClient } from "@/lib/queryClient";
import { CREDENTIAL_KEYS, removeItem } from "@/lib/storage";
import { clearUploadToken } from "@/lib/uploadToken";
import { prefetchViewPreferences } from "@/lib/viewPreferences";

interface LoginPayload {
  email: string;
  password: string;
  /** On native, the label the session is listed under. */
  deviceName?: string;
}

/** Answering a challenge: one of the two codes, never both. */
interface SecondFactorPayload {
  challenge: string;
  code?: string;
  recoveryCode?: string;
}

/** The factor presented against a session that is already open. */
interface StepUpPayload {
  code?: string;
  recoveryCode?: string;
}

interface EmailCodeStepUpPayload {
  challenge: string;
  code: string;
}

type RegisterPayload = UserCreate & { inviteCode?: string };

interface AuthContextValue {
  user: UserRead | null;
  token: string | null;
  loading: boolean;
  /**
   * True when the signed-in user came from a stored snapshot the server has not
   * confirmed — the app opened with no signal. Cleared as soon as any request
   * succeeds; a rejected one ends the session.
   */
  sessionUnverified: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  completeSecondFactor: (payload: SecondFactorPayload) => Promise<void>;
  applyPasskeySignIn: (result: PasskeySignInResult) => Promise<void>;
  /** Adopt a session a sign-in route answered with directly: a code sent to
   *  an address, or a demo link. */
  applySignIn: (token: Token) => Promise<void>;
  stepUpWithFactor: (payload: StepUpPayload) => Promise<void>;
  stepUpWithPasskey: () => Promise<void>;
  stepUpWithEmailCode: (payload: EmailCodeStepUpPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<UserRead>;
  /** Finish a sign-in that ended outside this page: a browser's, whose cookie
   *  the server set, or the app's, with what its callback redeemed. */
  completeOidcLogin: (credential?: NativeSession) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  /** Take an account the server just answered with (a write's response) as
   *  the newest read. */
  acceptUser: (user: UserRead) => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/**
 * The password was right and the account holds a second factor, so the sign-in
 * is not finished.
 *
 * Thrown rather than returned so `login` keeps one contract — it resolves when
 * you are signed in and throws when you are not — while still handing the page
 * the one thing it needs to carry on with.
 */
export class SecondFactorRequiredError extends Error {
  readonly challenge: string;

  constructor(challenge: string) {
    super("TOTP_REQUIRED");
    this.name = "SecondFactorRequiredError";
    this.challenge = challenge;
  }
}

/** The shape of the 401 that carries a challenge, from either sign-in route. */
const secondFactorChallenge = (error: unknown): string | null => {
  const response = (
    error as { response?: { status?: number; data?: { detail?: unknown; challenge?: unknown } } }
  )?.response;
  if (response?.status !== 401 || response.data?.detail !== "TOTP_REQUIRED") {
    return null;
  }
  return typeof response.data.challenge === "string" ? response.data.challenge : null;
};

const isNative = Capacitor.isNativePlatform();

/** A sign-in finished here: the route guard lets it through, and signing in
 *  counts as the person's input toward the session it opened. */
const beginSession = () => {
  markJustSignedIn();
  startSessionActivity();
};

/** Delete the long-lived device token an older version of the app kept, unread. */
const forgetLegacyDeviceToken = () => {
  removeItem(CREDENTIAL_KEYS.token);
  removeItem(CREDENTIAL_KEYS.isDeviceToken);
};

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const { t } = useTranslation("auth");
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUserState] = useState<UserRead | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [sessionUnverified, setSessionUnverified] = useState(false);
  const { isOnline } = useNetworkStatus();

  // Keep the React user state and the api-client session flag in lockstep so
  // the 401 interceptor always knows whether to treat a 401 as session expiry
  // (non-null user) or as a not-logged-in visitor (null user).
  // Which answer about the account is the current one.
  //
  // Reading the account is not instant and several reads can be in the air at
  // once — two signals arriving together, a signal beside the catch-up a
  // reconnect does. Responses come back in whatever order the network gives
  // them, so the last to *arrive* is not the last to have been *asked for*.
  //
  // Two separate things decide whether a read may still be applied, and they
  // are separate because conflating them loses data either way:
  //
  // * `readSeqRef` / `appliedReadRef` — reads are numbered as they are made,
  //   and one applies only if no later-numbered read has already landed. That
  //   holds in both orders: a straggler never overwrites a newer answer, and a
  //   newer answer is never thrown away because an older one happened to land
  //   first.
  // * `identityEpochRef` — signing in or out replaces *who* the account is,
  //   which no read of the previous person may undo. Bumped there and nowhere
  //   else, so an ordinary read cannot invalidate another read.
  const readSeqRef = useRef(0);
  const appliedReadRef = useRef(0);
  const identityEpochRef = useRef(0);

  /** A server-confirmed answer about who is here: record it (or unrecord it),
   *  and the session is no longer running on a snapshot. */
  const rememberIdentity = useCallback((nextUser: UserRead | null) => {
    setSessionUnverified(false);
    if (!isOfflineCacheEnabled()) return;
    if (!nextUser) {
      setOfflineWritesAllowed(false);
      clearOfflineSession();
      return;
    }
    // The cache restored at boot belonged to whoever was last signed in here.
    // If the server names somebody else, it does not carry over.
    if (restoredIdentityMismatch(nextUser.id)) {
      queryClient.clear();
      void purgeOfflineCache();
    }
    saveOfflineSession(nextUser, currentServerKey());
    setOfflineWritesAllowed(true);
  }, []);

  const setUser = useCallback(
    (nextUser: UserRead | null) => {
      setUserState(nextUser);
      setHasActiveSession(nextUser !== null);
      rememberIdentity(nextUser);
      if (nextUser) serveAccount(currentServerKey(), nextUser.id);
      // The first screen's list query waits on the saved filters and sort, so
      // ask for them from here rather than from the screen: knowing who is
      // signed in is the only prerequisite, and this is where that happens.
      if (nextUser) prefetchViewPreferences();
    },
    [rememberIdentity]
  );

  /** Apply a re-read of the same person, keeping the object when nothing moved.
   *
   *  The account is re-read whenever the server says it might have changed, and
   *  most of those answers are identical to what is already held. Handing back a
   *  fresh object for one of those re-runs every effect keyed on the user —
   *  including the socket that asked for the re-read — so an answer that says
   *  nothing new has to be indistinguishable from no answer at all. */
  const applyRead = useCallback(
    (nextUser: UserRead) => {
      setUserState((current) =>
        current && JSON.stringify(current) === JSON.stringify(nextUser) ? current : nextUser
      );
      setHasActiveSession(true);
      rememberIdentity(nextUser);
      // Signing in lands here. Before anything reads this device's messages, a
      // store another account left behind is wiped.
      serveAccount(currentServerKey(), nextUser.id);
      // The view-preference map is still fresh from any earlier call, so a
      // re-read costs nothing.
      prefetchViewPreferences();
    },
    [rememberIdentity]
  );

  /** Sign-in / sign-out: a new person, so every read in flight is stale. */
  /** Sign-in / sign-out: a new person, so every read in flight is stale.
   *
   *  `ended` says the session is definitively over — the server refused it, or
   *  the user signed out — as opposed to merely unverifiable. Content the
   *  session was holding goes only in the first case, and the parameter
   *  defaults to the safe answer: a caller that has not thought about it
   *  destroys nothing. */
  const replaceIdentity = useCallback(
    (nextUser: UserRead | null, ended = false) => {
      identityEpochRef.current += 1;
      if (!nextUser && ended) {
        // Whiteboard scenes are file content held on the device, so they
        // end with the session however it ended — not only the tidy way.
        // Deliberately outside the offline cache's platform check: this matters
        // most on the web, where that cache is not enabled at all.
        clearAllWhiteboardSceneCaches();
      }
      setUser(nextUser);
    },
    [setUser]
  );

  // Load the credential on mount for native only (web uses an HttpOnly cookie,
  // so there is nothing here to read).
  //
  // The app keeps its refresh token and nothing else, so a launch begins by
  // renewing. A renewal that fails keeps the token: with no signal it is
  // tried again, and a refused one is cleared when the account read that
  // follows is refused too.
  useEffect(() => {
    if (!isNative) return;
    let cancelled = false;
    forgetLegacyDeviceToken();

    const restore = async () => {
      if (!readRefreshToken()) return;
      // The access token is short-lived and was never written down, so the
      // launch begins by renewing rather than by being turned away once.
      //
      // Through the shared coordinator rather than posting here: a refresh
      // token is spent by its first use, and two requests carrying the same
      // one read as a replay and revoke the chain. Anything else renewing at
      // the same moment — a mount run twice, a request that raced this —
      // joins the attempt already in flight instead of starting a second.
      const renewed = await renewSession();
      if (renewed && !cancelled) setTokenState(renewed);
    };

    void restore().catch((err) => {
      console.error("Failed to load token", err);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshUser = useCallback(async () => {
    readSeqRef.current += 1;
    const readId = readSeqRef.current;
    const epoch = identityEpochRef.current;
    const me = await readMe();
    if (epoch !== identityEpochRef.current) {
      // Somebody signed in or out while this was in flight; it is about a
      // person who is no longer the one here.
      return;
    }
    if (readId <= appliedReadRef.current) {
      // A read made after this one has already landed, so this is the older
      // answer whichever order they arrived in.
      return;
    }
    appliedReadRef.current = readId;
    applyRead(me);
  }, [applyRead]);

  const acceptUser = useCallback(
    (nextUser: UserRead) => {
      readSeqRef.current += 1;
      appliedReadRef.current = readSeqRef.current;
      applyRead(nextUser);
    },
    [applyRead]
  );

  /**
   * Take up a session the server just issued and read the account it belongs
   * to. Every way in ends here: a password, its second factor, a passkey, a
   * code sent to an address, a provider, and a step-up of the session already
   * open.
   *
   * The app keeps the refresh token it is handed and holds none otherwise; a
   * browser's is the HttpOnly cookie the server set. The access token is kept
   * in memory for this session only. A provider's browser sign-in hands back
   * no token at all, since its cookie came with the redirect.
   *
   * `begin` is a sign-in, as opposed to a step-up of a session already open:
   * it starts a new identity epoch, the route guard lets it through and the
   * session's idle window starts.
   */
  const adoptSession = useCallback(
    async (token: Token | null, { begin }: { begin: boolean }) => {
      if (begin) identityEpochRef.current += 1;
      if (token) {
        if (Capacitor.isNativePlatform() && token.refresh_token) {
          storeRefreshToken(token.refresh_token);
        } else {
          clearRefreshToken();
        }
        setAuthToken(token.access_token);
        setTokenState(token.access_token);
      }
      await refreshUser();
      if (begin) beginSession();
    },
    [refreshUser]
  );

  // Bootstrap user on mount — always attempt /me.
  // Web: cookie is sent automatically (withCredentials). Native: token was loaded by the effect above.
  useEffect(() => {
    const bootstrap = async () => {
      setLoading(true);
      try {
        setUser(await readMe());
      } catch (error) {
        // Two different failures used to land here together. An answer of any
        // kind is the server's, and the cleanup below is right for it. Nothing
        // answering only means the account could not be read, which is what
        // used to make offline reading impossible — fall back to the stored
        // snapshot, marked unverified until a request succeeds.
        // Two separate questions, and they have different answers. Whether the
        // server said anything decides which identity we end up with. Whether
        // it refused the session decides if the content it was holding is over
        // — and only a 401 is a refusal. A 500 or a 502 is an answer from a
        // server having a bad time, and losing somebody's unsaved drawing over
        // one would be no better than losing it to a dropped connection.
        const noAnswer = isNoAnswerError(error);
        const snapshot =
          isOfflineCacheEnabled() && noAnswer ? readOfflineSession(currentServerKey()) : null;
        if (snapshot) {
          // Deliberately not through setUser: that would re-save the snapshot
          // and push its expiry out, so an app opened offline every day would
          // never age out.
          setUserState(snapshot);
          setHasActiveSession(true);
          setSessionUnverified(true);
          return;
        }
        replaceIdentity(null, isSessionRejected(error));
        if (isNative) {
          // Clear stale native token
          setTokenState(null);
          clearRefreshToken();
          setAuthToken(null);
        }
      } finally {
        setLoading(false);
      }
    };
    void bootstrap();
  }, [setUser, replaceIdentity]);

  // Re-read the account as soon as the device has signal again, rather than
  // waiting for a screen to ask for it.
  useEffect(() => {
    if (!sessionUnverified || !isOnline) return;
    void refreshUser().catch(() => {
      // Still nothing answering, or the session is gone and the 401 interceptor
      // has already surfaced it. Either way there is nothing to do here.
    });
  }, [sessionUnverified, isOnline, refreshUser]);

  const login = async ({ email, password, deviceName }: LoginPayload) => {
    try {
      const token = await loginAccessToken({
        username: email,
        password,
        grant_type: "password",
        device_name: Capacitor.isNativePlatform() ? deviceName || "Mobile Device" : undefined,
      });
      await adoptSession(token, { begin: true });
    } catch (error) {
      const challenge = secondFactorChallenge(error);
      if (challenge) {
        throw new SecondFactorRequiredError(challenge);
      }
      throw new Error(getErrorMessage(error, "auth:login.defaultError"));
    }
  };

  /**
   * Finish a sign-in that was waiting on the account's second factor.
   *
   * The session it returns is the same one `login` would have produced, so
   * everything after it — storing the credential, loading the user, marking the
   * sign-in — is what that path already does. Native is handed its refresh
   * token in the body and keeps it; the browser reads one from a cookie.
   */
  const completeSecondFactor = async ({ challenge, code, recoveryCode }: SecondFactorPayload) => {
    try {
      const token = await answerSecondFactor({
        challenge,
        code: code ?? null,
        recovery_code: recoveryCode ?? null,
      });
      await adoptSession(token, { begin: true });
    } catch (error) {
      throw new Error(getErrorMessage(error, "auth:login.defaultError"));
    }
  };

  const applyPasskeySignIn = useCallback(
    async (result: PasskeySignInResult) => {
      const accessToken = result.access_token;
      if (!accessToken) {
        throw new Error(t("login.passkeyFailed"));
      }
      await adoptSession({ access_token: accessToken }, { begin: true });
    },
    [adoptSession, t]
  );

  /** Adopt the session a code sent to an address, or a demo link, produced. */
  const applySignIn = useCallback(
    async (token: Token) => {
      await adoptSession(token, { begin: true });
    },
    [adoptSession]
  );

  /**
   * Add the account's second factor to the session already signed in.
   *
   * What `completeSecondFactor` does at the end of a sign-in, this does in the
   * middle of a visit: a community asked for the factor, and the answer goes
   * against the live session rather than a fresh one.
   */
  const stepUpWithFactor = async ({ code, recoveryCode }: StepUpPayload) => {
    const token = await answerStepUpWithFactor({
      code: code ?? null,
      recovery_code: recoveryCode ?? null,
    });
    await adoptSession(token, { begin: false });
  };

  /**
   * The same move, answered with a passkey.
   *
   * The ceremony belongs to the browser, so it lives in `lib/passkeys`; what
   * comes back is the same session the code step-up produces.
   */
  const stepUpWithPasskey = async () => {
    await adoptSession(await presentPasskeyForStepUp(), { begin: false });
  };

  /**
   * The same move, answered with a code sent to one of the account's proved
   * addresses. `challenge` is the handle the send route handed back.
   */
  const stepUpWithEmailCode = async ({ challenge, code }: EmailCodeStepUpPayload) => {
    await adoptSession(await verifyStepUpCode({ challenge, code }), { begin: false });
  };

  const register = async ({ inviteCode, ...body }: RegisterPayload) => {
    const made = await registerUser(body, inviteCode ? { invite_code: inviteCode } : undefined);
    // The first account changes the server's answer to "has anyone signed up",
    // which decides whether /login shows first-run registration. The next visit
    // asks again; the page on screen keeps its card and what it says.
    void queryClient.invalidateQueries({
      queryKey: getBootstrapStatusQueryKey(),
      refetchType: "none",
    });
    return made;
  };

  // Memoized: the OIDC callback page calls this from an effect, and this
  // function also sets the user it depends on. An unstable identity would make
  // that effect re-run on every render it causes — an endless /me loop.
  const completeOidcLogin = useCallback(
    async (credential?: NativeSession) => {
      await adoptSession(
        credential
          ? { access_token: credential.accessToken, refresh_token: credential.refreshToken }
          : null,
        { begin: true }
      );
    },
    [adoptSession]
  );

  /** Everything sign-out does on this device, and nothing that leaves it. */
  const clearLocalSession = useCallback(() => {
    replaceIdentity(null, true);
    setTokenState(null);
    setAuthToken(null);
    clearUploadToken();
    forgetLegacyDeviceToken();
    clearRefreshToken();
    forgetSessionActivity();
    queryClient.clear();
    // replaceIdentity already dropped the session snapshot; the cache that went
    // with it goes at the same time.
    clearOfflineSession();
    void purgeOfflineCache();
  }, [replaceIdentity]);

  /** The session this device was holding is over, and nothing here asked for
   *  that.
   *
   *  Distinct from `logout()`, which ends the same session deliberately and
   *  tells the server so. Both are scoped to this device; this one has nothing
   *  to tell the server, because the session is already gone.
   *
   *  The phone and desktop apps keep their messages: it is the same device when
   *  its owner signs back in, and the key store is still registered to them. A
   *  browser may be a shared computer, so its messages go with the session. */
  const endSessionLocally = useCallback(async () => {
    setHasActiveSession(false);
    clearJustSignedIn();
    if (!Capacitor.isNativePlatform()) {
      try {
        await forgetMessagesOnThisDevice();
      } catch {
        // The session is over either way.
      }
    }
    clearLocalSession();
  }, [clearLocalSession]);

  const logout = useCallback(async () => {
    // Fire the POST *first*, while the bearer token and cookie are still
    // in place — otherwise we may log out on the client without the
    // backend ever seeing the request, and the cached JWT/cookie can
    // keep authenticating subsequent requests until it expires naturally.
    //
    // Clear hasActiveSession before the POST so the interceptor ignores
    // any 401 that comes back from /auth/logout itself (can happen when
    // the cookie is already expired), preventing re-entry into this
    // same handler.
    setHasActiveSession(false);
    clearJustSignedIn();
    // A browser may be a shared computer, so its messages go before the session
    // does: a decrypted conversation must not outlive it, and withdrawing its
    // device needs the token. The phone and desktop apps keep theirs, as through
    // a lapse, so signing back in reads them straight away.
    if (!Capacitor.isNativePlatform()) {
      try {
        await forgetMessagesOnThisDevice();
      } catch {
        // Never a reason to stay signed in.
      }
    }
    try {
      // The same for this device's notifications: withdrawn while the
      // credential still works.
      await forgetPushOnThisDevice();
    } catch {
      // Never a reason to stay signed in.
    }
    try {
      // Which session is ending. A browser's refresh token is a cookie it
      // cannot read and the request carries it anyway; a native client keeps
      // its own in storage, so it names it here.
      const refreshToken = readRefreshToken();
      await endServerSession(refreshToken ? { refresh_token: refreshToken } : {});
    } catch {
      // Ignore errors — proceed with local cleanup regardless.
    }
    clearLocalSession();
  }, [clearLocalSession]);

  // While somebody is signed in, their input is what keeps the session alive.
  const signedIn = user !== null;
  useEffect(() => (signedIn ? watchForActivity() : undefined), [signedIn]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }
    const handleUnauthorized = () => {
      // The api-client session flag means this only fires for users who
      // were actually signed in, so it's safe to surface the toast here
      // without further checks.
      toast.error(t("session.expired"));
      void endSessionLocally();
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [endSessionLocally, t]);

  // Suspended while signed in: re-reading the account is what turns the app
  // over to the time-out screen.
  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }
    const handleSuspended = () => {
      void refreshUser();
    };
    window.addEventListener(AUTH_ACCOUNT_SUSPENDED_EVENT, handleSuspended);
    return () => window.removeEventListener(AUTH_ACCOUNT_SUSPENDED_EVENT, handleSuspended);
  }, [refreshUser]);

  const value: AuthContextValue = {
    user,
    token,
    loading,
    sessionUnverified,
    login,
    completeSecondFactor,
    applyPasskeySignIn,
    applySignIn,
    stepUpWithFactor,
    stepUpWithPasskey,
    stepUpWithEmailCode,
    register,
    completeOidcLogin,
    logout,
    refreshUser,
    acceptUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

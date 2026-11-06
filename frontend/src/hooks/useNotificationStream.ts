import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import { getAuthToken } from "@/api/client";
import { invalidate, q } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { refreshNotifications } from "@/hooks/useNotifications";
import { refreshFiledTickets } from "@/hooks/useTickets";
import { type AlertFrame, receiveAlert } from "@/lib/desktopAlerts";
import { openLiveSocket } from "@/lib/liveSocket";
import { buildApiWsUrl } from "@/lib/wsUrl";

// "Somebody just did something here" (the backend's MSG_ACTIVE). One byte, no
// payload: the socket already knows whose it is.
const MSG_ACTIVE = 6;

// How often that byte may go out, however busy the keyboard is. The server
// only needs to know the person was around within its idle window, so once a
// minute answers that with a frame nobody would notice.
const ACTIVITY_INTERVAL_MS = 60_000;

// What counts as a sign of someone. Pointer, key and scroll cover being at the
// machine; a tab coming back to the front covers returning to it.
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

// A frame is the only prompt to re-read the account, so a re-read that fails
// has to keep trying: there is no poll behind it any more, and the next frame
// may never come for this account. What is bounded is the *rate*, not the
// number of attempts — giving up would leave the tab holding an account it
// already knows is wrong, which is the thing this whole channel exists to
// prevent. Backs off to a slow beat and stays there until one lands.
const ACCOUNT_RETRY_DELAYS_MS = [2000, 8000, 30_000, 60_000] as const;
const ACCOUNT_RETRY_MAX_DELAY_MS = 300_000;

// ── Connection state, shared with whoever renders the bell ──────────────────
// The socket is mounted once at the app shell, but the component that decides
// whether to poll is the bell, several levels down. A module-level store read
// through `useSyncExternalStore` keeps that one boolean available to both
// without threading a provider through the tree.

let connected = false;
const listeners = new Set<() => void>();

const setConnected = (next: boolean) => {
  if (connected === next) {
    return;
  }
  connected = next;
  for (const listener of listeners) {
    listener();
  }
};

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/**
 * Whether the notification push channel is currently open.
 *
 * Consumers use this to decide whether they still need to poll: a socket that
 * never connects (a proxy that drops upgrades, a browser offline) must not
 * mean notifications stop arriving altogether.
 */
export const useNotificationStreamConnected = (): boolean =>
  useSyncExternalStore(
    subscribe,
    () => connected,
    () => false
  );

/**
 * Subscribe to the signed-in user's notification channel.
 *
 * The inbox is personal and cross-community, so this socket is addressed by
 * nothing but the credential — unlike `useRealtimeUpdates`, whose socket is
 * per-community and only exists inside a `/c/{communityId}` route. It therefore stays
 * open on personal routes too, which is exactly where the bell still lives.
 *
 * Every frame is a content-free "your inbox changed"; the response is to
 * invalidate the notification queries and let React Query refetch through the
 * normal REST path, which is the authorization gate.
 *
 * It carries one thing the other way: a throttled byte saying its person is at
 * the keyboard. That is what keeps them from reading as idle — and going quiet
 * is the whole signal, so a tab left open needs to send nothing for the server
 * to work out that nobody is at it.
 *
 * Mount once, at the authenticated app shell.
 */
export const useNotificationStream = () => {
  const { user, refreshUser } = useAuth();
  // The socket belongs to a person, not to a particular reading of them. Every
  // account re-read hands back a fresh object, and this socket asks for one on
  // every connect — so keying the connection on the object would have it tear
  // itself down and rebuild in a loop, each rebuild asking for the re-read that
  // ends it. Who they are is the id.
  const userId = user?.id ?? null;
  // Held in a ref so a new `refreshUser` identity does not tear the socket
  // down and rebuild it: the handler wants the current one, not the one that
  // existed when we connected.
  const refreshUserRef = useRef(refreshUser);
  refreshUserRef.current = refreshUser;
  const accountRetryTimerRef = useRef<number | null>(null);

  // Re-read the account, and keep trying for a short while if it does not
  // land. One in-flight attempt at a time: a second frame arriving mid-retry
  // restarts the sequence rather than racing it.
  const refreshAccount = useCallback((attempt = 0) => {
    if (accountRetryTimerRef.current !== null) {
      window.clearTimeout(accountRetryTimerRef.current);
      accountRetryTimerRef.current = null;
    }
    // Wrapped rather than chained straight off the call: the guard covers a
    // missing function, not a return that is not a promise.
    void Promise.resolve(refreshUserRef.current?.()).catch(() => {
      // Past the end of the ramp it stays at the slowest beat rather than
      // stopping: the account is known to be out of date, and nothing else is
      // coming to correct it.
      const delay = ACCOUNT_RETRY_DELAYS_MS[attempt] ?? ACCOUNT_RETRY_MAX_DELAY_MS;
      accountRetryTimerRef.current = window.setTimeout(() => {
        accountRetryTimerRef.current = null;
        refreshAccount(attempt + 1);
      }, delay);
    });
  }, []);

  // Who may reach this account, and who it has agreed something with. One
  // frame moves all three lists, because they change together: accepting a
  // connection opens a channel, and leaving a community closes one.
  const refreshConnections = useCallback(() => {
    void invalidate(q.contactGrants(), q.ignoredAccounts(), q.dmSettings());
  }, []);

  // Everything this socket follows, re-read at once. Used where the gap is
  // real but its contents are not knowable: our own reconnect, and the
  // server's.
  const resync = useCallback(() => {
    void invalidate(q.notifications());
    refreshAccount();
    refreshConnections();
    void invalidate(q.directMessages());
    void refreshFiledTickets();
  }, [refreshAccount, refreshConnections]);

  useEffect(
    () => () => {
      if (accountRetryTimerRef.current !== null) {
        window.clearTimeout(accountRetryTimerRef.current);
        accountRetryTimerRef.current = null;
      }
    },
    []
  );

  useEffect(() => {
    if (userId === null) {
      return;
    }

    const connection = openLiveSocket({
      url: buildApiWsUrl("notifications/stream"),
      // The inbox is addressed by nothing but the credential, read when the
      // frame is written rather than captured — it renews on its own clock
      // while the socket stays open. Empty is fine: the server reads the
      // session cookie, which is the web path after a reload.
      auth: () => ({ token: getAuthToken() }),
      onStatus: (up) => {
        setConnected(up);
        if (up) {
          // The socket was down for some interval — anything that happened in
          // it was never signalled, so catch up once on the way back up.
          resync();
        }
      },
      onFrame: (payload) => {
        const frame = payload as { resource?: string; action?: string } & AlertFrame;
        // Several channels over one socket. A frame carries nothing but which
        // one it is; what it means is a refetch, and the refetch is where
        // anything is actually decided.
        // The server's heartbeat names no channel, so it falls through: its
        // whole content is that it arrived.
        if (frame.resource === "resync") {
          // The server's own bus was down for a while, so frames went past
          // with nobody listening for them. It cannot say which, so this says
          // the same thing a reconnect does: read everything again.
          resync();
        } else if (frame.resource === "notification") {
          void refreshNotifications(frame.action);
        } else if (frame.resource === "alert") {
          // The desktop app's system notifications; nothing else reads them.
          receiveAlert(frame);
        } else if (frame.resource === "account") {
          refreshAccount();
        } else if (frame.resource === "connections") {
          refreshConnections();
        } else if (frame.resource === "tickets") {
          // One of the tickets this person filed moved: the team answered, or
          // its state changed. The open ticket page reads it again.
          void refreshFiledTickets();
        } else if (frame.resource === "dm") {
          // A direct-message frame says only that there is something to
          // collect. The page that owns the mailbox does the reading.
          void invalidate(q.directMessages());
        }
      },
    });

    // Throttled at the source rather than on a timer: no frame goes out for a
    // tab nobody is touching, which is exactly the state being reported.
    let lastReported = 0;
    const reportActivity = () => {
      const now = Date.now();
      if (now - lastReported < ACTIVITY_INTERVAL_MS) {
        return;
      }
      lastReported = now;
      connection.send(new Uint8Array([MSG_ACTIVE]));
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        // Coming back to the tab is being back, whenever the last click was.
        lastReported = 0;
        reportActivity();
      }
    };
    for (const name of ACTIVITY_EVENTS) {
      window.addEventListener(name, reportActivity, { passive: true });
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      for (const name of ACTIVITY_EVENTS) {
        window.removeEventListener(name, reportActivity);
      }
      document.removeEventListener("visibilitychange", onVisibilityChange);
      setConnected(false);
      connection.close();
    };
  }, [userId, resync, refreshAccount, refreshConnections]);
};

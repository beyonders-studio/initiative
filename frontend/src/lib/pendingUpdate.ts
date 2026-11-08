import { useSyncExternalStore } from "react";

/**
 * How the app takes an update it is waiting on: reloading the page (the web
 * app, or a downloaded bundle in the phone and desktop apps), restarting into
 * a desktop app it has already downloaded, or installing a new app, which the
 * dialog that explains it walks through.
 */
export type UpdateAction = "reload" | "restart" | "install";

export interface PendingUpdate {
  action: UpdateAction;
  run: () => void;
}

// Kept outside React: the update is found where the app checks for one, and
// the Update button is drawn in the sidebar or the desktop title bar.
let pending: PendingUpdate | null = null;
const listeners = new Set<() => void>();

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/**
 * Offer an update until it is taken. The prompt that announces one can be
 * closed; this stays, and taking it reloads or restarts the app, which ends it.
 */
export const setPendingUpdate = (update: PendingUpdate | null) => {
  pending = update;
  for (const listener of listeners) listener();
};

/** The update the app is waiting on, or null while it is up to date. */
export const usePendingUpdate = () =>
  useSyncExternalStore(
    subscribe,
    () => pending,
    () => null
  );

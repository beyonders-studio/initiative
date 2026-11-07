/**
 * A single, app-wide clock that relative-time labels ("2 minutes ago") subscribe
 * to so they refresh in place without a page reload.
 *
 * Why one shared clock instead of a timer per label: a table can render dozens of
 * relative timestamps, and one `setInterval` per cell would mean dozens of wakeups
 * firing at staggered moments. Here every subscriber is driven by the same tick,
 * so updates batch into a single render pass and the interval only runs while at
 * least one label is mounted.
 *
 * Re-render suppression is the caller's job: `getClockNow()` only advances on a
 * tick, so a `useSyncExternalStore` snapshot derived from it stays referentially
 * stable between ticks, and React skips re-rendering any label whose formatted
 * string did not actually change (see `useRelativeTime`).
 */

type Listener = () => void;

const listeners = new Set<Listener>();

let intervalId: ReturnType<typeof setInterval> | null = null;

/**
 * Cached "now" shared by every subscriber. Only advances on a tick so snapshots
 * stay stable between ticks (required for `useSyncExternalStore` to bail out of
 * re-rendering unchanged labels).
 */
let now = Date.now();

/**
 * 30s keeps minute-granularity labels ("2 minutes ago") within half a minute of
 * accurate while keeping wakeups cheap. Coarser labels ("3 hours ago", "2 days
 * ago") never re-render on most ticks because their formatted string is
 * unchanged — the tick still fires, but React bails out.
 */
export const CLOCK_TICK_MS = 30_000;

const notify = (): void => {
  now = Date.now();
  for (const listener of listeners) {
    listener();
  }
};

const handleVisibilityChange = (): void => {
  // A backgrounded tab throttles (or pauses) `setInterval`, so labels can be
  // badly stale by the time it returns to the foreground. Tick immediately on
  // becoming visible so they snap to the current time.
  if (typeof document !== "undefined" && document.visibilityState === "visible") {
    notify();
  }
};

const start = (): void => {
  if (intervalId !== null) {
    return;
  }
  now = Date.now();
  intervalId = setInterval(notify, CLOCK_TICK_MS);
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", handleVisibilityChange);
  }
};

const stop = (): void => {
  if (intervalId === null) {
    return;
  }
  clearInterval(intervalId);
  intervalId = null;
  if (typeof document !== "undefined") {
    document.removeEventListener("visibilitychange", handleVisibilityChange);
  }
};

/**
 * The shared "now", in epoch milliseconds. Stable between ticks so callers can
 * derive a referentially-stable snapshot from it.
 */
export const getClockNow = (): number => now;

/**
 * Subscribe to the shared clock. Returns an unsubscribe function. The interval
 * runs only while at least one subscriber is registered. Shaped for direct use
 * as the `subscribe` argument of `useSyncExternalStore`.
 */
export const subscribeToClock = (listener: Listener): (() => void) => {
  listeners.add(listener);
  start();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      stop();
    }
  };
};

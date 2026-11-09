import { Capacitor } from "@capacitor/core";
import { Preferences } from "@capacitor/preferences";

const isNative = () => Capacitor.isNativePlatform();
const hasLocalStorage = typeof localStorage !== "undefined";

/**
 * Keys whose values let this device act as its account. On native they are kept
 * in their own Preferences group, which the app's Android backup rules leave out
 * (`android/app/src/main/res/xml/`), so a phone restored from a backup keeps its
 * settings and server address and signs in again.
 */
export const CREDENTIAL_KEYS = {
  refreshToken: "initiative-refresh-token",
  offlineSession: "initiative-offline-session",
  pendingSignIn: "initiative-pending-sign-in",
} as const;

const DEFAULT_GROUP = "CapacitorStorage";
const CREDENTIALS_GROUP = "InitiativeCredentials";
const credentialKeys = new Set<string>(Object.values(CREDENTIAL_KEYS));
const groupOf = (key: string) => (credentialKeys.has(key) ? CREDENTIALS_GROUP : DEFAULT_GROUP);

// The Preferences group is set for every call that follows, so calls run one
// at a time, each in the group its key belongs to.
let queue: Promise<unknown> = Promise.resolve();
const inGroup = <T>(group: string, operation: () => Promise<T>): Promise<T> => {
  const run = queue.then(async () => {
    await Preferences.configure({ group });
    return operation();
  });
  queue = run.catch(() => undefined);
  return run;
};

const readGroup = (group: string) =>
  inGroup(group, async () => {
    const { keys } = await Preferences.keys();
    return Promise.all(
      (Array.isArray(keys) ? keys : []).map(async (key) => {
        const { value } = await Preferences.get({ key });
        return [key, value] as const;
      })
    );
  });

/**
 * In-memory cache used on native platforms. Hydrated once at startup from
 * Capacitor Preferences so that all subsequent reads are synchronous.
 */
const cache = new Map<string, string>();

/**
 * Call once before React renders. On web this is a no-op (resolves instantly).
 * On native it loads every persisted key into the in-memory cache so that
 * getItem() can remain synchronous.
 */
export async function initStorage(): Promise<void> {
  if (!isNative()) {
    return;
  }
  const defaults = await readGroup(DEFAULT_GROUP);
  const credentials = await readGroup(CREDENTIALS_GROUP);
  for (const [key, value] of [...defaults, ...credentials]) {
    if (value !== null) cache.set(key, value);
  }
}

export function getItem(key: string): string | null {
  if (!isNative()) {
    return hasLocalStorage ? localStorage.getItem(key) : null;
  }
  return cache.get(key) ?? null;
}

/**
 * Reads see the value at once. On native the durable write finishes later;
 * await the result where the app may be closed before it does.
 */
export function setItem(key: string, value: string): Promise<void> {
  if (!isNative()) {
    if (hasLocalStorage) localStorage.setItem(key, value);
    return Promise.resolve();
  }
  cache.set(key, value);
  return inGroup(groupOf(key), () => Preferences.set({ key, value }));
}

/**
 * Mirror a value into the WebView's own localStorage as well, for the one
 * reader that runs before any of this module exists: the pre-paint script in
 * index.html. On web, `setItem` already lands there. On native the durable
 * copy is in Preferences and this is only a hint — the OS may clear it, and
 * the script falls back to the system theme when it is gone.
 */
export function setFirstPaintHint(key: string, value: string): void {
  if (!isNative() || !hasLocalStorage) return;
  try {
    localStorage.setItem(key, value);
  } catch {
    // A hint only: the first frame falls back to the system theme.
  }
}

export function removeItem(key: string): Promise<void> {
  if (!isNative()) {
    if (hasLocalStorage) localStorage.removeItem(key);
    return Promise.resolve();
  }
  cache.delete(key);
  return inGroup(groupOf(key), () => Preferences.remove({ key }));
}

/**
 * Values for the life of this tab, or of the app process on native: gone when
 * it closes, on every platform, so they stay in the WebView's sessionStorage.
 */
export function getSessionItem(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function setSessionItem(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // Storage unavailable; the value is simply not kept.
  }
}

/** Enumerate every stored key. */
export function listKeys(): string[] {
  if (!isNative()) {
    if (!hasLocalStorage) return [];
    return Object.keys(localStorage);
  }
  return Array.from(cache.keys());
}

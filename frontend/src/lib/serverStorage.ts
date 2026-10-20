import { CREDENTIAL_KEYS, getItem, removeItem, setItem } from "@/lib/storage";

const SERVER_URL_KEY = "initiative-server-url";
// The self-hosted address as the person typed it. Kept through disconnecting,
// so their server is already filled in when they come back to it.
const SELF_HOSTED_ADDRESS_KEY = "initiative-self-hosted-address";

/** Initiative Cloud, the server the app signs in to until it is given another. */
export const CLOUD_SERVER_URL = "https://initiativetasks.com/api/v1";
export const CLOUD_ORIGIN = new URL(CLOUD_SERVER_URL).origin;

// Server URL storage
export function getStoredServerUrl(): string | null {
  return getItem(SERVER_URL_KEY);
}

/**
 * The server the app talks to: the one it was given, or Initiative Cloud on a
 * fresh install. Kept, so everything keyed on the stored server agrees.
 */
export function adoptStoredServerUrl(): string {
  const stored = getStoredServerUrl();
  if (stored) return stored;
  setStoredServerUrl(CLOUD_SERVER_URL);
  return CLOUD_SERVER_URL;
}

export function setStoredServerUrl(url: string): void {
  setItem(SERVER_URL_KEY, url);
}

export function getSelfHostedAddress(): string | null {
  return getItem(SELF_HOSTED_ADDRESS_KEY);
}

export function setSelfHostedAddress(address: string): void {
  setItem(SELF_HOSTED_ADDRESS_KEY, address);
}

export function clearStoredServerUrl(): void {
  removeItem(SERVER_URL_KEY);
}

export function clearStoredToken(): void {
  removeItem(CREDENTIAL_KEYS.token);
}

// Clear all app data (for disconnect/logout)
export function clearAllStorage(): void {
  clearStoredServerUrl();
  clearStoredToken();
}

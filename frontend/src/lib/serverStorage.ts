import { CLOUD_OPEN, CLOUD_SERVER_URL } from "@/lib/cloud";
import { getItem, removeItem, setItem } from "@/lib/storage";

const SERVER_URL_KEY = "initiative-server-url";
// The self-hosted address as the person typed it. Kept through disconnecting,
// so their server is already filled in when they come back to it.
const SELF_HOSTED_ADDRESS_KEY = "initiative-self-hosted-address";

// Server URL storage
export function getStoredServerUrl(): string | null {
  return getItem(SERVER_URL_KEY);
}

/**
 * The server the app talks to: the one it was given, or, on a fresh install,
 * Initiative Cloud once it is open. Kept, so everything keyed on the stored
 * server agrees.
 */
export function adoptStoredServerUrl(): string | null {
  const stored = getStoredServerUrl();
  if (stored || !CLOUD_OPEN) return stored;
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

// Clear all app data (for disconnect/logout)
export function clearAllStorage(): void {
  clearStoredServerUrl();
}

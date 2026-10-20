import { Capacitor } from "@capacitor/core";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

import { setApiBaseUrl } from "@/api/client";
import { releasePushForServerSwitch } from "@/lib/pushRegistration";
import { queryClient } from "@/lib/queryClient";
import {
  adoptStoredServerUrl,
  CLOUD_SERVER_URL,
  clearAllStorage,
  setStoredServerUrl,
} from "@/lib/serverStorage";

interface ServerContextValue {
  /** The configured server URL (e.g., "https://myserver.com/api/v1") */
  serverUrl: string | null;
  /** Whether running on native platform (iOS/Android) */
  isNativePlatform: boolean;
  /** Whether a server URL is configured (always true on web) */
  isServerConfigured: boolean;
  /** Whether the provider is still loading */
  loading: boolean;
  /** Configure the server URL after validating it */
  setServerUrl: (url: string) => Promise<void>;
  /** Clear the server URL (disconnect from server) */
  clearServerUrl: () => Promise<void>;
  /** Test if a server URL is valid and reachable */
  testServerConnection: (url: string) => Promise<{ valid: boolean; error?: string }>;
  /** Get display-friendly hostname from server URL */
  getServerHostname: () => string | null;
  /**
   * The server's origin (scheme + host, no path) for building absolute links
   * to non-API routes. On web that's the app's own origin; on native it's
   * derived from the configured server URL. Null on native before a server is
   * configured.
   */
  getServerOrigin: () => string | null;
}

/** How long a server has to answer the connection check before it counts as unreachable. */
const CONNECTION_TIMEOUT_MS = 10_000;

export const ServerContext = createContext<ServerContextValue | undefined>(undefined);

/**
 * Normalize a server URL to include /api/v1 suffix
 */
export function normalizeServerUrl(url: string): string {
  let normalized = url.trim();

  // Add https:// if no protocol
  if (!normalized.startsWith("http://") && !normalized.startsWith("https://")) {
    normalized = "https://" + normalized;
  }

  // Remove trailing slashes
  normalized = normalized.replace(/\/+$/, "");

  // Remove /api/v1 if present (we'll add it back)
  normalized = normalized.replace(/\/api\/v1\/?$/, "");
  normalized = normalized.replace(/\/api\/?$/, "");

  // Add /api/v1
  normalized = normalized + "/api/v1";

  return normalized;
}

/**
 * Extract hostname from server URL for display
 */
function extractHostname(serverUrl: string): string | null {
  try {
    const url = new URL(serverUrl);
    return url.hostname;
  } catch {
    return null;
  }
}

/**
 * The origin (scheme + host) of a server URL, dropping its `/api/v1` path.
 * `URL.origin` handles any path shape, unlike a suffix match on `/api/v1`.
 */
function extractOrigin(serverUrl: string): string | null {
  try {
    return new URL(serverUrl).origin;
  } catch {
    return null;
  }
}

export const ServerProvider = ({ children }: { children: ReactNode }) => {
  const [serverUrl, setServerUrlState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const isNativePlatform = Capacitor.isNativePlatform();

  // On web, server is always "configured" (uses relative URLs)
  // On native, we need an explicit server URL
  const isServerConfigured = !isNativePlatform || serverUrl !== null;

  // Load stored server URL on mount
  useEffect(() => {
    if (!isNativePlatform) {
      setLoading(false);
      return;
    }

    const stored = adoptStoredServerUrl();
    setServerUrlState(stored);
    setApiBaseUrl(stored);
    setLoading(false);
  }, [isNativePlatform]);

  const testServerConnection = useCallback(
    async (url: string): Promise<{ valid: boolean; error?: string }> => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), CONNECTION_TIMEOUT_MS);
      try {
        const normalizedUrl = normalizeServerUrl(url);

        // Test connectivity by fetching version endpoint
        const response = await fetch(`${normalizedUrl}/version`, {
          method: "GET",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });

        if (!response.ok) {
          return { valid: false, error: `Server returned status ${response.status}` };
        }

        const data = await response.json();

        // Verify it's an Initiative server by checking response shape
        if (!data.version) {
          return { valid: false, error: "Not a valid Initiative server" };
        }

        return { valid: true };
      } catch (err) {
        console.error("Server connection test failed", err);
        if (err instanceof TypeError && err.message.includes("fetch")) {
          return { valid: false, error: "Could not connect to server" };
        }
        return { valid: false, error: "Connection failed" };
      } finally {
        clearTimeout(timer);
      }
    },
    []
  );

  const setServerUrl = useCallback(async (url: string): Promise<void> => {
    const normalizedUrl = normalizeServerUrl(url);
    // This device's push handle is the previous server's; the relay is told
    // to drop it before anything is sent to the next one.
    await releasePushForServerSwitch(normalizedUrl).catch(() => undefined);
    setStoredServerUrl(normalizedUrl);
    setApiBaseUrl(normalizedUrl);
    // Nothing the previous server said holds for this one.
    queryClient.clear();
    setServerUrlState(normalizedUrl);
  }, []);

  const clearServerUrl = useCallback(async (): Promise<void> => {
    await releasePushForServerSwitch(null).catch(() => undefined);
    // Disconnecting goes back to where a fresh install starts.
    clearAllStorage();
    setStoredServerUrl(CLOUD_SERVER_URL);
    setApiBaseUrl(CLOUD_SERVER_URL);
    queryClient.clear();
    setServerUrlState(CLOUD_SERVER_URL);
  }, []);

  const getServerHostname = useCallback((): string | null => {
    if (!serverUrl) return null;
    return extractHostname(serverUrl);
  }, [serverUrl]);

  const getServerOrigin = useCallback((): string | null => {
    if (!isNativePlatform) return window.location.origin;
    return serverUrl ? extractOrigin(serverUrl) : null;
  }, [isNativePlatform, serverUrl]);

  const value: ServerContextValue = {
    serverUrl,
    isNativePlatform,
    isServerConfigured,
    loading,
    setServerUrl,
    clearServerUrl,
    testServerConnection,
    getServerHostname,
    getServerOrigin,
  };

  return <ServerContext.Provider value={value}>{children}</ServerContext.Provider>;
};

export const useServer = () => {
  const context = useContext(ServerContext);
  if (!context) {
    throw new Error("useServer must be used within a ServerProvider");
  }
  return context;
};

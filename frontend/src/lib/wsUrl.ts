import { API_BASE_URL } from "@/api/client";

/**
 * Build the absolute http(s) URL for an API endpoint from the API base (which
 * may be relative in dev, where Vite proxies it). `subpath` is relative to the
 * API root, e.g. `notifications/stream`.
 */
export const buildApiUrl = (subpath: string): URL => {
  const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
  const url = isAbsolute ? new URL(API_BASE_URL) : new URL(API_BASE_URL, window.location.origin);
  const normalizedPath = url.pathname.endsWith("/")
    ? url.pathname.slice(0, -1)
    : url.pathname || "/api/v1";
  url.pathname = `${normalizedPath}/${subpath}`;
  url.search = "";
  url.hash = "";
  return url;
};

/** {@link buildApiUrl}, as the ws/wss URL of an API WebSocket endpoint. */
export const buildApiWsUrl = (subpath: string): string => {
  const url = buildApiUrl(subpath);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
};

/**
 * Build the ws/wss URL for a community-scoped WebSocket endpoint. `subpath` is
 * relative to the community root, e.g. `projects/5/ws`.
 */
export const buildCommunityWsUrl = (communityId: number, subpath: string): string =>
  buildApiWsUrl(`c/${communityId}/${subpath}`);

import { Capacitor } from "@capacitor/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";

import { getUploadToken } from "./uploadToken";
import {
  resolveArtworkUrl,
  resolveFileDownloadUrl,
  resolveFileVersionDownloadUrl,
  resolveUploadUrl,
} from "./uploadUrl";

// Mock the scoped-token module so we can assert uploadUrl stamps the SHORT-LIVED
// upload token (never the long-lived session JWT) into native media URLs.
vi.mock("./uploadToken", () => ({
  getUploadToken: vi.fn(() => null),
}));

const getUploadTokenMock = vi.mocked(getUploadToken);

// Capacitor.isNativePlatform() is globally mocked to `false` in test setup,
// so the default-path tests cover the web (same-origin, cookie-auth) flow.

describe("resolveFileVersionDownloadUrl", () => {
  it("builds the community-scoped version download path, apart from the current file's", () => {
    expect(resolveFileVersionDownloadUrl(5, 3, 7)).toBe("/api/v1/c/7/files/5/versions/3/download");
    expect(resolveFileVersionDownloadUrl(5, 3, 7, true)).toBe(
      "/api/v1/c/7/files/5/versions/3/download?inline=1"
    );
    expect(resolveFileVersionDownloadUrl(5, 3, 7)).not.toBe(resolveFileDownloadUrl(5, 7));
    // Nothing when an id is missing.
    expect(resolveFileVersionDownloadUrl(0, 3, 7)).toBeNull();
    expect(resolveFileVersionDownloadUrl(5, 0, 7)).toBeNull();
    expect(resolveFileVersionDownloadUrl(5, 3, 0)).toBeNull();
  });
});

describe("resolveUploadUrl (web)", () => {
  it("returns a same-origin /uploads/ path or a data URI unchanged, with no token", () => {
    // Web flow: HttpOnly cookie authenticates the <img> load — no ?token=.
    expect(resolveUploadUrl("/uploads/avatars/abc.png")).toBe("/uploads/avatars/abc.png");
    expect(resolveUploadUrl("data:image/png;base64,AAAA")).toBe("data:image/png;base64,AAAA");
  });
});

describe("resolveUploadUrl (native)", () => {
  afterEach(() => {
    getUploadTokenMock.mockReset();
    getUploadTokenMock.mockReturnValue(null);
  });

  it("stamps the SHORT-LIVED scoped upload token (not the session JWT) into the URL", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue("http://10.0.2.2:8000/api/v1");
    getUploadTokenMock.mockReturnValue("scoped-upload-token");

    const url = resolveUploadUrl("/uploads/avatars/abc.png");

    expect(url).toBe("http://10.0.2.2:8000/uploads/avatars/abc.png?token=scoped-upload-token");

    // And omits it when none is available yet.
    getUploadTokenMock.mockReturnValue(null);
    expect(resolveUploadUrl("/uploads/avatars/abc.png")).toBe(
      "http://10.0.2.2:8000/uploads/avatars/abc.png"
    );
  });

  it("keeps the server's path prefix on native", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue(
      "https://example.test/initiative/api/v1"
    );
    getUploadTokenMock.mockReturnValue(null);

    expect(resolveUploadUrl("/uploads/avatars/abc.png")).toBe(
      "https://example.test/initiative/uploads/avatars/abc.png"
    );
  });
});

describe("resolveArtworkUrl", () => {
  it("leaves catalog artwork paths alone on web", () => {
    expect(resolveArtworkUrl("/marketplace/core-guild-calendar.svg")).toBe(
      "/marketplace/core-guild-calendar.svg"
    );
    expect(resolveArtworkUrl("/api/v1/marketplace/media/abc123")).toBe(
      "/api/v1/marketplace/media/abc123"
    );
  });

  it("keeps bundled artwork bundle-relative on native, and addresses mirrored artwork at the API", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue("http://10.0.2.2:8000/api/v1");
    getUploadTokenMock.mockReturnValue("scoped-upload-token");

    // Shipped with the web bundle: the native app already holds the file, so
    // sending the request to the API origin would be a needless round trip.
    expect(resolveArtworkUrl("/marketplace/core-guild-calendar.svg")).toBe(
      "/marketplace/core-guild-calendar.svg"
    );
    expect(resolveArtworkUrl("/icons/logo.svg")).toBe("/icons/logo.svg");
    // Served only by the API: bundle-relative it resolves inside the app's own
    // origin and the image breaks. The media route is public, so no token.
    expect(resolveArtworkUrl("/api/v1/marketplace/media/abc123")).toBe(
      "http://10.0.2.2:8000/api/v1/marketplace/media/abc123"
    );
  });

  it("keeps the server's path prefix on native", () => {
    // A server reached at https://host/initiative serves its API — and its
    // mirrored artwork — under that prefix too, so the prefix has to survive.
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue(
      "https://example.test/initiative/api/v1"
    );

    expect(resolveArtworkUrl("/api/v1/marketplace/media/abc123")).toBe(
      "https://example.test/initiative/api/v1/marketplace/media/abc123"
    );
  });

  it("passes absolute URLs and data URIs through, and null for nothing", () => {
    expect(resolveArtworkUrl("https://cdn.example.test/icon.svg")).toBe(
      "https://cdn.example.test/icon.svg"
    );
    expect(resolveArtworkUrl("data:image/png;base64,AAAA")).toBe("data:image/png;base64,AAAA");
    expect(resolveArtworkUrl(null)).toBeNull();
    expect(resolveArtworkUrl(undefined)).toBeNull();
    expect(resolveArtworkUrl("")).toBeNull();
  });
});

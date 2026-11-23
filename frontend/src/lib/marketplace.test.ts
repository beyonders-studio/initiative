import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ListingKind, ListingSource } from "@/api/generated/initiativeAPI.schemas";
import { darkVariant } from "@/lib/releaseImages";

import {
  COMMUNITY_SHELVES,
  DEFAULT_COMMUNITY_SHELF,
  listingImageUrl,
  minimumAgeFor,
  parseCommunityShelf,
  parseListingKind,
} from "./marketplace";

describe("reading a kind out of the URL", () => {
  it("accepts a kind the server publishes, and nothing else", () => {
    expect(parseListingKind(ListingKind.wiki)).toBe(ListingKind.wiki);
    expect(parseListingKind("dashboards")).toBeUndefined();
    expect(parseListingKind(undefined)).toBeUndefined();
    expect(parseListingKind(7)).toBeUndefined();
  });

  it("opens the community shelf the URL names, else the default", () => {
    for (const shelf of COMMUNITY_SHELVES) {
      expect(parseCommunityShelf(shelf)).toBe(shelf);
    }
    // A person's shelf reached through a community URL is not that community's,
    // and neither is a typo or an absent param.
    expect(parseCommunityShelf(ListingKind.profile_pack)).toBe(DEFAULT_COMMUNITY_SHELF);
    expect(parseCommunityShelf("nonsense")).toBe(DEFAULT_COMMUNITY_SHELF);
    expect(parseCommunityShelf(undefined)).toBe(DEFAULT_COMMUNITY_SHELF);
  });
});

describe("minimumAgeFor", () => {
  const definition = { minimum_age: { default: 16, US: 13 } };

  it("reads the viewer's region first, then the default, else nothing", () => {
    expect(minimumAgeFor(definition, "en-US")).toBe(13);
    expect(minimumAgeFor(definition, "de-DE")).toBe(16);
    expect(minimumAgeFor(definition, "en")).toBe(16);
    expect(minimumAgeFor({ minimum_age: { US: 13 } }, "fr-FR")).toBeNull();
    expect(minimumAgeFor({}, "en-US")).toBeNull();
    expect(minimumAgeFor(null, undefined)).toBeNull();
  });
});

describe("a listing's pictures", () => {
  it("draws a built-in listing's in the app's theme, and any other's as written", () => {
    const image = "/marketplace/community-contacts.webp";
    expect(listingImageUrl(image, ListingSource.builtin, true)).toBe(
      "/marketplace/community-contacts.dark.webp"
    );
    expect(listingImageUrl(image, ListingSource.builtin, false)).toBe(image);
    expect(listingImageUrl(image, ListingSource.registry, true)).toBe(image);
  });

  it("ships both themes of every picture a built-in listing names", () => {
    const catalog = join(process.cwd(), "..", "backend", "app", "marketplace_catalog");
    const missing: string[] = [];

    for (const file of readdirSync(catalog).filter((name) => name.endsWith(".json"))) {
      const manifest = JSON.parse(readFileSync(join(catalog, file), "utf8"));
      for (const image of (manifest.images ?? []) as string[]) {
        for (const path of [image, darkVariant(image)]) {
          if (!existsSync(join(process.cwd(), "public", path))) missing.push(`${file}: ${path}`);
        }
      }
    }

    expect(missing).toEqual([]);
  });
});

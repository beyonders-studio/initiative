import { describe, expect, it } from "vitest";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

import {
  COMMUNITY_SHELVES,
  DEFAULT_COMMUNITY_SHELF,
  minimumAgeFor,
  parseCommunityShelf,
  parseListingKind,
  UNSHELVED_KINDS,
  USER_SHELVES,
} from "./marketplace";

describe("who a listing is offered to", () => {
  it("places every kind the server knows on exactly one shelf", () => {
    // A kind added server-side and missed here would be offered by neither
    // marketplace — invisible rather than obviously broken. A kind held back
    // on purpose is listed as unshelved, which is a decision rather than an
    // omission.
    const placed = [...USER_SHELVES, ...COMMUNITY_SHELVES, ...UNSHELVED_KINDS];
    expect(new Set(placed).size).toBe(placed.length);
    expect(new Set(placed)).toEqual(new Set(Object.values(ListingKind)));
  });
});

describe("reading a kind out of the URL", () => {
  it("accepts every kind the server publishes", () => {
    for (const kind of Object.values(ListingKind)) {
      expect(parseListingKind(kind)).toBe(kind);
    }
  });

  it("reports nothing for a kind that is not one", () => {
    expect(parseListingKind("dashboards")).toBeUndefined();
    expect(parseListingKind(undefined)).toBeUndefined();
    expect(parseListingKind(7)).toBeUndefined();
  });

  it("opens each community shelf the URL names", () => {
    for (const shelf of COMMUNITY_SHELVES) {
      expect(parseCommunityShelf(shelf)).toBe(shelf);
    }
  });

  it("falls back to the default shelf for anything a community does not sell", () => {
    // A person's shelf reached through a community URL is not that community's,
    // and neither is a typo or an absent param.
    expect(parseCommunityShelf(ListingKind.profile_pack)).toBe(DEFAULT_COMMUNITY_SHELF);
    expect(parseCommunityShelf("nonsense")).toBe(DEFAULT_COMMUNITY_SHELF);
    expect(parseCommunityShelf(undefined)).toBe(DEFAULT_COMMUNITY_SHELF);
  });

  it("defaults to a shelf the community actually has", () => {
    expect(COMMUNITY_SHELVES).toContain(DEFAULT_COMMUNITY_SHELF);
  });
});

describe("minimumAgeFor", () => {
  const definition = { minimum_age: { default: 16, US: 13 } };

  it("reads the viewer's region first, then the default", () => {
    expect(minimumAgeFor(definition, "en-US")).toBe(13);
    expect(minimumAgeFor(definition, "de-DE")).toBe(16);
    expect(minimumAgeFor(definition, "en")).toBe(16);
  });

  it("says nothing where the plug-in declares nothing for the viewer", () => {
    expect(minimumAgeFor({ minimum_age: { US: 13 } }, "fr-FR")).toBeNull();
    expect(minimumAgeFor({}, "en-US")).toBeNull();
    expect(minimumAgeFor(null, undefined)).toBeNull();
  });
});

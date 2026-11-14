import { beforeEach, describe, expect, it } from "vitest";

import {
  persistCommunityId,
  readStoredCommunityId,
  readStoredCommunityIdFor,
} from "@/lib/activeCommunityStorage";
import { removeItem } from "@/lib/storage";

const KEY = "initiative-active-guild";

describe("the community a browser remembers", () => {
  beforeEach(() => {
    removeItem(KEY);
  });

  it("keeps one answer per account", () => {
    persistCommunityId(3, 19);
    persistCommunityId(1, 24);

    expect(readStoredCommunityIdFor(19)).toBe(3);
    expect(readStoredCommunityIdFor(24)).toBe(1);
  });

  it("does not answer for an account that has never been here", () => {
    persistCommunityId(3, 19);

    expect(readStoredCommunityIdFor(99)).toBeNull();
  });

  it("offers whoever was here last to code that runs before sign-in", () => {
    persistCommunityId(3, 19);
    persistCommunityId(1, 24);

    expect(readStoredCommunityId()).toBe(1);
  });

  it("forgets an account's community when it is cleared", () => {
    persistCommunityId(3, 19);
    persistCommunityId(null, 19);

    expect(readStoredCommunityIdFor(19)).toBeNull();
  });

  it("writes nothing when nobody is signed in", () => {
    persistCommunityId(3, null);

    expect(readStoredCommunityId()).toBeNull();
  });
});

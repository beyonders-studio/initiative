/**
 * Letting go of a community the user no longer belongs to.
 *
 * Deleting the shard is only half of it: the departed community's queries are
 * still sitting in the query client, and a save landing afterwards would write
 * the shard straight back from memory. These pin the order that makes the prune
 * stick, and the grant case that must survive it.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// The offline cache is native-only, so this file asks for a native platform
// rather than the suite-wide web default.
vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => true,
    getPlatform: () => "android",
    convertFileSrc: (url: string) => url,
  },
  registerPlugin: () => ({}),
}));

import { queryClient } from "@/lib/queryClient";

import {
  retainOnlyCommunities,
  setGrantOnlyCommunityIds,
  shouldPersistQuery,
} from "./offlineCache";

const seed = (key: string) => {
  queryClient.setQueryData([key], { seeded: true });
};

const held = (key: string) => queryClient.getQueryData([key]) !== undefined;

beforeEach(() => {
  queryClient.clear();
  setGrantOnlyCommunityIds([]);
});

describe("retainOnlyCommunities", () => {
  it("drops a departed community's queries out of the client, and nothing that names none", async () => {
    seed("/api/v1/c/3/tasks");
    seed("/api/v1/c/5/tasks");
    seed("/api/v1/me");
    seed("/api/v1/me/tasks");
    queryClient.setQueryData(["dm", "unread"], { seeded: true });

    await retainOnlyCommunities([3], [3]);

    expect(held("/api/v1/c/3/tasks")).toBe(true);
    // Nothing is left that a later save could write the shard back from.
    expect(held("/api/v1/c/5/tasks")).toBe(false);
    expect(held("/api/v1/me")).toBe(true);
    expect(held("/api/v1/me/tasks")).toBe(true);
    expect(queryClient.getQueryData(["dm", "unread"])).toBeDefined();
  });

  it("keeps a community reached by a live grant usable, while refusing it disk", async () => {
    seed("/api/v1/c/9/tasks");
    setGrantOnlyCommunityIds([9]);

    // Reachable (the grant is live) but not cacheable (it can end while away).
    await retainOnlyCommunities([3, 9], [3]);

    expect(held("/api/v1/c/9/tasks")).toBe(true);
    // Still barred from disk by the grant exclusion, which the prune leaves be.
    const query = queryClient.getQueryCache().find({ queryKey: ["/api/v1/c/9/tasks"] });
    expect(query && shouldPersistQuery(query)).toBe(false);
  });
});

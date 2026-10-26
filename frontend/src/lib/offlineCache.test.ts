import type { Query } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import {
  addGrantOnlyCommunityIds,
  communityIdOfPath,
  isPersistablePath,
  noteRestoredIdentity,
  offlineCacheBuster,
  resetGrantOnlyCommunityIds,
  restoredIdentityMismatch,
  setGrantOnlyCommunityIds,
  shardOfQueryKey,
  shouldPersistQuery,
} from "./offlineCache";

beforeEach(() => {
  resetGrantOnlyCommunityIds();
  noteRestoredIdentity(null);
});

describe("communityIdOfPath", () => {
  it("reads the community out of a community-addressed path", () => {
    expect(communityIdOfPath("/api/v1/c/42/tasks/7")).toBe(42);
  });

  it("is null for a platform path", () => {
    expect(communityIdOfPath("/api/v1/me")).toBeNull();
  });

  it("does not match a community-looking segment further along the path", () => {
    expect(communityIdOfPath("/api/v1/me/tasks?g=3")).toBeNull();
  });
});

describe("isPersistablePath", () => {
  it("keeps community content somebody was reading", () => {
    expect(isPersistablePath("/api/v1/c/3/tasks/2866")).toBe(true);
    expect(isPersistablePath("/api/v1/c/3/files")).toBe(true);
    expect(isPersistablePath("/api/v1/c/12/projects/1/tasks")).toBe(true);
    expect(isPersistablePath("/api/v1/c/3/catalogs/4")).toBe(true);
    expect(isPersistablePath("/api/v1/c/3/wiki-pages/5")).toBe(true);
  });

  it("keeps the cross-community reads the home screens are built from", () => {
    expect(isPersistablePath("/api/v1/me/tasks")).toBe(true);
    expect(isPersistablePath("/api/v1/me")).toBe(true);
    expect(isPersistablePath("/api/v1/communities")).toBe(true);
  });

  it("denies by default — an unlisted path is never persisted", () => {
    expect(isPersistablePath("/api/v1/c/3/uploads/9")).toBe(false);
    expect(isPersistablePath("/api/v1/c/3/imports")).toBe(false);
    expect(isPersistablePath("/api/v1/something-new")).toBe(false);
    expect(isPersistablePath("/other/path")).toBe(false);
  });

  it("never persists configuration, operator or access-grant surfaces", () => {
    for (const path of [
      "/api/v1/auth/providers",
      "/api/v1/config",
      "/api/v1/settings/branding",
      "/api/v1/c/3/settings",
      "/api/v1/c/3/settings/ai",
      "/api/v1/c/3/members",
      "/api/v1/c/3/webhooks/subscriptions",
      "/api/v1/c/3/plugins",
      "/api/v1/operator/users",
      "/api/v1/access-grants/",
      "/api/v1/ai-settings",
      "/api/v1/webhooks",
    ]) {
      expect(isPersistablePath(path)).toBe(false);
    }
  });

  it("never persists message surfaces, whose plaintext has its own erase contract", () => {
    expect(isPersistablePath("/api/v1/me/dm-settings")).toBe(false);
    expect(isPersistablePath("/api/v1/me/connections")).toBe(false);
    expect(isPersistablePath("/api/v1/me/dm-permissions")).toBe(false);
    expect(isPersistablePath("/api/v1/me/contacts")).toBe(false);
    expect(isPersistablePath("/api/v1/me/ignored")).toBe(false);
    expect(isPersistablePath("/api/v1/users/8/dm/devices")).toBe(false);
  });

  it("never persists the account's settings, keys or addresses", () => {
    expect(isPersistablePath("/api/v1/me/api-keys")).toBe(false);
    expect(isPersistablePath("/api/v1/me/emails")).toBe(false);
    expect(isPersistablePath("/api/v1/me/notification-preferences")).toBe(false);
    expect(isPersistablePath("/api/v1/me/reports")).toBe(false);
  });

  it("never persists search or trash", () => {
    expect(isPersistablePath("/api/v1/c/3/search")).toBe(false);
    expect(isPersistablePath("/api/v1/c/3/trash")).toBe(false);
    expect(isPersistablePath("/api/v1/me/trash")).toBe(false);
  });

  it("excludes a community reached only by a time-bound PAM grant", () => {
    expect(isPersistablePath("/api/v1/c/9/tasks")).toBe(true);
    setGrantOnlyCommunityIds([9]);
    expect(isPersistablePath("/api/v1/c/9/tasks")).toBe(false);
    // Other communities are unaffected.
    expect(isPersistablePath("/api/v1/c/10/tasks")).toBe(true);
  });

  it("does not let a prefix match spill into a longer sibling name", () => {
    expect(isPersistablePath("/api/v1/c/3/tasks-export")).toBe(false);
  });

  it("widens the grant exclusion without narrowing it, for an unread grant list", () => {
    setGrantOnlyCommunityIds([9]);
    // A refresh that could not read the grant list must not drop 9.
    addGrantOnlyCommunityIds([]);
    expect(isPersistablePath("/api/v1/c/9/tasks")).toBe(false);
    addGrantOnlyCommunityIds([11]);
    expect(isPersistablePath("/api/v1/c/9/tasks")).toBe(false);
    expect(isPersistablePath("/api/v1/c/11/tasks")).toBe(false);
    // A reading that did come back is allowed to replace it.
    setGrantOnlyCommunityIds([]);
    expect(isPersistablePath("/api/v1/c/9/tasks")).toBe(true);
  });
});

const query = (key: readonly unknown[], status: "success" | "error" | "pending"): Query =>
  ({ queryKey: key, state: { status } }) as unknown as Query;

describe("shouldPersistQuery", () => {
  it("keeps a successful read of an allowlisted path", () => {
    expect(shouldPersistQuery(query(["/api/v1/c/3/tasks", { page: 1 }], "success"))).toBe(true);
  });

  it("drops anything that is not a success", () => {
    expect(shouldPersistQuery(query(["/api/v1/c/3/tasks"], "error"))).toBe(false);
    expect(shouldPersistQuery(query(["/api/v1/c/3/tasks"], "pending"))).toBe(false);
  });

  it("drops hand-written keys, which are not request paths", () => {
    expect(shouldPersistQuery(query(["dm", "unread"], "success"))).toBe(false);
    expect(shouldPersistQuery(query(["contacts", "community", 3, ""], "success"))).toBe(false);
    expect(shouldPersistQuery(query([{ scope: "community-plugin" }], "success"))).toBe(false);
  });
});

describe("shardOfQueryKey", () => {
  it("files a community's content under that community", () => {
    expect(shardOfQueryKey(["/api/v1/c/3/tasks/2866"])).toBe("g3");
    expect(shardOfQueryKey(["/api/v1/c/12/files"])).toBe("g12");
  });

  it("files everything else under the platform shard", () => {
    expect(shardOfQueryKey(["/api/v1/me"])).toBe("platform");
    expect(shardOfQueryKey(["/api/v1/me/tasks", { page: 1 }])).toBe("platform");
    expect(shardOfQueryKey([{ scope: "community-plugin" }])).toBe("platform");
  });
});

describe("offlineCacheBuster", () => {
  it("differs per server, so pointing at another deployment discards the cache", () => {
    expect(offlineCacheBuster("https://a.example")).not.toBe(
      offlineCacheBuster("https://b.example")
    );
  });
});

describe("restoredIdentityMismatch", () => {
  it("is false when nothing was restored", () => {
    expect(restoredIdentityMismatch(7)).toBe(false);
  });

  it("is false when the confirmed user is the one we restored for", () => {
    noteRestoredIdentity(7);
    expect(restoredIdentityMismatch(7)).toBe(false);
  });

  it("is true when sign-out never ran and somebody else signed in", () => {
    noteRestoredIdentity(7);
    expect(restoredIdentityMismatch(8)).toBe(true);
  });

  it("adopts the confirmed identity, so it only fires once per handover", () => {
    noteRestoredIdentity(7);
    expect(restoredIdentityMismatch(8)).toBe(true);
    expect(restoredIdentityMismatch(8)).toBe(false);
  });
});

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
  it("reads the community out of a community-addressed path, and only there", () => {
    expect(communityIdOfPath("/api/v1/c/42/tasks/7")).toBe(42);
    expect(communityIdOfPath("/api/v1/me")).toBeNull();
    expect(communityIdOfPath("/api/v1/me/tasks?g=3")).toBeNull();
  });
});

describe("isPersistablePath", () => {
  // Community content somebody was reading, and the cross-community reads the
  // home screens are built from.
  it.each([
    "/api/v1/c/3/tasks/2866",
    "/api/v1/c/3/files",
    "/api/v1/c/12/projects/1/tasks",
    "/api/v1/c/3/collections/4",
    "/api/v1/c/3/wiki-pages/5",
    "/api/v1/me/tasks",
    "/api/v1/me",
    "/api/v1/communities",
  ])("keeps %s", (path) => {
    expect(isPersistablePath(path)).toBe(true);
  });

  it.each([
    // Denied by default: an unlisted path is never persisted.
    "/api/v1/c/3/uploads/9",
    "/api/v1/c/3/imports",
    "/api/v1/something-new",
    "/other/path",
    // A prefix match does not spill into a longer sibling name.
    "/api/v1/c/3/tasks-export",
    // Configuration, operator and access-grant surfaces.
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
    // Message surfaces, whose plaintext has its own erase contract.
    "/api/v1/me/dm-settings",
    "/api/v1/me/connections",
    "/api/v1/me/dm-permissions",
    "/api/v1/me/people",
    "/api/v1/me/ignored",
    "/api/v1/users/8/dm/devices",
    // The account's settings, keys and addresses.
    "/api/v1/me/api-keys",
    "/api/v1/me/emails",
    "/api/v1/me/notification-preferences",
    "/api/v1/me/reports",
    // Search and trash.
    "/api/v1/c/3/search",
    "/api/v1/c/3/trash",
    "/api/v1/me/trash",
  ])("never persists %s", (path) => {
    expect(isPersistablePath(path)).toBe(false);
  });

  it("excludes a community reached only by a time-bound PAM grant", () => {
    expect(isPersistablePath("/api/v1/c/9/tasks")).toBe(true);
    setGrantOnlyCommunityIds([9]);
    expect(isPersistablePath("/api/v1/c/9/tasks")).toBe(false);
    // Other communities are unaffected.
    expect(isPersistablePath("/api/v1/c/10/tasks")).toBe(true);
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
  it("keeps only a successful read of an allowlisted path, never a hand-written key", () => {
    expect(shouldPersistQuery(query(["/api/v1/c/3/tasks", { page: 1 }], "success"))).toBe(true);
    expect(shouldPersistQuery(query(["/api/v1/c/3/tasks"], "error"))).toBe(false);
    expect(shouldPersistQuery(query(["/api/v1/c/3/tasks"], "pending"))).toBe(false);
    expect(shouldPersistQuery(query(["dm", "unread"], "success"))).toBe(false);
    expect(shouldPersistQuery(query(["people", "community", 3, ""], "success"))).toBe(false);
    expect(shouldPersistQuery(query([{ scope: "community-plugin" }], "success"))).toBe(false);
  });
});

describe("shardOfQueryKey", () => {
  it("files a community's content under that community, everything else under the platform", () => {
    expect(shardOfQueryKey(["/api/v1/c/3/tasks/2866"])).toBe("g3");
    expect(shardOfQueryKey(["/api/v1/c/12/files"])).toBe("g12");
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
  it("fires once when somebody other than the restored user signs in", () => {
    // Nothing restored.
    expect(restoredIdentityMismatch(7)).toBe(false);
    noteRestoredIdentity(7);
    expect(restoredIdentityMismatch(7)).toBe(false);
    // Sign-out never ran and somebody else signed in; the confirmed identity is
    // adopted, so it fires only once per handover.
    expect(restoredIdentityMismatch(8)).toBe(true);
    expect(restoredIdentityMismatch(8)).toBe(false);
  });
});

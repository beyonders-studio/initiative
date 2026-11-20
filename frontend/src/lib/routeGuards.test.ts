import { describe, expect, it } from "vitest";

import { type GuardServerState, routeGuardSignature } from "./routeGuards";

const web: GuardServerState = {
  loading: false,
  isNativePlatform: false,
  isServerConfigured: true,
};

/**
 * The signature decides when the router re-evaluates its `beforeLoad` guards.
 * Miss a transition and a signed-out visitor keeps the authenticated shell;
 * fire on unrelated churn and every context update reloads the whole match
 * tree. Tests here pin both edges.
 */
describe("routeGuardSignature", () => {
  it("tells loading, settled-anonymous and each signed-in user apart", () => {
    const signatures = [
      routeGuardSignature({ loading: true, user: null }, web),
      routeGuardSignature({ loading: false, user: null }, web),
      routeGuardSignature({ loading: false, user: { id: 1 } }, web),
      routeGuardSignature({ loading: false, user: { id: 2 } }, web),
    ];
    expect(new Set(signatures).size).toBe(signatures.length);
  });

  it("is stable when the user object is replaced with an equivalent one", () => {
    // `refreshUser()` swaps in a fresh object on every poll; that must not
    // invalidate the router.
    const first = routeGuardSignature({ loading: false, user: { id: 4 } }, web);
    const second = routeGuardSignature({ loading: false, user: { id: 4 } }, { ...web });
    expect(first).toBe(second);
  });

  it("changes when a native install gains a configured server", () => {
    const auth = { loading: false, user: { id: 1 } };
    const unconfigured = routeGuardSignature(auth, {
      loading: false,
      isNativePlatform: true,
      isServerConfigured: false,
    });
    const configured = routeGuardSignature(auth, {
      loading: false,
      isNativePlatform: true,
      isServerConfigured: true,
    });
    expect(unconfigured).not.toBe(configured);
  });

  it("ignores server values while the server context is still loading", () => {
    const auth = { loading: false, user: { id: 1 } };
    const a = routeGuardSignature(auth, {
      loading: true,
      isNativePlatform: true,
      isServerConfigured: false,
    });
    const b = routeGuardSignature(auth, {
      loading: true,
      isNativePlatform: false,
      isServerConfigured: true,
    });
    expect(a).toBe(b);
  });

  it("treats an absent context as its own state", () => {
    const absent = routeGuardSignature(undefined, undefined);
    expect(absent).not.toBe(routeGuardSignature({ loading: true, user: null }, web));
    expect(absent).toBe(routeGuardSignature(undefined, undefined));
  });
});

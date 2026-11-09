/**
 * Every destination the server puts on a notification has to be a real page.
 *
 * The server writes a `target_path` into the notification row and the SPA
 * navigates to it. Nothing checks the two agree, which is how the account
 * notices came to point at `/settings/profile` — a path that has never
 * existed. It typechecks on both sides and fails only in somebody's hands.
 *
 * So this reads the paths the backend actually writes and asserts each one is
 * a route this app has. It is deliberately a *frontend* test: the route table
 * is here, and it is the half that changes when a page moves.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const BACKEND = path.resolve(__dirname, "../../../backend/app");
const ROUTE_TREE = path.resolve(__dirname, "../routeTree.gen.ts");

/** Literal `"target_path": "/…"` values the notification code writes. */
const backendTargetPaths = (): string[] => {
  const source = fs.readFileSync(path.join(BACKEND, "services/notifications.py"), "utf-8");
  const found = new Set<string>();
  for (const [, value] of source.matchAll(/"target_path":\s*"(\/[^"]*)"/g)) {
    found.add(value);
  }
  // Named constants the same file addresses app-level routes with.
  for (const [, value] of source.matchAll(/^[A-Z_]*TARGET_PATH\s*=\s*"(\/[^"]*)"/gm)) {
    found.add(value);
  }
  return [...found];
};

const appRoutes = (): Set<string> => {
  const tree = fs.readFileSync(ROUTE_TREE, "utf-8");
  return new Set([...tree.matchAll(/fullPath: '([^']+)'/g)].map(([, p]) => p));
};

describe("notification target paths", () => {
  it("finds the paths it is meant to be checking", () => {
    // Guards against the regexes silently matching nothing, which would make
    // every assertion below vacuously true.
    const paths = backendTargetPaths();
    expect(paths.length).toBeGreaterThan(0);
    expect(paths).toContain("/profile/account");
  });

  it("only ever points at a page this app has", () => {
    const routes = appRoutes();
    // Community-relative targets are resolved against a community elsewhere; these
    // are the app-level ones the SPA navigates to verbatim.
    const missing = backendTargetPaths().filter((target) => !routes.has(target));

    expect(missing).toEqual([]);
  });
});

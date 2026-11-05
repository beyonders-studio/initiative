import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The browser MCP server in .mcp.json runs with `--browser chromium`: the
 * Chromium that `pnpm exec playwright install chromium` downloads for the
 * journeys and the release screenshots. Each Playwright release wants its own
 * Chromium build, so pnpm-workspace.yaml holds @playwright/mcp to the
 * Playwright @playwright/test is on, whichever of the two moves.
 */
const root = path.resolve(__dirname, "../..");

/** Where `name` resolves to from the package in `from`. */
const resolveFrom = (from: string, name: string) =>
  path.dirname(createRequire(path.join(from, "package.json")).resolve(`${name}/package.json`));

const chromium = (playwrightCore: string) =>
  (
    JSON.parse(fs.readFileSync(path.join(playwrightCore, "browsers.json"), "utf8")) as {
      browsers: { name: string; revision: string; browserVersion?: string }[];
    }
  ).browsers.find((browser) => browser.name === "chromium");

describe("the browser MCP server", () => {
  it("runs the Chromium the tests install", () => {
    const test = resolveFrom(root, "@playwright/test");
    const installs = chromium(resolveFrom(resolveFrom(test, "playwright"), "playwright-core"));
    const runs = chromium(resolveFrom(resolveFrom(root, "@playwright/mcp"), "playwright-core"));
    expect(
      runs?.revision,
      `@playwright/mcp runs Chromium ${runs?.browserVersion}, @playwright/test installs ${installs?.browserVersion}: the overrides in pnpm-workspace.yaml keep them on one Playwright`
    ).toBe(installs?.revision);
  });
});

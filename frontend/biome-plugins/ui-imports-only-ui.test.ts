import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

import { afterAll, describe, expect, it } from "vitest";

const frontend = path.join(import.meta.dirname, "..");
// Inside src/ui, because that is where the rule applies.
const dir = mkdtempSync(path.join(frontend, "src/ui/rule-fixtures-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));

const refused = {
  "one of Initiative's hooks": 'import { useAuth } from "@/hooks/useAuth";',
  "a relative path out of the folder": 'import { thing } from "../../lib/thing";',
  "a re-export of Initiative's code": 'export { other } from "@/lib/other";',
  "another generated module": 'export type { Other } from "@/api/generated/other";',
  "a page loaded later": 'export const page = () => import("@/pages/Home");',
};
const allowed = {
  "the kit's own files": 'import { cn } from "@/ui/lib/utils";',
  "a file beside it": 'import { thing } from "./sibling";',
  "an npm package": 'import { useState } from "react";',
  "the generated API's types":
    'import type { UserRead } from "@/api/generated/initiativeAPI.schemas";',
  "a kit file loaded later": 'export const button = () => import("@/ui/button");',
};

/** Lints every fixture in one Biome run, and says which files it flagged. */
const flagged = (() => {
  const sources = Object.values({ ...refused, ...allowed });
  const files = sources.map((source, index) => {
    const file = path.join(dir, `${index}.ts`);
    writeFileSync(file, `${source}\n`);
    return file;
  });
  let output: string;
  try {
    output = execFileSync(
      path.join(frontend, "node_modules/.bin/biome"),
      ["lint", `--config-path=${frontend}`, "--only=plugin", "--reporter=json", ...files],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    );
  } catch (error) {
    output = (error as { stdout: string }).stdout;
  }
  const report = JSON.parse(output) as {
    diagnostics: { message: string; location: { path: string } }[];
  };
  return new Set(
    report.diagnostics
      .filter((diagnostic) => diagnostic.message.includes("src/ui is copied into our plug-ins"))
      .map((diagnostic) => path.basename(diagnostic.location.path))
  );
})();

const fileOf = (source: string) =>
  `${Object.values({ ...refused, ...allowed }).indexOf(source)}.ts`;

describe("the ui-imports-only-ui rule", () => {
  it.each(Object.entries(refused))("refuses %s", (_, source) => {
    expect(flagged.has(fileOf(source))).toBe(true);
  });

  it.each(Object.entries(allowed))("allows %s", (_, source) => {
    expect(flagged.has(fileOf(source))).toBe(false);
  });
});

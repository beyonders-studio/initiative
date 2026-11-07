// biome-ignore-all lint/plugin: these are the rule's fixtures
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterAll, describe, expect, it } from "vitest";

const frontend = path.join(import.meta.dirname, "..");
const dir = mkdtempSync(path.join(tmpdir(), "one-formatter-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));

const refused = {
  "a date formatter built in place": 'new Intl.DateTimeFormat(undefined, { dateStyle: "medium" })',
  "a number formatter with no arguments": "new Intl.NumberFormat()",
  "a collator": "new Intl.Collator()",
  "a date's toLocaleDateString": 'date.toLocaleDateString("en", { month: "short" })',
  "a number's toLocaleString": "value.toLocaleString()",
  "a date's toLocaleTimeString": "date.toLocaleTimeString()",
  "localeCompare with options": 'text.localeCompare("b", undefined, { sensitivity: "base" })',
  "localeCompare with a locale": 'text.localeCompare("b", "en")',
};
const allowed = {
  "the shared date formatter": 'dateTimeFormat(undefined, { dateStyle: "medium" })',
  "localeCompare with nothing else": 'text.localeCompare("b")',
  "a locale, which formats nothing": 'new Intl.Locale("en")',
};

/** Lints every fixture in one Biome run, and says which files it flagged. */
const flagged = (() => {
  const sources = Object.values({ ...refused, ...allowed });
  const files = sources.map((expression, index) => {
    const file = path.join(dir, `${index}.ts`);
    writeFileSync(
      file,
      "declare const date: Date, value: number, text: string;\n" +
        "declare const dateTimeFormat: (...args: unknown[]) => unknown;\n" +
        `export const x = ${expression};\n`
    );
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
      .filter((diagnostic) => diagnostic.message.includes("src/ui/lib/intl.ts"))
      .map((diagnostic) => path.basename(diagnostic.location.path))
  );
})();

const fileOf = (expression: string) =>
  `${Object.values({ ...refused, ...allowed }).indexOf(expression)}.ts`;

describe("the one-formatter rule", () => {
  it.each(Object.entries(refused))("refuses %s", (_, expression) => {
    expect(flagged.has(fileOf(expression))).toBe(true);
  });

  it.each(Object.entries(allowed))("allows %s", (_, expression) => {
    expect(flagged.has(fileOf(expression))).toBe(false);
  });
});

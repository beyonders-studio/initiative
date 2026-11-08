import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The editor's core imports what the UI kit may (`ui-imports-only-ui`): npm
 * packages, the kit, the generated API's types and its own files, none of
 * them Initiative's extension in `initiative/`.
 */
const EDITOR = import.meta.dirname;

const coreFiles = (readdirSync(EDITOR, { recursive: true }) as string[]).filter(
  (file) =>
    /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file) && !file.startsWith(`initiative${path.sep}`)
);

const SPECIFIER = /(?:\bfrom\s*|\bimport\s*\(\s*|^import\s+)["']([^"']+)["']/gm;

const refused = (specifier: string): boolean =>
  specifier.split("/").includes("..") ||
  specifier.startsWith("./initiative/") ||
  specifier.startsWith("@/components/editor/initiative/") ||
  (specifier.startsWith("@/") &&
    !specifier.startsWith("@/ui/") &&
    !specifier.startsWith("@/components/editor/") &&
    specifier !== "@/api/generated/initiativeAPI.schemas");

describe("the editor's core", () => {
  it("has files to check", () => {
    expect(coreFiles.length).toBeGreaterThan(50);
  });

  it.each(coreFiles)("imports nothing of Initiative's: %s", (file) => {
    const source = readFileSync(path.join(EDITOR, file), "utf8");
    const specifiers = Array.from(source.matchAll(SPECIFIER), (match) => match[1]);
    expect(specifiers.filter(refused)).toEqual([]);
  });
});

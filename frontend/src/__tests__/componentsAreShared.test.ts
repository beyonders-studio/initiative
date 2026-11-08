import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// `components/` holds the app's chrome and what several pages share. A
// component only the pages of one folder use is part of those pages, and
// lives beside them.
const SRC = path.resolve(__dirname, "..");
const isTest = (file: string) => /\.test\.|__tests__/.test(file);

const sources = (dir: string): string[] =>
  fs.readdirSync(path.join(SRC, dir), { withFileTypes: true }).flatMap((entry) => {
    const rel = path.join(dir, entry.name);
    if (entry.isDirectory()) return sources(rel);
    return /\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts") ? [rel] : [];
  });

const files = sources(".").map((file) => path.normalize(file));
const known = new Set(files);
const resolve = (from: string, spec: string): string | undefined => {
  const bare = spec.replace(/\?.*$/, "");
  let base: string;
  if (bare.startsWith("@/")) base = bare.slice(2);
  else if (bare.startsWith(".")) base = path.join(path.dirname(from), bare);
  else return undefined;
  return [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`].find((c) =>
    known.has(c)
  );
};

const importers = new Map<string, Set<string>>();
const IMPORT = /(?:from\s*|import\s*\(\s*|import\s+)["']([^"']+)["']/g;
for (const file of files) {
  if (isTest(file)) continue;
  const text = fs.readFileSync(path.join(SRC, file), "utf8");
  for (const [, spec] of text.matchAll(IMPORT)) {
    const target = resolve(file, spec);
    if (!target || target === file) continue;
    if (!importers.has(target)) importers.set(target, new Set());
    importers.get(target)?.add(file);
  }
}

describe("components", () => {
  it("are used by more than one folder of pages, or outside pages", () => {
    const pageOnly = files
      .filter((file) => file.startsWith("components/") && !isTest(file))
      .flatMap((file) => {
        const folders = new Set([...(importers.get(file) ?? [])].map((i) => path.dirname(i)));
        const [only] = folders;
        return folders.size === 1 && only.startsWith("pages/") ? [`${file} → ${only}`] : [];
      });

    expect(pageOnly).toEqual([]);
  });

  it("sit in folders", () => {
    expect(files.filter((file) => path.dirname(file) === "components")).toEqual([]);
  });
});

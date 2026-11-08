import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const PLUGINS_SOURCE = fs.readFileSync(path.resolve(__dirname, "./plugins.tsx"), "utf-8");

/**
 * Every className string in the file that positions an element with `sticky`.
 * These are the editor's toolbars and actions bar — they overlap the document
 * as it scrolls, so their background has to be opaque.
 */
const stickyClassNames = (source: string): string[] =>
  Array.from(source.matchAll(/className="([^"]*)"/g))
    .map((match) => match[1])
    .filter((classes) => /\bsticky\b/.test(classes));

describe("editor toolbars", () => {
  it("has sticky bars to check", () => {
    expect(stickyClassNames(PLUGINS_SOURCE).length).toBeGreaterThan(0);
  });

  it.each(stickyClassNames(PLUGINS_SOURCE))("is opaque: %s", (classes) => {
    const backgrounds = classes.split(/\s+/).filter((cls) => cls.startsWith("bg-"));

    expect(backgrounds).not.toHaveLength(0);
    // `bg-muted/20` and friends let the scrolled content show through.
    expect(backgrounds.filter((cls) => cls.includes("/"))).toEqual([]);
  });
});

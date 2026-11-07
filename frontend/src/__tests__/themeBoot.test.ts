import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const read = (relative: string) => readFileSync(resolve(__dirname, "../..", relative), "utf8");

/**
 * The pre-paint theme script lives outside the React tree, so nothing types
 * the contract between it and the provider. These keep the two in step.
 */
describe("theme boot script", () => {
  it("reads the same storage key the ThemeProvider writes", () => {
    const boot = read("public/theme-boot.js");
    const provider = read("src/hooks/useTheme.tsx");
    const key = provider.match(/THEME_STORAGE_KEY = "([^"]+)"/)?.[1];
    expect(key).toBeTruthy();
    expect(boot).toContain(`"${key}"`);
  });

  it("is loaded from the app's own origin before the app itself", () => {
    const html = read("index.html");
    expect(html).toContain('<script src="/theme-boot.js"></script>');
    expect(html).toContain('<link rel="stylesheet" href="/theme-boot.css" />');
    expect(html.indexOf("/theme-boot.js")).toBeLessThan(html.indexOf("/src/main.tsx"));
  });

  it("mirrors the stylesheet's background for each theme", () => {
    const boot = read("public/theme-boot.css");
    const styles = read("src/ui/styles.css");
    const tokens = [...styles.matchAll(/^ {2}--background: ([^;]+);/gm)].map((m) => m[1]);
    expect(tokens).toHaveLength(2);
    for (const token of tokens) expect(boot).toContain(token);
  });
});

/**
 * The script a plug-in refreshes its copy of the kit with, run against this
 * checkout: what it copies, and what its check refuses.
 */
import { execFileSync } from "node:child_process";
import {
  appendFileSync,
  copyFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

const script = path.join(import.meta.dirname, "refresh.mjs");
const frontend = path.join(import.meta.dirname, "../..");
const root = path.join(frontend, "..");

let plugin: string;
beforeEach(() => {
  plugin = mkdtempSync(path.join(tmpdir(), "plugin-"));
  copyFileSync(path.join(frontend, "package.json"), path.join(plugin, "package.json"));
  run("--from", root);
});
afterEach(() => rmSync(plugin, { recursive: true, force: true }));

function run(...args: string[]) {
  return execFileSync("node", [script, ...args], { cwd: plugin, encoding: "utf8", stdio: "pipe" });
}

/** What the check says, or nothing when the copy is current. */
const check = (): string => {
  try {
    run("--check", "--from", root);
    return "";
  } catch (error) {
    return (error as { stderr: string }).stderr;
  }
};

describe("refreshing the kit", () => {
  it("copies the kit without its tests, with the API types and its words, and stamps it", () => {
    const at = (file: string) => path.join(plugin, file);
    expect(readFileSync(at("src/ui/button.tsx"), "utf8")).toBe(
      readFileSync(path.join(frontend, "src/ui/button.tsx"), "utf8")
    );
    expect(existsSync(at("src/ui/lib/utils.ts"))).toBe(true);
    expect(existsSync(at("src/ui/refresh.test.ts"))).toBe(false);
    expect(existsSync(at("src/api/generated/initiativeAPI.schemas.ts"))).toBe(true);
    expect(existsSync(at("public/locales/de/ui.json"))).toBe(true);
    expect(readFileSync(at("src/ui/.initiative-ref"), "utf8").trim()).toMatch(/^[0-9a-f]{40}$/);
  });

  it("passes a copy nobody touched", () => {
    expect(check()).toBe("");
  });

  it("refuses a copied file that was edited", () => {
    appendFileSync(path.join(plugin, "src/ui/button.tsx"), "// edited\n");
    expect(check()).toContain("src/ui/button.tsx differs");
  });

  it("refuses a file the kit does not have", () => {
    writeFileSync(path.join(plugin, "src/ui/mine.tsx"), "export const mine = 1;\n");
    expect(check()).toContain("src/ui/mine.tsx is not part of Initiative's kit");
  });

  it("refuses a package at another version than the kit is built with", () => {
    const manifest = JSON.parse(readFileSync(path.join(plugin, "package.json"), "utf8"));
    manifest.dependencies["lucide-react"] = "^0.1.0";
    writeFileSync(path.join(plugin, "package.json"), JSON.stringify(manifest));
    expect(check()).toContain("lucide-react ^0.1.0");
  });
});

import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const FRONTEND_LOCALES_DIR = path.resolve(__dirname, "../../public/locales");
const BACKEND_LOCALES_DIR = path.resolve(__dirname, "../../../backend/app/locales");
const SOURCE_LOCALE = "en";

/**
 * Recursively collect all leaf key paths from a nested JSON object.
 * e.g. { a: { b: "x", c: "y" } } → ["a.b", "a.c"]
 */
const collectKeys = (obj: Record<string, unknown>, prefix = ""): string[] => {
  const keys: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      keys.push(...collectKeys(value as Record<string, unknown>, fullKey));
    } else {
      keys.push(fullKey);
    }
  }
  return keys.sort();
};

const loadJson = (filePath: string): Record<string, unknown> =>
  JSON.parse(fs.readFileSync(filePath, "utf-8"));

const getLocales = (localesDir: string): string[] =>
  fs
    .readdirSync(localesDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && d.name !== SOURCE_LOCALE && d.name !== "pseudo")
    .map((d) => d.name);

const getNamespaces = (localesDir: string, locale: string): string[] =>
  fs
    .readdirSync(path.join(localesDir, locale))
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.replace(".json", ""));

const getNestedValue = (obj: Record<string, unknown>, keyPath: string): unknown => {
  let current: unknown = obj;
  for (const part of keyPath.split(".")) {
    if (current === null || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
};

/**
 * Both locale roots answer the same question — does every translation carry
 * exactly the source locale's keys — so they are checked by one suite.
 *
 * `placeholders` is frontend-only: those strings interpolate `{{variables}}`,
 * and the namespace-file check goes with them.
 */
const describeLocaleParity = (
  label: string,
  localesDir: string,
  { placeholders = false }: { placeholders?: boolean } = {}
) => {
  describe(label, () => {
    const sourceNamespaces = getNamespaces(localesDir, SOURCE_LOCALE);

    for (const locale of getLocales(localesDir)) {
      describe(`${locale} vs ${SOURCE_LOCALE}`, () => {
        if (placeholders) {
          it("should have the same namespace files", () => {
            const targetNamespaces = getNamespaces(localesDir, locale);
            expect(
              sourceNamespaces.filter((ns) => !targetNamespaces.includes(ns)),
              `Missing namespace files in ${locale}`
            ).toEqual([]);
            expect(
              targetNamespaces.filter((ns) => !sourceNamespaces.includes(ns)),
              `Extra namespace files in ${locale}`
            ).toEqual([]);
          });
        }

        for (const namespace of sourceNamespaces) {
          describe(`${namespace}.json`, () => {
            const sourcePath = path.join(localesDir, SOURCE_LOCALE, `${namespace}.json`);
            const targetPath = path.join(localesDir, locale, `${namespace}.json`);

            it("should exist with exactly the source keys", () => {
              expect(fs.existsSync(targetPath), `${locale}/${namespace}.json is missing`).toBe(
                true
              );
              const sourceKeys = collectKeys(loadJson(sourcePath));
              const targetKeys = collectKeys(loadJson(targetPath));
              expect(
                sourceKeys.filter((k) => !targetKeys.includes(k)),
                `Keys in ${SOURCE_LOCALE} but missing in ${locale}`
              ).toEqual([]);
              expect(
                targetKeys.filter((k) => !sourceKeys.includes(k)),
                `Keys in ${locale} but not in ${SOURCE_LOCALE}`
              ).toEqual([]);
            });

            if (!placeholders) return;

            it("should preserve interpolation placeholders", () => {
              if (!fs.existsSync(targetPath)) return;
              const sourceData = loadJson(sourcePath);
              const targetData = loadJson(targetPath);
              const errors: string[] = [];

              for (const key of collectKeys(sourceData)) {
                const sourceVal = getNestedValue(sourceData, key);
                const targetVal = getNestedValue(targetData, key);
                if (typeof sourceVal !== "string" || typeof targetVal !== "string") continue;

                const sourcePlaceholders = (sourceVal.match(/\{\{[^}]+\}\}/g) ?? []).sort();
                const targetPlaceholders = (targetVal.match(/\{\{[^}]+\}\}/g) ?? []).sort();
                if (JSON.stringify(sourcePlaceholders) !== JSON.stringify(targetPlaceholders)) {
                  errors.push(
                    `${key}: expected {{placeholders}} ${JSON.stringify(sourcePlaceholders)}, got ${JSON.stringify(targetPlaceholders)}`
                  );
                }
              }
              expect(errors, "Mismatched interpolation placeholders").toEqual([]);
            });
          });
        }
      });
    }
  });
};

describeLocaleParity("Frontend locale key parity", FRONTEND_LOCALES_DIR, {
  placeholders: true,
});

if (fs.existsSync(BACKEND_LOCALES_DIR)) {
  describeLocaleParity("Backend locale key parity", BACKEND_LOCALES_DIR);
}

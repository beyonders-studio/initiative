/**
 * Widget metadata: the contract, and the built-ins' conformance to it.
 *
 * The reason this exists as its own boundary: a widget's name and option labels
 * come from the widget, so they are untrusted input on a path that ends in the
 * DOM. `validateWidgetMeta` rebuilds them from checked parts, and the built-ins
 * are held to the same contract a listing's widget would be.
 */
import { describe, expect, it } from "vitest";

import { localized } from "@/ui/lib/localized";

import { BUILTIN_WIDGET_TYPES, builtinWidgetSource } from "./registry";
import { readMetaInSandbox } from "./runtime/sandbox";
import { META_LIMITS, validateWidgetMeta, widgetDisplayName } from "./widgetMeta";

const SHIPPED_LOCALES = ["de", "en", "es", "fr"];

describe("validateWidgetMeta", () => {
  it("accepts a full meta and rebuilds it", () => {
    const meta = validateWidgetMeta({
      name: { en: "Chart", de: "Diagramm" },
      description: { en: "A series." },
      options: {
        mark: { label: { en: "Type" }, values: { bar: { en: "Bar" } } },
      },
    });
    expect(meta?.name.de).toBe("Diagramm");
    expect(meta?.options?.mark.values?.bar.en).toBe("Bar");
  });

  it("rejects meta with no usable name", () => {
    expect(validateWidgetMeta({ description: { en: "no name" } })).toBeNull();
    expect(validateWidgetMeta({ name: {} })).toBeNull();
    expect(validateWidgetMeta({ name: "Chart" })).toBeNull();
    expect(validateWidgetMeta(null)).toBeNull();
    expect(validateWidgetMeta("Chart")).toBeNull();
  });

  it("drops entries whose locale tag is not a language tag", () => {
    const meta = validateWidgetMeta({
      name: {
        en: "Chart",
        "<script>": "x",
        "": "y",
        [`${"a".repeat(50)}`]: "z",
        de_AT: "underscores are not a tag separator",
      },
    });
    expect(Object.keys(meta?.name ?? {})).toEqual(["en"]);
  });

  it("drops non-string values rather than coercing them", () => {
    const meta = validateWidgetMeta({
      name: { en: "Chart", de: { toString: "nope" }, fr: 42 },
    });
    expect(Object.keys(meta?.name ?? {})).toEqual(["en"]);
  });

  it("truncates over-long text", () => {
    const meta = validateWidgetMeta({ name: { en: "x".repeat(500) } });
    expect(meta?.name.en).toHaveLength(META_LIMITS.maxTextLength);
  });

  it("caps how many locales one string may carry", () => {
    const name: Record<string, string> = {};
    for (let i = 0; i < META_LIMITS.maxLocales + 20; i++) name[`l${i}`] = `n${i}`;
    const meta = validateWidgetMeta({ name });
    expect(Object.keys(meta?.name ?? {}).length).toBeLessThanOrEqual(META_LIMITS.maxLocales);
  });

  it("never throws, whatever it is handed", () => {
    for (const input of [undefined, null, 0, "", [], { name: [] }, { options: 1 }]) {
      expect(() => validateWidgetMeta(input)).not.toThrow();
    }
  });
});

describe("localized", () => {
  const text = { en: "Chart", de: "Diagramm", "pt-BR": "Gráfico" };

  it("prefers an exact tag, then the base language", () => {
    expect(localized(text, "de")).toBe("Diagramm");
    expect(localized(text, "de-AT")).toBe("Diagramm");
    expect(localized(text, "pt-BR")).toBe("Gráfico");
  });

  it("falls back to English, then to whatever was supplied", () => {
    expect(localized(text, "ja")).toBe("Chart");
    expect(localized({ de: "Nur Deutsch" }, "ja")).toBe("Nur Deutsch");
    expect(localized(undefined, "en")).toBeUndefined();
  });

  it("falls back to the type id when a module ships no name", () => {
    expect(widgetDisplayName(null, "gantt", "en")).toBe("gantt");
  });
});

describe("the built-ins name themselves", () => {
  it.each(BUILTIN_WIDGET_TYPES)("%s declares valid meta", async (type) => {
    const result = await readMetaInSandbox(builtinWidgetSource(type) as string);
    expect(result.ok, `meta read failed: ${JSON.stringify(result)}`).toBe(true);
    if (!result.ok) return;

    const meta = validateWidgetMeta(result.value);
    expect(meta, `${type} has no valid meta`).not.toBeNull();

    // Every language the app ships, so no viewer sees a raw type id.
    for (const locale of SHIPPED_LOCALES) {
      expect(meta?.name[locale], `${type} has no ${locale} name`).toBeTruthy();
      expect(meta?.description?.[locale], `${type} has no ${locale} description`).toBeTruthy();
    }
  });

  it.each(BUILTIN_WIDGET_TYPES)("%s labels each of its own options", async (type) => {
    const result = await readMetaInSandbox(builtinWidgetSource(type) as string);
    if (!result.ok) throw new Error("meta read failed");
    const meta = validateWidgetMeta(result.value);

    for (const [key, option] of Object.entries(meta?.options ?? {})) {
      for (const locale of SHIPPED_LOCALES) {
        expect(option.label[locale], `${type}.${key} has no ${locale} label`).toBeTruthy();
      }
      for (const [value, label] of Object.entries(option.values ?? {})) {
        for (const locale of SHIPPED_LOCALES) {
          expect(label[locale], `${type}.${key}=${value} has no ${locale} label`).toBeTruthy();
        }
      }
    }
  });

  it("reads meta under the same bounds a render gets", async () => {
    // A module whose meta getter loops is still just a widget: bounded, not hung.
    const result = await readMetaInSandbox("const meta = { get name() { while (true) {} } };", {
      timeoutMs: 50,
    });
    expect(result.ok).toBe(false);
  });

  it("treats a module with no meta as unnamed, not broken", async () => {
    const result = await readMetaInSandbox("function render() { return null; }");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toBeNull();
    expect(validateWidgetMeta(result.value)).toBeNull();
  });
});

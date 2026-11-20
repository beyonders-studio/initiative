/**
 * Widget-supplied metadata: what a widget calls itself.
 *
 * A widget's name, its description, and the labels for its own options belong
 * to the widget, not to this app's locale files. Putting them here would mean a
 * marketplace widget could not name itself without an app release — and that a
 * second copy of the widget vocabulary sat in `dashboards.json`, drifting from
 * the registry. So a module exports `meta` alongside `render`, carrying its
 * strings in every language its author supports.
 *
 * What stays plugin-owned is what is genuinely ours: binding *source* labels (they
 * name our endpoints and are shared by every widget) and page chrome.
 *
 * Meta is untrusted input like any other widget output, so it crosses the same
 * kind of boundary a scene does — `validateWidgetMeta` rebuilds it from checked
 * parts rather than trusting the shape.
 */

import { caps, charsets } from "@/contract/manifest.contract.json";

/** Language code → text. No locale is required: resolution falls back through
 *  the base language, then English, then whatever the widget did supply, so a
 *  widget that ships one language still renders everywhere. */
export type LocalizedText = Record<string, string>;

export interface WidgetOptionMeta {
  label: LocalizedText;
  /** Label per allowed value. The *values* themselves are the backend's
   *  (`WIDGET_SPECS[...].options`); only how they read is the widget's. */
  values?: Record<string, LocalizedText>;
}

export interface WidgetMeta {
  name: LocalizedText;
  description?: LocalizedText;
  options?: Record<string, WidgetOptionMeta>;
}

/**
 * What this trims by, read from the vendored plugin-kit contract.
 *
 * The server validates the same meta in Python over catalog content, and the
 * two cannot call each other — but they must trim identically, or a widget is
 * accepted by the catalog and then re-rendered differently here. Both read
 * these numbers rather than each holding a copy.
 *
 * Refresh the vendored contract with `backend/scripts/refresh_plugin_kit.py`.
 */
export const META_LIMITS = {
  maxTextLength: caps.textLength,
  maxDescriptionLength: caps.widgetDescriptionLength,
  /** Languages one string may be supplied in. Generous — the cap only stops a
   *  module from shipping a dictionary. */
  maxLocales: caps.locales,
  maxOptions: caps.widgetOptions,
  maxValuesPerOption: caps.valuesPerOption,
  /** `en`, `en-GB`, `pt-BR` — a language tag, not free text. */
  maxLocaleTagLength: caps.localeTagLength,
} as const;

// --- validation ------------------------------------------------------------

const LOCALE_TAG_CHARS = charsets.localeTag;

/** An explicit character check rather than a pattern: the set of things a
 *  language tag may contain is short enough to state outright. */
const isLocaleTag = (value: string): boolean => {
  if (!value || value.length > META_LIMITS.maxLocaleTagLength) return false;
  for (const character of value) {
    if (!LOCALE_TAG_CHARS.includes(character)) return false;
  }
  return true;
};

const localizedText = (raw: unknown, maxLength: number): LocalizedText | null => {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const out: LocalizedText = {};
  let count = 0;
  for (const [tag, value] of Object.entries(raw as Record<string, unknown>)) {
    if (++count > META_LIMITS.maxLocales) break;
    if (!isLocaleTag(tag) || typeof value !== "string") continue;
    const text = value.trim().slice(0, maxLength);
    if (text) out[tag] = text;
  }
  return Object.keys(out).length ? out : null;
};

/**
 * Rebuild a widget's meta from validated parts, or `null` if it has no usable
 * name. A widget without meta is not an error — the caller falls back to the
 * type id — so this never throws.
 */
export function validateWidgetMeta(raw: unknown): WidgetMeta | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const source = raw as Record<string, unknown>;

  const name = localizedText(source.name, META_LIMITS.maxTextLength);
  if (!name) return null;

  const meta: WidgetMeta = { name };

  const description = localizedText(source.description, META_LIMITS.maxDescriptionLength);
  if (description) meta.description = description;

  if (
    typeof source.options === "object" &&
    source.options !== null &&
    !Array.isArray(source.options)
  ) {
    const options: Record<string, WidgetOptionMeta> = {};
    let optionCount = 0;
    for (const [key, rawOption] of Object.entries(source.options as Record<string, unknown>)) {
      if (++optionCount > META_LIMITS.maxOptions) break;
      if (typeof rawOption !== "object" || rawOption === null) continue;
      const option = rawOption as Record<string, unknown>;
      const label = localizedText(option.label, META_LIMITS.maxTextLength);
      if (!label) continue;

      const entry: WidgetOptionMeta = { label };
      if (typeof option.values === "object" && option.values !== null) {
        const values: Record<string, LocalizedText> = {};
        let valueCount = 0;
        for (const [value, rawLabel] of Object.entries(option.values as Record<string, unknown>)) {
          if (++valueCount > META_LIMITS.maxValuesPerOption) break;
          const valueLabel = localizedText(rawLabel, META_LIMITS.maxTextLength);
          if (valueLabel) values[value] = valueLabel;
        }
        if (Object.keys(values).length) entry.values = values;
      }
      options[key] = entry;
    }
    if (Object.keys(options).length) meta.options = options;
  }

  return meta;
}

// --- resolution ------------------------------------------------------------

/**
 * Pick the best string for a language.
 *
 * `de-AT` → `de-AT`, then `de`, then `en`, then whatever the widget shipped —
 * so a widget that supports one language is still readable to everyone, and one
 * that supports many needs no coordination with us.
 */
export function localized(text: LocalizedText | undefined, language: string): string | undefined {
  if (!text) return undefined;
  const base = language.split("-")[0];
  return text[language] ?? text[base] ?? text.en ?? Object.values(text)[0] ?? undefined;
}

/** A widget's display name, falling back to its type id so a module with no
 *  meta still shows something stable rather than a blank tile header. */
export const widgetDisplayName = (
  meta: WidgetMeta | null | undefined,
  type: string,
  language: string
): string => localized(meta?.name, language) ?? type;

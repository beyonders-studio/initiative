/**
 * The browser's formatters, each built once per locale and options.
 *
 * Building an `Intl` formatter costs far more than using one, and a list that
 * formats a date on every row would otherwise build one per row: on a board it
 * was the largest single cost of drawing the cards. `toLocaleString`,
 * `toLocaleDateString`, `toLocaleTimeString` and `localeCompare` with a locale
 * or options build one on every call too, so code formats through these
 * instead (the `one-formatter` Biome rule holds it to that).
 *
 * The reader's 12/24-hour choice and language are part of the options and the
 * locale, so a changed choice reaches the next call.
 */

const formatters = new Map<string, unknown>();

const once = <T>(kind: string, locale: unknown, options: object | undefined, build: () => T): T => {
  const key = `${kind}|${JSON.stringify(locale ?? null)}|${JSON.stringify(options ?? null)}`;
  let formatter = formatters.get(key) as T | undefined;
  if (formatter === undefined) {
    formatter = build();
    formatters.set(key, formatter);
  }
  return formatter;
};

type Locale = Intl.LocalesArgument;

export const dateTimeFormat = (locale?: Locale, options?: Intl.DateTimeFormatOptions) =>
  // biome-ignore lint/plugin: built here, once per locale and options
  once("date", locale, options, () => new Intl.DateTimeFormat(locale, options));

export const numberFormat = (locale?: Locale, options?: Intl.NumberFormatOptions) =>
  // biome-ignore lint/plugin: built here, once per locale and options
  once("number", locale, options, () => new Intl.NumberFormat(locale, options));

export const listFormat = (locale?: Locale, options?: Intl.ListFormatOptions) =>
  // biome-ignore lint/plugin: built here, once per locale and options
  once("list", locale, options, () => new Intl.ListFormat(locale, options));

export const collator = (locale?: Locale, options?: Intl.CollatorOptions) =>
  // biome-ignore lint/plugin: built here, once per locale and options
  once("collator", locale, options, () => new Intl.Collator(locale, options));

export const displayNames = (locale: Locale, options: Intl.DisplayNamesOptions) =>
  once("names", locale, options, () => new Intl.DisplayNames(locale, options));

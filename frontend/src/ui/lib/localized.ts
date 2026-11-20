/** Text in each language it is written in, by language code. */
export type LocalizedText = Readonly<Record<string, string>>;

/**
 * Text in `language`: `de-AT`, then `de`, then English, then whatever it was
 * written in, so text written in one language is still readable to everyone.
 */
export const localized = (
  text: LocalizedText | null | undefined,
  language: string
): string | undefined => {
  if (!text) return undefined;
  return text[language] ?? text[language.split("-")[0]] ?? text.en ?? Object.values(text)[0];
};

import Typo from "typo-js";

import { host } from "@/ui/host";

let dictionary: Typo | null = null;
let initPromise: Promise<void> | null = null;

/**
 * Initialize the spell checker with the dictionary the host supplies, loaded on
 * first use and kept for the session. Without one the checker stays off.
 */
export async function initSpellCheck(): Promise<void> {
  const load = host.spellCheckDictionary;
  if (dictionary || !load) return;

  if (initPromise) {
    return initPromise;
  }

  initPromise = (async () => {
    try {
      const { aff, dic } = await load();
      dictionary = new Typo("en_US", aff, dic);
    } catch (error) {
      console.error("Failed to initialize spell checker:", error);
      initPromise = null;
      throw error;
    }
  })();

  return initPromise;
}

/**
 * Check if a word is spelled correctly.
 * Returns true if the word is correct or if the dictionary isn't loaded.
 */
export function checkWord(word: string): boolean {
  if (!dictionary) return true;
  return dictionary.check(word);
}

/**
 * Get spelling suggestions for a misspelled word.
 * @param word The misspelled word
 * @param limit Maximum number of suggestions to return (default: 5)
 * @returns Array of suggested corrections
 */
export function getSuggestions(word: string, limit = 5): string[] {
  if (!dictionary) return [];
  const suggestions = dictionary.suggest(word);
  return suggestions.slice(0, limit);
}

/**
 * Check if the spell checker is ready to use.
 */
export function isSpellCheckReady(): boolean {
  return dictionary !== null;
}

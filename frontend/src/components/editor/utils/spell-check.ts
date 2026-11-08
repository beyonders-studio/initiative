import Typo from "typo-js";

// CDN URLs for English dictionary files
const AFF_URL = "https://cdn.jsdelivr.net/npm/dictionary-en@3.2.0/index.aff";
const DIC_URL = "https://cdn.jsdelivr.net/npm/dictionary-en@3.2.0/index.dic";

let dictionary: Typo | null = null;
let initPromise: Promise<void> | null = null;

/**
 * Initialize the spell checker by loading dictionary files from CDN.
 * This is lazy-loaded on first use and cached for the session.
 */
export async function initSpellCheck(): Promise<void> {
  if (dictionary) return;

  if (initPromise) {
    return initPromise;
  }

  initPromise = (async () => {
    try {
      const [affResponse, dicResponse] = await Promise.all([fetch(AFF_URL), fetch(DIC_URL)]);

      if (!affResponse.ok || !dicResponse.ok) {
        throw new Error("Failed to fetch dictionary files");
      }

      const [affData, dicData] = await Promise.all([affResponse.text(), dicResponse.text()]);

      dictionary = new Typo("en_US", affData, dicData);
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

import type { HelpIndexEntry } from "@/api/generated/initiativeAPI.schemas";
import { commandFilter } from "@/ui/lib/fuzzyMatch";

/**
 * Searching the user guide's index, which the server serves at its own
 * version (`GET /help/index`).
 *
 * Each word is matched on its own through the app's own matcher, typos
 * forgiven, so a question typed as a sentence finds the entries that share most
 * of its words. An entry has to match most of the words, and the results are
 * the ones scoring within half of the best, rather than a fixed number of them.
 */

/** Words that say nothing about what is wanted. The index is the English user guide. */
const IGNORED = new Set([
  "a",
  "an",
  "and",
  "are",
  "be",
  "can",
  "can't",
  "do",
  "does",
  "doesn't",
  "don't",
  "for",
  "how",
  "i",
  "i'm",
  "in",
  "is",
  "isn't",
  "it",
  "it's",
  "me",
  "my",
  "of",
  "on",
  "or",
  "the",
  "this",
  "to",
  "what",
  "why",
  "with",
]);

/** How much a word found in each part of an entry counts. */
const WEIGHTS = [
  ["title", 3],
  ["section", 1],
  ["snippet", 1],
] as const;

/**
 * What a word found in a part of an entry is worth. `commandFilter` scores a
 * word that is in the text 0.8 and up, and one a typo or two from one of its
 * words below 0.1; a typo counts half. Between those it scores the word's
 * letters scattered through the text in order, which nearly any paragraph
 * has, so that is no match here.
 */
const worth = (score: number): number =>
  score >= 0.8 ? score : score > 0 && score < 0.1 ? 0.5 : 0;

const termsOf = (text: string): string[] =>
  text
    .toLowerCase()
    .split(/[^\p{L}\p{N}']+/u)
    .filter((word) => word.length > 1 && !IGNORED.has(word));

/** A search over these entries. */
export const helpSearch =
  (entries: HelpIndexEntry[]) =>
  (text: string): HelpIndexEntry[] => {
    const terms = termsOf(text);
    if (terms.length === 0) return [];
    const needed = Math.ceil(terms.length * 0.6);
    const ranked: { entry: HelpIndexEntry; rank: number }[] = [];
    for (const entry of entries) {
      let score = 0;
      let hits = 0;
      for (const term of terms) {
        let found = 0;
        for (const [field, weight] of WEIGHTS) {
          found += weight * worth(commandFilter(entry[field], term));
        }
        if (found > 0) {
          hits += 1;
          score += found;
        }
      }
      if (hits >= needed) ranked.push({ entry, rank: (score * hits) / terms.length });
    }
    ranked.sort((a, b) => b.rank - a.rank);
    const best = ranked[0]?.rank ?? 0;
    return ranked.filter((match) => match.rank >= best / 2).map((match) => match.entry);
  };

/**
 * What a page is about, from its route template: the last two things it names,
 * a parameter by what it holds (`$initiativeId` is an initiative) and the
 * one-letter prefixes (`/c/`, `/i/`) left out, since its parameter names it.
 */
export const pageTerms = (routeTemplate: string): string =>
  routeTemplate
    .split("/")
    .map((segment) => (segment.startsWith("$") ? segment.slice(1).replace(/Id$/, "") : segment))
    .filter((segment) => segment.length > 1)
    .slice(-2)
    .join(" ");

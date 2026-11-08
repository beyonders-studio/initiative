import Fuse from "fuse.js";

import type { HelpIndexEntry } from "@/api/generated/initiativeAPI.schemas";

/**
 * Searching the user guide's index, which the server serves at its own
 * version (`GET /help/index`).
 *
 * Each word is matched on its own, typos forgiven, so a question typed as a
 * sentence finds the entries that share most of its words. An entry has to
 * match most of the words, and the results are the ones scoring within half of
 * the best, rather than a fixed number of them.
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

const termsOf = (text: string): string[] =>
  text
    .toLowerCase()
    .split(/[^\p{L}\p{N}']+/u)
    .filter((word) => word.length > 1 && !IGNORED.has(word));

/** A search over these entries. */
export const helpSearch = (entries: HelpIndexEntry[]) => {
  const fuse = new Fuse(entries, {
    keys: [
      { name: "title", weight: 3 },
      { name: "section", weight: 1 },
      { name: "snippet", weight: 1 },
    ],
    includeScore: true,
    ignoreLocation: true,
    threshold: 0.3,
    minMatchCharLength: 2,
  });
  return (text: string): HelpIndexEntry[] => {
    const terms = termsOf(text);
    if (terms.length === 0) return [];
    const found = new Map<number, { entry: HelpIndexEntry; score: number; hits: number }>();
    for (const term of terms) {
      for (const { item, refIndex, score = 1 } of fuse.search(term)) {
        const held = found.get(refIndex) ?? { entry: item, score: 0, hits: 0 };
        held.score += 1 - score;
        held.hits += 1;
        found.set(refIndex, held);
      }
    }
    const needed = Math.ceil(terms.length * 0.6);
    const ranked = [...found.values()]
      .filter((match) => match.hits >= needed)
      .map((match) => ({ entry: match.entry, rank: (match.score * match.hits) / terms.length }))
      .sort((a, b) => b.rank - a.rank);
    const best = ranked[0]?.rank ?? 0;
    return ranked.filter((match) => match.rank >= best / 2).map((match) => match.entry);
  };
};

/** What a page is about, from its route template: its named segments, ids left out. */
export const pageTerms = (routeTemplate: string): string =>
  routeTemplate
    .split("/")
    .filter((segment) => segment && !segment.startsWith("$"))
    .join(" ");

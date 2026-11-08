/**
 * Fuzzy matching function compatible with cmdk's `filter` prop.
 *
 * Returns 0 for no match, 0.1–1.0 for matches with scoring bonuses for:
 * - Exact substring match (highest)
 * - Consecutive character matches
 * - Word boundary matches (after space/hyphen/underscore)
 * - Start-of-string matches
 */

function fuzzyScore(text: string, search: string): number {
  const lowerText = text.toLowerCase();
  const lowerSearch = search.toLowerCase();

  // Exact substring match — highest score
  if (lowerText.includes(lowerSearch)) {
    // Bonus if it starts at the beginning
    if (lowerText.startsWith(lowerSearch)) return 1.0;
    // Bonus if it starts at a word boundary
    const idx = lowerText.indexOf(lowerSearch);
    const charBefore = lowerText[idx - 1];
    if (charBefore === " " || charBefore === "-" || charBefore === "_") return 0.9;
    return 0.8;
  }

  // Subsequence match with scoring
  let searchIdx = 0;
  let score = 0;
  let consecutive = 0;

  for (let i = 0; i < lowerText.length && searchIdx < lowerSearch.length; i++) {
    if (lowerText[i] === lowerSearch[searchIdx]) {
      consecutive++;

      // Word boundary bonus
      if (i === 0) {
        score += 1.5;
      } else {
        const prev = lowerText[i - 1];
        if (prev === " " || prev === "-" || prev === "_") {
          score += 1.2;
        } else if (consecutive > 1) {
          score += 1.0;
        } else {
          score += 0.5;
        }
      }

      searchIdx++;
    } else {
      consecutive = 0;
    }
  }

  // All search characters must be found
  if (searchIdx < lowerSearch.length) return 0;

  // Normalize: ratio of matched chars, weighted by positional bonuses
  const maxPossibleScore = lowerSearch.length * 1.5;
  const normalized = score / maxPossibleScore;

  // Scale to 0.1–0.7 range (below substring match scores)
  return Math.max(0.1, Math.min(0.7, normalized * 0.7));
}

/**
 * cmdk-compatible filter function.
 * Checks the `value` string and all `keywords`, returns the best score.
 */
export function commandFilter(value: string, search: string, keywords?: string[]): number {
  const valueScore = fuzzyScore(value, search);
  if (!keywords || keywords.length === 0) return valueScore;

  let best = valueScore;
  for (const kw of keywords) {
    if (kw) {
      const kwScore = fuzzyScore(kw, search);
      if (kwScore > best) best = kwScore;
    }
  }
  return best;
}

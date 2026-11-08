/**
 * Fuzzy matching function compatible with cmdk's `filter` prop.
 *
 * Returns 0 for no match, 0.1–1.0 for matches with scoring bonuses for:
 * - The whole text (highest), then the text's start
 * - Exact substring match
 * - Consecutive character matches
 * - Word boundary matches (after space/hyphen/underscore)
 * - Start-of-string matches
 *
 * Below those, under 0.1, it forgives typos: see `typoScore`.
 */

/** How many letters a searched word may be off by: none below four letters,
 *  one up to seven, two from eight. */
const typosAllowed = (length: number): number => (length < 4 ? 0 : length < 8 ? 1 : 2);

/** Letters apart, counting a wrong, missing, extra or swapped letter as one. */
function editDistance(a: string, b: string): number {
  const d = Array.from({ length: a.length + 1 }, (_, i) =>
    Array.from({ length: b.length + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0))
  );
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      d[i][j] = Math.min(
        d[i - 1][j] + 1,
        d[i][j - 1] + 1,
        d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
      );
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
      }
    }
  }
  return d[a.length][b.length];
}

/**
 * A match for a search that is in the text only with typos, or only in pieces.
 *
 * Each word of the search must be in the text, or within its allowance of the
 * start of one of the text's words, so a half-typed word with a slip in it
 * still finds what it was heading for. Scores below every in-order match, and
 * lower the more letters were off.
 */
function typoScore(text: string, search: string): number {
  const words = text.split(/[\s\-_/.]+/).filter(Boolean);
  let edits = 0;
  for (const token of search.split(/\s+/).filter(Boolean)) {
    if (text.includes(token)) continue;
    const allowed = typosAllowed(token.length);
    if (allowed === 0) return 0;
    let best = allowed + 1;
    for (const word of words) {
      const longest = Math.min(word.length, token.length + allowed);
      for (let length = Math.max(1, token.length - allowed); length <= longest; length++) {
        best = Math.min(best, editDistance(token, word.slice(0, length)));
      }
    }
    if (best > allowed) return 0;
    edits += best;
  }
  return Math.max(0.01, 0.09 - 0.02 * edits);
}

/** Lower case, with a hyphen or underscore read as the space it stands for. */
const words = (value: string) => value.toLowerCase().replace(/[-_]/g, " ");

function fuzzyScore(text: string, search: string): number {
  const lowerText = words(text);
  const lowerSearch = words(search);

  // Exact substring match — highest score
  if (lowerText.includes(lowerSearch)) {
    // The whole text, then its start
    if (lowerText === lowerSearch) return 1.0;
    if (lowerText.startsWith(lowerSearch)) return 0.95;
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

  // Every search character in order, or the search forgiven its typos.
  if (searchIdx < lowerSearch.length) return typoScore(lowerText, lowerSearch);

  // Normalize: ratio of matched chars, weighted by positional bonuses
  const maxPossibleScore = lowerSearch.length * 1.5;
  const normalized = score / maxPossibleScore;

  // Scale to 0.1–0.7 range (below substring match scores)
  return Math.max(0.1, Math.min(0.7, normalized * 0.7));
}

/**
 * cmdk-compatible filter function.
 * Checks the `value` string and all `keywords`, returns the best score. A
 * keyword describes the thing rather than naming it, so it ranks below the
 * same match in the value.
 */
export function commandFilter(value: string, search: string, keywords?: string[]): number {
  let best = fuzzyScore(value, search);
  for (const kw of keywords ?? []) {
    if (kw) best = Math.max(best, fuzzyScore(kw, search) * 0.9);
  }
  return best;
}

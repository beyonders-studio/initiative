/**
 * What a tile may say about where its data came from.
 *
 * A statement says which datasets it read, which the server answers with; there
 * is no id to resolve and nothing further to disclose, because a query returns
 * what its reader already reaches.
 */

/** One fact about where a widget's data came from, as the line and popover
 *  draw it. */
export interface ProvenanceChip {
  key: string;
  label: string;
}

/** The datasets a statement read, as chips. Answered by the server rather than
 *  parsed here: what a statement resolves to is the validator's answer, and a
 *  second reading of the same SQL could only disagree with it. */
export const queryScope = (relations: readonly string[]): ProvenanceChip[] =>
  relations.map((relation) => ({ key: relation, label: relation }));

/**
 * Range selection for card grids — the shift-click gesture shared by every list
 * that turns its cards into checkboxes (projects, files, counter groups,
 * dashboards).
 *
 * The rules are the ones people already know from file managers and mail
 * clients: a plain click flips one card and becomes the *anchor*; a shift-click
 * paints every card between that anchor and the clicked one.
 */

/** Items between two ids in the visible order, inclusive of both ends. */
export function itemsInRange<T extends { id: number }>(
  items: readonly T[],
  fromId: number,
  toId: number
): T[] {
  const from = items.findIndex((item) => item.id === fromId);
  const to = items.findIndex((item) => item.id === toId);
  if (from === -1 || to === -1) {
    return [];
  }
  return from <= to ? items.slice(from, to + 1) : items.slice(to, from + 1);
}

export interface CardClickOptions<T> {
  /** The cards in the order they are rendered — the axis a range runs along. */
  items: readonly T[];
  /** The last card clicked, or null when nothing has been clicked yet. */
  anchorId: number | null;
  isSelected: (id: number) => boolean;
  /** Shift was held. */
  extend?: boolean;
}

/** The items a click adds to the selection and the ids it takes out. */
export interface SelectionChange<T> {
  add: T[];
  remove: number[];
}

/**
 * Resolve one click on a selectable card into the selection change it makes.
 *
 * A shift-click paints the run from the anchor to the clicked card with the
 * *anchor's* state, so the same gesture both selects a run and clears one:
 * shift-clicking from a selected anchor selects everything it reaches, and
 * shift-clicking from one you just deselected clears them instead. Without a
 * usable anchor — nothing clicked yet, or a range that spans two lists (e.g.
 * the anchor was left behind on another page) — it falls back to a plain toggle.
 */
export function resolveCardClick<T extends { id: number }>(
  item: T,
  { items, anchorId, isSelected, extend }: CardClickOptions<T>
): SelectionChange<T> {
  const plainToggle = (): SelectionChange<T> =>
    isSelected(item.id) ? { add: [], remove: [item.id] } : { add: [item], remove: [] };

  if (!extend || anchorId === null || anchorId === item.id) {
    return plainToggle();
  }

  const range = itemsInRange(items, anchorId, item.id);
  if (range.length === 0) {
    return plainToggle();
  }

  return isSelected(anchorId)
    ? { add: range, remove: [] }
    : { add: [], remove: range.map((ranged) => ranged.id) };
}

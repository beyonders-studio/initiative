import { describe, expect, it } from "vitest";

import { itemsInRange, resolveCardClick } from "./selectionRange";

const items = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }];

describe("itemsInRange", () => {
  it("returns the inclusive slice in either direction, or nothing when an end is missing", () => {
    expect(itemsInRange(items, 2, 4).map((i) => i.id)).toEqual([2, 3, 4]);
    expect(itemsInRange(items, 4, 2).map((i) => i.id)).toEqual([2, 3, 4]);
    expect(itemsInRange(items, 3, 3).map((i) => i.id)).toEqual([3]);
    expect(itemsInRange(items, 2, 99)).toEqual([]);
    expect(itemsInRange(items, 99, 2)).toEqual([]);
  });
});

describe("resolveCardClick", () => {
  const click = (id: number, selected: number[], anchorId: number | null, extend?: boolean) =>
    resolveCardClick(
      { id },
      { items, anchorId, isSelected: (candidate) => selected.includes(candidate), extend }
    );

  it("toggles a single card when shift is not held", () => {
    expect(click(3, [], null)).toEqual({ add: [{ id: 3 }], remove: [] });
    expect(click(3, [3], 3)).toEqual({ add: [], remove: [3] });
  });

  it("selects the whole run when shift-clicking from a selected anchor", () => {
    const { add, remove } = click(4, [2], 2, true);
    expect(add.map((i) => i.id)).toEqual([2, 3, 4]);
    expect(remove).toEqual([]);
  });

  it("clears the run when shift-clicking from an unselected anchor", () => {
    const { add, remove } = click(1, [1, 2], 3, true);
    expect(add).toEqual([]);
    expect(remove).toEqual([1, 2, 3]);
  });

  it("falls back to a plain toggle without a usable anchor", () => {
    // Nothing clicked yet…
    expect(click(2, [], null, true)).toEqual({ add: [{ id: 2 }], remove: [] });
    // …the anchor is the card itself…
    expect(click(2, [2], 2, true)).toEqual({ add: [], remove: [2] });
    // …or the anchor was left behind on another page.
    expect(click(2, [], 99, true)).toEqual({ add: [{ id: 2 }], remove: [] });
  });
});

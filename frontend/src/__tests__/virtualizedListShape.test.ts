/**
 * The shape every virtualized list in the app has to keep.
 *
 * Two facts about layout that jsdom cannot measure, and that broke the pages
 * in ways only a person scrolling would notice. Both are asserted against the
 * source, which is also where they regress.
 *
 * 1. **The gap lives inside the measured element.** `measureElement` reads an
 *    item's own box, so a flex `gap` between items is invisible to it: the
 *    virtualizer's model comes out shorter than the real list by the gap on
 *    every row (measured: 32px adrift over three rows at `gap-4`), and
 *    everything below sits in the wrong place.
 * 2. **The list measures where it starts.** Read during render the ref is
 *    still null, and every offset comes out short by the height of the
 *    toolbar and filters above it.
 *
 * The posts board virtualizes in the page; a collection's grid and timeline do
 * it through a shared row component. Both answer to the same two facts, so
 * they are asked together.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const read = (relative: string) => fs.readFileSync(path.resolve(__dirname, relative), "utf-8");

/** Each virtualized list, and the constant its measured element carries. */
const LISTS = [
  {
    what: "the posts board",
    source: read("../pages/initiativeTools/posts/PostsPage.tsx"),
    gap: "CARD_GAP",
  },
  {
    what: "a collection's wall",
    source: read("../components/files/collections/VirtualRows.tsx"),
    gap: "ROW_GAP",
  },
];

describe("a virtualized list", () => {
  it.each(LISTS)(
    "$what keeps the row spacing inside the element it measures",
    ({ source, gap }) => {
      const attributes = /<div ref={listRef}([^>]*)>/.exec(source)?.[1];

      expect(attributes, "the virtualized list container moved").toBeDefined();
      expect(attributes ?? "").not.toMatch(/\bgap-\d/);
      // The measured wrapper is what carries it instead.
      expect(source).toMatch(
        new RegExp(String.raw`ref={virtualizer\.measureElement}\s*\n\s*className={${gap}}`)
      );
    }
  );

  it.each(LISTS)(
    "$what measures where the list starts instead of assuming the top",
    ({ source }) => {
      expect(source).toContain("useLayoutEffect");
      expect(source).toContain("scrollMargin: listOffset");
    }
  );
});

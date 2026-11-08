/**
 * The app shell scrolls; it does not also decide how wide a page is.
 *
 * Those two jobs were one element once, and both symptoms followed from it.
 * A scrollbar renders at the edge of its own scrollport, so a scroller that
 * was also `container mx-auto` put the bar beside the centred column instead
 * of down the side of the app. And `overflow-y: auto` does not stay on one
 * axis — with the other left `visible`, CSS computes that one to `auto` too,
 * which quietly made the shell a horizontal scroller that anything overrunning
 * anywhere could drag sideways.
 *
 * Asserted against the source because jsdom does no layout, which is why
 * neither was visible to the suite.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SHELL = path.resolve(__dirname, "./_serverRequired/_authenticated.tsx");

const shellSource = (): string => fs.readFileSync(SHELL, "utf-8");

/** The `<main>` carrying `data-app-scroll`, as written. */
const scrollerTag = (): string => {
  const match = shellSource().match(/<main\b[^>]*data-app-scroll[^>]*>/s);
  if (!match) throw new Error("no [data-app-scroll] <main> in the app shell");
  return match[0];
};

/** The viewport-sized box the whole app sits in — the one carrying `overflow-clip`. */
const shellTag = (): string => {
  // Sized to the viewport, the dynamic one where the browser has it.
  const match = shellSource().match(
    /<div\b[^>]*\bh-(?:screen|dvh|app)\b[^>]*\boverflow-clip\b[^>]*>/s
  );
  if (!match) throw new Error("no viewport-sized overflow-clip shell in the app layout");
  return match[0];
};

/** The first element inside that `<main>` — the one holding the page width. */
const contentTag = (): string => {
  const after = shellSource().split(scrollerTag())[1] ?? "";
  const match = after.match(/<div\b[^>]*>/s);
  if (!match) throw new Error("the app scroller has no content wrapper");
  return match[0];
};

describe("the app scroller", () => {
  it("scrolls vertically and refuses the other axis", () => {
    const tag = scrollerTag();
    expect(tag).toContain("overflow-y-auto");
    // Not `overflow-x-auto`: wide content owns its own scroller (the tool
    // rail, every table), so the shell never offers a horizontal bar.
    expect(tag).toContain("overflow-x-clip");
  });

  it("is not also the thing that sets the page width", () => {
    const tag = scrollerTag();
    expect(
      /\bcontainer\b/.test(tag),
      "the scroller carries `container`, which puts its scrollbar beside the centred column"
    ).toBe(false);
    expect(/\bmx-auto\b/.test(tag)).toBe(false);
  });

  it("still spans the row it sits in", () => {
    expect(scrollerTag()).toMatch(/\bflex-1\b/);
  });

  // An absolutely positioned descendant with no positioned ancestor -- every
  // `sr-only` label -- is laid out against the document, not the scroller, at
  // its in-flow offset from the top of the page. Deep in a long comment thread
  // that offset is below the window, the document grows to fit it, and any
  // scroll request then moves the whole app rather than the page. Measured:
  // fifteen comments, a 3057px document in a 900px window.
  it("is the containing block for what it scrolls", () => {
    expect(scrollerTag()).toMatch(/\brelative\b/);
  });

  it("clips at a shell that is itself positioned, so nothing escapes to the document", () => {
    expect(shellTag()).toMatch(/\brelative\b/);
  });

  // Taking the width off the scroller is only half of it: the width has to
  // land somewhere, or every page goes edge to edge.
  it("hands the page width to the wrapper inside it", () => {
    const tag = contentTag();
    expect(tag).toMatch(/\bcontainer\b/);
    expect(tag).toMatch(/\bmx-auto\b/);
  });

  // That wrapper sits between the scrollport and the page, so it has to pass a
  // height through without capping one. `h-full` would fix it at the
  // scrollport and a long page would spill past its own bottom padding;
  // `min-h-full` alone leaves `height: auto`, and a page's own `h-full` would
  // resolve against that and become auto. A grid row is definite either way.
  it("passes a height through to full-height pages", () => {
    const tag = contentTag();
    expect(tag).toMatch(/\bmin-h-full\b/);
    // `(?<![-\w])` so `min-h-full` is not read as `h-full`.
    expect(tag).not.toMatch(/(?<![-\w])h-full\b/);
    expect(tag).toMatch(/\bgrid\b/);
    expect(tag).toMatch(/grid-rows-\[1fr\]/);
  });

  // A grid item's automatic minimum is its content's minimum. Without a floor,
  // a page holding something that will not wrap sized the column to that, and
  // the content spilled out of a container that was still, correctly, centred.
  // Measured: a 1918px item inside a 1536px container, overflowing by 414px.
  it("floors its column so content cannot widen it", () => {
    expect(contentTag()).toMatch(/grid-cols-\[minmax\(0,1fr\)\]/);
  });
});

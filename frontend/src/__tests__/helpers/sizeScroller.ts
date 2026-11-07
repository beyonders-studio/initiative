import { afterAll, beforeAll } from "vitest";

/**
 * Give a virtualized list's scroller a height for a file's tests.
 *
 * The virtualizer mounts only the rows that fit in its scroller, which it
 * measures by `clientHeight`. jsdom lays nothing out, so every element is 0
 * tall and no row would mount.
 */
export const sizeScroller = (isScroller: (element: HTMLElement) => boolean, height: number) => {
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get(this: HTMLElement) {
        return isScroller(this) ? height : 0;
      },
    });
  });
  afterAll(() => {
    Reflect.deleteProperty(HTMLElement.prototype, "clientHeight");
  });
};

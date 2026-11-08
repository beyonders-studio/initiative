import { afterAll, beforeAll } from "vitest";

/**
 * Lay out a virtualized list for a file's tests.
 *
 * jsdom lays nothing out: every element is 0 tall and none can be scrolled, so
 * a virtualizer mounts nothing, or, measuring every row at 0, all of them.
 * Here the scroller is `height` tall, its content as tall as the virtualizer
 * sizes its first child, each row the virtualizer measures (`data-index`)
 * `rowHeight` tall, and `scrollTo` moves the scroller.
 */
export const layOutVirtualList = (
  isScroller: (element: HTMLElement) => boolean,
  { height, rowHeight }: { height: number; rowHeight: number }
) => {
  const sizes: Record<string, (element: HTMLElement) => number> = {
    clientHeight: (element) => (isScroller(element) ? height : 0),
    offsetHeight: (element) => (element.dataset.index === undefined ? 0 : rowHeight),
    scrollHeight: (element) =>
      isScroller(element)
        ? Math.max(
            height,
            Number.parseFloat(
              (element.firstElementChild as HTMLElement | null)?.style.height ?? ""
            ) || 0
          )
        : 0,
  };
  beforeAll(() => {
    for (const [name, size] of Object.entries(sizes)) {
      Object.defineProperty(HTMLElement.prototype, name, {
        configurable: true,
        get(this: HTMLElement) {
          return size(this);
        },
      });
    }
    HTMLElement.prototype.scrollTo = function (this: HTMLElement, options?: ScrollToOptions) {
      this.scrollTop = options?.top ?? this.scrollTop;
      this.dispatchEvent(new Event("scroll"));
    } as HTMLElement["scrollTo"];
  });
  afterAll(() => {
    for (const name of [...Object.keys(sizes), "scrollTo"]) {
      Reflect.deleteProperty(HTMLElement.prototype, name);
    }
  });
};

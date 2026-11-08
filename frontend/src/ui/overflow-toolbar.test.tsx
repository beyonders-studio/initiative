import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  OverflowMenuItem,
  OverflowSubmenu,
  OverflowToolbar,
  type OverflowToolbarItem,
} from "@/ui/overflow-toolbar";

const ITEM_WIDTH = 100;

/** The measured row is the one child carrying `overflow-hidden`. */
const isRow = (el: HTMLElement) => el.classList.contains("overflow-hidden");

/**
 * jsdom lays nothing out: every element measures zero. Give the row and the
 * wrappers inside it the widths a browser would, so the shedding rule is what
 * the test exercises rather than the "nothing to read, show everything"
 * fallback. Must be in place before the first layout effect runs.
 */
const stubLayout = (
  rowWidth: number,
  widthOfItem: (el: HTMLElement) => number = () => ITEM_WIDTH
) => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (
    this: HTMLElement
  ) {
    return isRow(this) ? rowWidth : 0;
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (
    this: HTMLElement
  ) {
    const parent = this.parentElement;
    return parent && isRow(parent) ? widthOfItem(this) : 0;
  });
};

/**
 * jsdom has no ResizeObserver. This one records what each observer was asked
 * to watch, so `resize(element)` notifies only the observers actually watching
 * it — otherwise a test would pass whether or not the items are observed.
 */
const stubResizeObserver = () => {
  const watchers: { callback: ResizeObserverCallback; targets: Set<Element> }[] = [];

  vi.stubGlobal(
    "ResizeObserver",
    class {
      private entry: { callback: ResizeObserverCallback; targets: Set<Element> };
      constructor(callback: ResizeObserverCallback) {
        this.entry = { callback, targets: new Set() };
        watchers.push(this.entry);
      }
      observe(target: Element) {
        this.entry.targets.add(target);
      }
      unobserve(target: Element) {
        this.entry.targets.delete(target);
      }
      disconnect() {
        this.entry.targets.clear();
      }
    }
  );

  return (element: Element) => {
    for (const watcher of watchers) {
      if (watcher.targets.has(element)) watcher.callback([], {} as ResizeObserver);
    }
  };
};

const buildItems = (count: number): OverflowToolbarItem[] =>
  Array.from({ length: count }, (_, index) => ({
    id: `item-${index}`,
    node: <button type="button">{`Action ${index}`}</button>,
    menu: <OverflowMenuItem>{`Action ${index}`}</OverflowMenuItem>,
  }));

const renderToolbar = (items: OverflowToolbarItem[]) =>
  render(<OverflowToolbar items={items} label="Test toolbar" moreLabel="More" />);

const rowChildren = (container: HTMLElement) =>
  Array.from(container.querySelector(".overflow-hidden")?.children ?? []) as HTMLElement[];

describe("OverflowToolbar", () => {
  it("keeps every item in the row when there is no layout to measure", () => {
    const { container } = renderToolbar(buildItems(6));

    expect(rowChildren(container).filter((child) => child.hidden)).toHaveLength(0);
    expect(screen.getByRole("button", { name: "More", hidden: true })).not.toBeVisible();
  });

  it("sheds the items that do not fit, from the right", async () => {
    // Three of six 100px items fit in a 320px row (jsdom reports no gap).
    stubLayout(320);
    const { container } = renderToolbar(buildItems(6));

    await waitFor(() => {
      expect(rowChildren(container).filter((child) => child.hidden)).toHaveLength(3);
    });

    const shown = rowChildren(container).filter((child) => !child.hidden);
    expect(shown.map((child) => child.textContent)).toEqual(["Action 0", "Action 1", "Action 2"]);

    const more = screen.getByRole("button", { name: "More" });
    expect(more).toBeVisible();

    await userEvent.click(more);
    expect(await screen.findByRole("menuitem", { name: "Action 5" })).toBeInTheDocument();
  });

  it("names a shed control in the menu", async () => {
    stubLayout(100);
    renderToolbar([
      {
        id: "stays",
        node: <button type="button">Stays</button>,
        menu: <OverflowMenuItem>Stays</OverflowMenuItem>,
      },
      {
        id: "goes",
        node: <button type="button" aria-label="Rarely needed" />,
        menu: <OverflowMenuItem>Rarely needed</OverflowMenuItem>,
      },
    ]);

    await userEvent.click(await screen.findByRole("button", { name: "More" }));

    // The row shows an icon; the menu has room to say what it does.
    expect(await screen.findByRole("menuitem", { name: "Rarely needed" })).toBeInTheDocument();
  });

  it("keeps a menu-only item out of the row however wide it is", async () => {
    const items: OverflowToolbarItem[] = [
      ...buildItems(2),
      {
        id: "hidden-one",
        node: <button type="button">Rarely</button>,
        menu: <OverflowMenuItem>Rarely</OverflowMenuItem>,
        menuOnly: true,
      },
    ];

    const { container } = renderToolbar(items);

    // Two items in the row; the third is only ever reachable from the panel.
    expect(rowChildren(container)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Rarely" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(await screen.findByRole("menuitem", { name: "Rarely" })).toBeInTheDocument();
  });
});

describe("a control that changes size in place", () => {
  it("sheds it once it outgrows the row, without the row itself resizing", async () => {
    // The first item names what the caret is in, so its width follows its
    // label: narrow at first, wide once the label changes.
    let firstIsWide = false;
    const isFirst = (el: HTMLElement) => el === el.parentElement?.firstElementChild;
    const resize = stubResizeObserver();
    stubLayout(200, (el) => (isFirst(el) ? (firstIsWide ? 150 : 60) : ITEM_WIDTH));

    const { container } = renderToolbar(buildItems(2));

    // 60 + 100 fits in 200, so both stay.
    await waitFor(() => {
      expect(rowChildren(container).filter((child) => child.hidden)).toHaveLength(0);
    });

    firstIsWide = true;
    // The control grew; the row it sits in did not.
    act(() => resize(rowChildren(container)[0]));

    // 150 + 100 does not, and the row's own width never changed.
    await waitFor(() => {
      expect(rowChildren(container).filter((child) => child.hidden)).toHaveLength(1);
    });
  });
});

describe("focus around the overflow menu", () => {
  it("hands focus back to whatever was being worked on", async () => {
    stubLayout(10);
    render(
      <>
        <textarea aria-label="The grid" />
        <OverflowToolbar
          label="Test toolbar"
          moreLabel="More"
          items={[
            {
              id: "clear",
              node: <button type="button">Clear</button>,
              menu: <OverflowMenuItem>Clear</OverflowMenuItem>,
            },
          ]}
        />
      </>
    );

    const grid = screen.getByRole("textbox", { name: "The grid" });
    grid.focus();

    await userEvent.click(screen.getByRole("button", { name: "More" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Clear" }));

    // Not the `…` button: typing has to keep reaching the surface below.
    await waitFor(() => expect(grid).toHaveFocus());
  });
});

describe("the overflow menu's branches", () => {
  it("drills into a branch and back, rather than flying out beside the menu", async () => {
    // Narrower than one item: both shed, so both are in the menu.
    stubLayout(10);
    renderToolbar([
      {
        id: "stays",
        node: <button type="button">Stays</button>,
        menu: <OverflowMenuItem>Stays</OverflowMenuItem>,
      },
      {
        id: "colors",
        node: <button type="button" aria-label="Colours" />,
        menu: (
          <OverflowSubmenu id="colors" label="Colours">
            <OverflowMenuItem>Red</OverflowMenuItem>
          </OverflowSubmenu>
        ),
      },
    ]);

    await userEvent.click(await screen.findByRole("button", { name: "More" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Colours/ }));

    // The branch replaces the menu: what was above it is gone while it is open.
    expect(await screen.findByRole("menuitem", { name: "Red" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Stays" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("menuitem", { name: /Colours/ }));
    expect(await screen.findByRole("menuitem", { name: "Stays" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Red" })).not.toBeInTheDocument();
  });
});

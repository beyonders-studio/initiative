/**
 * How wide the navigation is.
 *
 * What is worth asserting is the three promises the drag makes: it never goes
 * narrower than the width the app asked for, it never takes more than half the
 * window, and what it settles on is remembered on this device — which is a
 * different thing from being remembered for this person.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { Sidebar, SidebarProvider } from "@/components/sidebar/sidebar";
import { getItem, removeItem } from "@/lib/storage";

const FLOOR = 320; // the 20rem the app shell asks for

const widthOf = () => {
  const wrapper = document.querySelector<HTMLElement>(".group\\/sidebar-wrapper");
  return wrapper?.style.getPropertyValue("--sidebar-width") ?? "";
};

// The shell's own shape: a column that cannot be folded away, which is a
// different branch of `Sidebar` from the one that can.
const setup = () =>
  render(
    <SidebarProvider style={{ "--sidebar-width": "20rem" } as React.CSSProperties}>
      <Sidebar collapsible="none">
        <div>navigation</div>
      </Sidebar>
    </SidebarProvider>
  );

/** Drag the edge by `travel` pixels and let go. */
const drag = (travel: number) => {
  const handle = screen.getByTitle("Drag to resize the sidebar");
  fireEvent.pointerDown(handle, { button: 0, clientX: FLOOR });
  fireEvent.pointerMove(window, { clientX: FLOOR + travel });
  fireEvent.pointerUp(window);
};

beforeEach(() => {
  removeItem("sidebar-width");
  // jsdom's window is 1024 wide, so half of it — the ceiling — is 512.
  window.innerWidth = 1024;
});

describe("dragging the sidebar's edge", () => {
  it("widens it, and remembers the width on this device", () => {
    setup();
    expect(widthOf()).toBe(`${FLOOR}px`);

    drag(120);

    expect(widthOf()).toBe(`${FLOOR + 120}px`);
    expect(getItem("sidebar-width")).toBe(String(FLOOR + 120));
  });

  // Never narrower than the width the app asked for, never more than half the
  // window.
  it.each([
    [-200, `${FLOOR}px`],
    [900, "512px"],
  ])("clamps a drag of %ipx to %s", (travel, width) => {
    setup();

    drag(travel);

    expect(widthOf()).toBe(width);
  });

  it("starts at the width this device last settled on", () => {
    setup();
    drag(100);
    cleanup();

    // A fresh mount, as a reload is: the width comes back off the device.
    setup();

    expect(widthOf()).toBe(`${FLOOR + 100}px`);
  });
});

describe("a column that can be folded away", () => {
  it("has the same edge", () => {
    render(
      <SidebarProvider style={{ "--sidebar-width": "20rem" } as React.CSSProperties}>
        <Sidebar collapsible="offcanvas">
          <div>navigation</div>
        </Sidebar>
      </SidebarProvider>
    );

    expect(screen.getByTitle("Drag to resize the sidebar")).toBeInTheDocument();
  });
});

/**
 * Cmd/Ctrl+B folds the sidebar, unless whatever has focus already used the
 * key: in the editor it means bold, and one press must not do both.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SidebarProvider, useSidebar } from "@/components/sidebar/sidebar";

const Probe = () => {
  const { open, openMobile } = useSidebar();
  return <span data-testid="probe">{`${open}:${openMobile}`}</span>;
};

const setup = () =>
  render(
    <SidebarProvider>
      <Probe />
      {/* Stands in for the editor, which takes Cmd/Ctrl+B for bold. */}
      <input aria-label="claims the key" onKeyDown={(event) => event.preventDefault()} />
    </SidebarProvider>
  );

describe("the sidebar's keyboard shortcut", () => {
  it("folds the sidebar", () => {
    setup();
    const before = screen.getByTestId("probe").textContent;

    fireEvent.keyDown(window, { key: "b", ctrlKey: true });

    expect(screen.getByTestId("probe").textContent).not.toBe(before);
  });

  it("leaves a key something focused already used", () => {
    setup();
    const before = screen.getByTestId("probe").textContent;

    fireEvent.keyDown(screen.getByLabelText("claims the key"), { key: "b", ctrlKey: true });

    expect(screen.getByTestId("probe").textContent).toBe(before);
  });
});

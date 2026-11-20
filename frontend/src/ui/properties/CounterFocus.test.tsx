import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { CounterFocus } from "./CounterFocus";
import type { CounterShown } from "./CounterView";

const lives: CounterShown = { count: "3", step: "1", min: "0", max: "3", look: "clock" };

const focus = (overrides: Partial<Parameters<typeof CounterFocus>[0]> = {}) => {
  const props = {
    counter: lives,
    name: "Lives",
    disabled: false,
    onStep: vi.fn(),
    onCommit: vi.fn(),
    onExit: vi.fn(),
    ...overrides,
  };
  renderWithProviders(<CounterFocus {...props} />);
  return props;
};

describe("CounterFocus", () => {
  it("steps within its bounds, in its look, and exits", async () => {
    const props = focus();
    expect(screen.getByRole("heading", { name: "Lives" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Step Lives up" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Step Lives down" }));
    expect(props.onStep).toHaveBeenCalledWith(false);
    // The clock draws one segment a step.
    expect(document.querySelectorAll("line")).toHaveLength(3);
    // Nothing to reset or more to do, so no menu.
    expect(screen.queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Exit full screen" }));
    expect(props.onExit).toHaveBeenCalled();
  });

  it("is watched without stepping where it can't be changed", () => {
    focus({ disabled: true });
    expect(screen.getByRole("heading", { name: "Lives" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Step Lives/ })).not.toBeInTheDocument();
  });

  it("shows a counter without both bounds as a number", () => {
    focus({ counter: { ...lives, max: null } });
    expect(document.querySelector("svg line")).toBeNull();
    expect(screen.getByRole("spinbutton", { name: "Lives" })).toHaveValue(3);
  });

  it("resets from its menu", async () => {
    const onReset = vi.fn();
    focus({ onReset });
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Reset Lives" }));
    expect(onReset).toHaveBeenCalled();
  });

  it("moves between counters by the arrows or a swipe, where there are others", async () => {
    const onMove = vi.fn();
    focus({ navigation: { index: 1, total: 3, onMove } });
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next counter" }));
    expect(onMove).toHaveBeenLastCalledWith(1);
    await userEvent.click(screen.getByRole("button", { name: "Previous counter" }));
    expect(onMove).toHaveBeenLastCalledWith(-1);

    const area = screen.getByRole("spinbutton", { name: "Lives" }).closest(".flex-1");
    if (!area) throw new Error("no swipe area");
    fireEvent.touchStart(area, { touches: [{ clientX: 200, clientY: 100 }] });
    fireEvent.touchEnd(area, { changedTouches: [{ clientX: 100, clientY: 110 }] });
    expect(onMove).toHaveBeenLastCalledWith(1);
  });

  it("has no arrows for a counter on its own", () => {
    focus({ navigation: { index: 0, total: 1, onMove: vi.fn() } });
    expect(screen.queryByRole("button", { name: "Next counter" })).not.toBeInTheDocument();
  });
});

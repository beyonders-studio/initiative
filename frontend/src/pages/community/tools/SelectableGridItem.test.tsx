import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SelectableGridItem } from "./SelectableGridItem";

describe("SelectableGridItem", () => {
  it("renders children untouched outside selection mode", () => {
    const onToggle = vi.fn();
    render(
      <SelectableGridItem active={false} selected={false} onToggle={onToggle} label="Card">
        <a href="/somewhere">Open</a>
      </SelectableGridItem>
    );

    expect(screen.getByRole("link", { name: "Open" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("reports whether shift was held so the list can extend a range", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <SelectableGridItem active selected={false} onToggle={onToggle} label="Card">
        <span>Card</span>
      </SelectableGridItem>
    );

    const overlay = screen.getByRole("button", { name: "Card" });

    await user.click(overlay);
    expect(onToggle).toHaveBeenLastCalledWith({ extend: false });

    await user.keyboard("{Shift>}");
    await user.click(overlay);
    await user.keyboard("{/Shift}");
    expect(onToggle).toHaveBeenLastCalledWith({ extend: true });
  });

  it("extends from the keyboard too, where the overlay is the only stop", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <SelectableGridItem active selected={false} onToggle={onToggle} label="Card">
        <span>Card</span>
      </SelectableGridItem>
    );

    screen.getByRole("button", { name: "Card" }).focus();

    await user.keyboard("{Enter}");
    expect(onToggle).toHaveBeenLastCalledWith({ extend: false });

    await user.keyboard("{Shift>}{Enter}{/Shift}");
    expect(onToggle).toHaveBeenLastCalledWith({ extend: true });

    await user.keyboard("{Shift>} {/Shift}");
    expect(onToggle).toHaveBeenLastCalledWith({ extend: true });
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AsyncCombobox } from "./async-combobox";

const ITEMS = [
  { value: "1", label: "Alpha" },
  { value: "2", label: "Beta" },
];

describe("AsyncCombobox", () => {
  it("reports the debounced query rather than every keystroke", async () => {
    const user = userEvent.setup();
    const onSearchChange = vi.fn();

    render(<AsyncCombobox items={ITEMS} onSearchChange={onSearchChange} debounceMs={20} />);

    await user.click(screen.getByRole("combobox"));
    await user.type(screen.getByPlaceholderText("Search"), "alp");

    await waitFor(() => {
      expect(onSearchChange).toHaveBeenLastCalledWith("alp");
    });
    // The opening "" plus the settled query — not one call per character.
    expect(onSearchChange.mock.calls.map(([q]) => q)).toEqual(["", "alp"]);
  });

  it("tells the caller when it opens and closes, so the query can be gated", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(<AsyncCombobox items={ITEMS} onSearchChange={vi.fn()} onOpenChange={onOpenChange} />);

    await user.click(screen.getByRole("combobox"));
    expect(onOpenChange).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByText("Alpha"));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it("renders every item the server returned, without filtering them again", async () => {
    const user = userEvent.setup();

    // A result the client couldn't match on label alone — the server matched
    // it on something else, and it must survive to the list.
    const items = [...ITEMS, { value: "3", label: "Unrelated" }];
    render(<AsyncCombobox items={items} onSearchChange={vi.fn()} debounceMs={0} />);

    await user.click(screen.getByRole("combobox"));
    await user.type(screen.getByPlaceholderText("Search"), "alpha");

    await waitFor(() => {
      expect(screen.getByText("Unrelated")).toBeInTheDocument();
    });
  });

  it("selects by value and reports it once", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();

    render(<AsyncCombobox items={ITEMS} onSearchChange={vi.fn()} onValueChange={onValueChange} />);

    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByText("Beta"));

    expect(onValueChange).toHaveBeenCalledExactlyOnceWith("2");
  });

  it("labels the trigger from selectedLabel when the selection is not in the results", () => {
    // The user picked "Gamma", then typed something else — the current page of
    // results no longer contains it, but the trigger must still name it.
    render(
      <AsyncCombobox items={ITEMS} value="9" selectedLabel="Gamma" onSearchChange={vi.fn()} />
    );

    expect(screen.getByRole("combobox")).toHaveTextContent("Gamma");
  });

  it("shows the loading state instead of a premature empty message", async () => {
    const user = userEvent.setup();

    render(
      <AsyncCombobox items={[]} loading onSearchChange={vi.fn()} emptyMessage="Nothing here" />
    );

    await user.click(screen.getByRole("combobox"));

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("Nothing here")).not.toBeInTheDocument();
  });
});

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Combobox } from "./combobox";

const ITEMS = [
  { value: "1", label: "Alpha" },
  { value: "2", label: "Beta" },
];

describe("Combobox", () => {
  describe("searched on the server", () => {
    it("reports the debounced query rather than every keystroke", async () => {
      const user = userEvent.setup();
      const onSearchChange = vi.fn();

      render(<Combobox items={ITEMS} onSearchChange={onSearchChange} debounceMs={20} />);

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

      render(<Combobox items={ITEMS} onSearchChange={vi.fn()} onOpenChange={onOpenChange} />);

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
      render(<Combobox items={items} onSearchChange={vi.fn()} debounceMs={0} />);

      await user.click(screen.getByRole("combobox"));
      await user.type(screen.getByPlaceholderText("Search"), "alpha");

      await waitFor(() => {
        expect(screen.getByText("Unrelated")).toBeInTheDocument();
      });
    });

    it("labels the trigger from selectedLabel when the selection is not in the results", () => {
      // The user picked "Gamma", then typed something else — the current page
      // of results no longer contains it, but the trigger must still name it.
      render(<Combobox items={ITEMS} value="9" selectedLabel="Gamma" onSearchChange={vi.fn()} />);

      expect(screen.getByRole("combobox")).toHaveTextContent("Gamma");
    });

    it("shows the loading state instead of a premature empty message", async () => {
      const user = userEvent.setup();

      render(<Combobox items={[]} loading onSearchChange={vi.fn()} emptyMessage="Nothing here" />);

      await user.click(screen.getByRole("combobox"));

      expect(screen.getByText("Loading…")).toBeInTheDocument();
      expect(screen.queryByText("Nothing here")).not.toBeInTheDocument();
    });
  });

  describe("searched here", () => {
    it("forgives a typo and ranks an exact name first", async () => {
      const user = userEvent.setup();
      const items = [
        { value: "1", label: "Roadmap review" },
        { value: "2", label: "Budget" },
        { value: "3", label: "Roadmap" },
      ];

      render(<Combobox items={items} />);

      await user.click(screen.getByRole("combobox"));
      await user.type(screen.getByPlaceholderText("Search"), "roadmap");
      expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
        "Roadmap",
        "Roadmap review",
      ]);

      await user.clear(screen.getByPlaceholderText("Search"));
      await user.type(screen.getByPlaceholderText("Search"), "budgte");
      expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["Budget"]);
    });

    it("selects by value and reports it once", async () => {
      const user = userEvent.setup();
      const onValueChange = vi.fn();

      render(<Combobox items={ITEMS} onValueChange={onValueChange} />);

      await user.click(screen.getByRole("combobox"));
      await user.click(screen.getByText("Beta"));

      expect(onValueChange).toHaveBeenCalledExactlyOnceWith("2");
    });

    it("offers what was typed even while an item contains it", async () => {
      const user = userEvent.setup();
      const onValueChange = vi.fn();
      const claims = ["roles", "groups"].map((claim) => ({ value: claim, label: claim }));

      render(
        <Combobox
          items={claims}
          onValueChange={onValueChange}
          typedLabel={(value) => `Use "${value}"`}
        />
      );

      await user.click(screen.getByRole("combobox"));
      await user.type(screen.getByPlaceholderText("Search"), "role");

      // `role` is a real claim, and `roles` being on the list must not be
      // what stops somebody choosing it.
      await user.click(screen.getByRole("option", { name: 'Use "role"' }));
      expect(onValueChange).toHaveBeenCalledWith("role");
    });

    it("does not offer what was typed once it is an item itself", async () => {
      const user = userEvent.setup();

      render(
        <Combobox
          items={[{ value: "groups", label: "groups" }]}
          typedLabel={(value) => `Use "${value}"`}
        />
      );

      await user.click(screen.getByRole("combobox"));
      await user.type(screen.getByPlaceholderText("Search"), "groups");

      expect(screen.queryByText('Use "groups"')).not.toBeInTheDocument();
      expect(screen.getByRole("option", { name: "groups" })).toBeInTheDocument();
    });
  });

  describe("multiple", () => {
    const Multiple = ({ initial = [] }: { initial?: string[] }) => {
      const [value, setValue] = useState(initial);
      return (
        <Combobox
          multiple
          aria-label="Statuses"
          value={value}
          onValueChange={setValue}
          placeholder="All statuses"
          items={[
            { value: "1", label: "Doing" },
            { value: "2", label: "Done" },
            { value: "cat:done", label: "Done", group: "Category" },
          ]}
        />
      );
    };

    it("ticks options from the keyboard and stays open", async () => {
      const user = userEvent.setup();
      render(<Multiple />);

      await user.click(screen.getByRole("combobox", { name: "Statuses" }));
      // Select all, clear all (disabled), Doing, Done, Done.
      await user.keyboard("{ArrowDown}{Enter}");
      await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

      expect(screen.getByRole("option", { name: "Doing" })).toHaveAttribute("aria-checked", "true");
      const category = within(screen.getByRole("group", { name: "Category" }));
      expect(category.getByRole("option", { name: "Done" })).toHaveAttribute(
        "aria-checked",
        "true"
      );
      expect(screen.getByRole("combobox", { name: "Statuses" })).toHaveTextContent("2 selected");
    });

    it("selects all and clears all", async () => {
      const user = userEvent.setup();
      render(<Multiple initial={["1"]} />);

      const trigger = screen.getByRole("combobox", { name: "Statuses" });
      expect(trigger).toHaveTextContent("Doing");

      await user.click(trigger);
      await user.click(screen.getByRole("option", { name: "Select all" }));
      expect(trigger).toHaveTextContent("All selected");

      await user.click(screen.getByRole("option", { name: "Clear all" }));
      expect(trigger).toHaveTextContent("All statuses");
    });

    it("says there is nothing to choose in place of the field", () => {
      render(<Combobox multiple value={[]} onValueChange={vi.fn()} items={[]} />);

      expect(screen.getByText("No options available")).toBeInTheDocument();
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });
  });
});

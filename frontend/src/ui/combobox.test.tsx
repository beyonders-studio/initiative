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

    it("matches the line under a name as well as the name", async () => {
      const user = userEvent.setup();
      const roles = [
        { value: "1", label: "Editor", sublabel: "Apollo" },
        { value: "2", label: "Viewer", sublabel: "Gemini" },
      ];

      render(<Combobox items={roles} />);

      await user.click(screen.getByRole("combobox"));
      await user.type(screen.getByPlaceholderText("Search"), "gemini");

      expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
        "ViewerGemini",
      ]);
    });

    it("makes a new item in a form of the caller's, from what was typed or from nothing", async () => {
      const user = userEvent.setup();
      const onValueChange = vi.fn();
      const Maker = () => {
        const [open, setOpen] = useState(false);
        const [draft, setDraft] = useState<string | null>(null);
        return (
          <Combobox
            items={ITEMS}
            onValueChange={onValueChange}
            open={open}
            onOpenChange={setOpen}
            typedLabel={() => "New item"}
            onCreate={setDraft}
            trigger={<button type="button">Add</button>}
          >
            {draft !== null ? (
              <button type="button" onClick={() => setOpen(false)}>
                Make "{draft}"
              </button>
            ) : null}
          </Combobox>
        );
      };

      render(<Maker />);

      await user.click(screen.getByRole("button", { name: "Add" }));
      // Offered before anything is typed, since this list makes items from
      // scratch as well.
      expect(screen.getByRole("option", { name: "New item" })).toBeInTheDocument();

      await user.type(screen.getByPlaceholderText("Search"), " Gamma ");
      await user.click(screen.getByRole("option", { name: "New item" }));

      expect(onValueChange).not.toHaveBeenCalled();
      await user.click(screen.getByRole("button", { name: 'Make "Gamma"' }));
      expect(screen.queryByRole("button", { name: 'Make "Gamma"' })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Add" })).toHaveAttribute("aria-expanded", "false");
    });

    it("keeps what was typed when making the item fails, to try again", async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(null);
      render(
        <Combobox
          items={ITEMS}
          typedLabel={(typed) => typed && `Create "${typed}"`}
          onCreate={onCreate}
        />
      );

      await user.click(screen.getByRole("combobox"));
      await user.type(screen.getByPlaceholderText("Search"), "Gamma");
      await user.click(screen.getByRole("option", { name: 'Create "Gamma"' }));
      expect(screen.getByPlaceholderText("Search")).toHaveValue("Gamma");

      await user.click(screen.getByRole("option", { name: 'Create "Gamma"' }));
      await waitFor(() => expect(screen.getByPlaceholderText("Search")).toHaveValue(""));
      expect(onCreate).toHaveBeenCalledTimes(2);
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

    it("adds every item that can be chosen to what is chosen, listed or not", async () => {
      const user = userEvent.setup();
      const onValueChange = vi.fn();
      render(
        <Combobox
          multiple
          aria-label="Statuses"
          value={["removed"]}
          onValueChange={onValueChange}
          items={[
            { value: "1", label: "Doing" },
            { value: "2", label: "Done", disabled: true },
          ]}
        />
      );

      await user.click(screen.getByRole("combobox", { name: "Statuses" }));
      await user.click(screen.getByRole("option", { name: "Select all" }));
      expect(onValueChange).toHaveBeenCalledWith(["removed", "1"]);
    });

    it("says there is nothing to choose in place of the field", () => {
      render(<Combobox multiple value={[]} onValueChange={vi.fn()} items={[]} />);

      expect(screen.getByText("No options available")).toBeInTheDocument();
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });

    it("searched on the server, treats the items as one page of matches", async () => {
      const user = userEvent.setup();

      // The one chosen is not on the page the server returned.
      const { rerender } = render(
        <Combobox
          multiple
          value={["9"]}
          onValueChange={vi.fn()}
          items={[]}
          onSearchChange={vi.fn()}
        />
      );
      expect(screen.getByRole("combobox")).toHaveTextContent("1 selected");

      rerender(
        <Combobox
          multiple
          value={["1", "2"]}
          onValueChange={vi.fn()}
          items={ITEMS}
          onSearchChange={vi.fn()}
        />
      );
      // Every row of a page is not every match, so neither is offered as "all".
      expect(screen.getByRole("combobox")).toHaveTextContent("2 selected");
      await user.click(screen.getByRole("combobox"));
      expect(screen.queryByRole("option", { name: "Select all" })).not.toBeInTheDocument();
    });
  });
});

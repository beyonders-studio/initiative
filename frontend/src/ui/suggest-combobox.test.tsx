import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SuggestCombobox } from "./suggest-combobox";

const labels = {
  searchPlaceholder: "Search or type",
  loadingLabel: "Looking…",
  emptyLabel: "Nothing to suggest",
  typedLabel: (value: string) => `Use "${value}"`,
};

describe("SuggestCombobox", () => {
  it("offers what was typed even while a suggestion contains it", async () => {
    const onValueChange = vi.fn();
    render(
      <SuggestCombobox
        suggestions={["roles", "groups"]}
        onValueChange={onValueChange}
        placeholder="Pick one"
        {...labels}
      />
    );

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.change(await screen.findByPlaceholderText("Search or type"), {
      target: { value: "role" },
    });

    // `role` is a real claim, and `roles` being on the list must not be what
    // stops somebody choosing it.
    fireEvent.click(screen.getByText('Use "role"'));
    expect(onValueChange).toHaveBeenCalledWith("role");
  });

  it("does not offer what was typed once it is a suggestion itself", async () => {
    render(<SuggestCombobox suggestions={["groups"]} placeholder="Pick one" {...labels} />);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.change(await screen.findByPlaceholderText("Search or type"), {
      target: { value: "groups" },
    });

    expect(screen.queryByText('Use "groups"')).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "groups" })).toBeInTheDocument();
  });

  it("asks for its suggestions when the list is first opened", () => {
    const onOpen = vi.fn();
    render(<SuggestCombobox suggestions={[]} onOpen={onOpen} placeholder="Pick one" {...labels} />);

    fireEvent.click(screen.getByRole("combobox"));

    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

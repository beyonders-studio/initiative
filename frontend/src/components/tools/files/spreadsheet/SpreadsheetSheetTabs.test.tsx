import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SheetMeta } from "@/lib/spreadsheet/sheets";

import { SpreadsheetSheetTabs } from "./SpreadsheetSheetTabs";

const SHEETS: SheetMeta[] = [
  { id: "s1", name: "Sheet1" },
  { id: "s2", name: "Sheet2" },
];

const renderTabs = (overrides: Partial<React.ComponentProps<typeof SpreadsheetSheetTabs>> = {}) => {
  const onRename = vi.fn();
  render(
    <SpreadsheetSheetTabs
      sheets={SHEETS}
      activeSheetId="s1"
      readOnly={false}
      canAdd
      onSelect={vi.fn()}
      onAdd={vi.fn()}
      onRename={onRename}
      onDelete={vi.fn()}
      onDuplicate={vi.fn()}
      onMove={vi.fn()}
      onSetHidden={vi.fn()}
      {...overrides}
    />
  );
  return { onRename };
};

describe("SpreadsheetSheetTabs", () => {
  it("keeps every typed character when renaming a sheet", async () => {
    const { onRename } = renderTabs();

    await userEvent.dblClick(screen.getByRole("tab", { name: "Sheet1" }));
    const input = screen.getByRole("textbox", { name: /sheet name/i });
    // ``skipClick`` keeps the selection the component set up: the name
    // starts selected, so the first keystroke replaces it wholesale — but
    // only the first. Re-selecting on every keystroke left just the last
    // character typed.
    await userEvent.type(input, "Budget{Enter}", { skipClick: true });

    expect(onRename).toHaveBeenCalledWith("s1", "Budget");
  });

  it("renames from the tab menu and discards the edit on Escape", async () => {
    const { onRename } = renderTabs();

    await userEvent.click(screen.getByRole("button", { name: "Sheet2 sheet actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: /sheet name/i });
    expect(input).toHaveValue("Sheet2");

    await userEvent.type(input, "Q1 Actuals{Escape}", { skipClick: true });

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByRole("tab", { name: "Sheet2" })).toBeInTheDocument();
  });
});

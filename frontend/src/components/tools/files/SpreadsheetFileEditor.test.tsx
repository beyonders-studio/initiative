/**
 * The spreadsheet editor's grid.
 *
 * A hidden row or column is not drawn. The virtualizer keeps a hidden line in its layout at zero size, so the
 * lines after it sit at the right offsets. Drawing it anyway puts its cells
 * at the same offset as the next line's, which is what
 * https://github.com/beyonders-studio/initiative/issues/1562 showed: hiding a row
 * left its text painted on top of the row below.
 *
 * The virtualizer is stubbed because jsdom gives every element a size of
 * zero, so the real one reports nothing to draw. The stub lays items out
 * from the same `estimateSize` the component supplies — which is where a
 * hidden line's zero height comes from — so what is under test is the
 * component's own decision about what to render.
 *
 * The toolbar is stubbed to count renders: it re-renders whenever the editor
 * body does, so it shows whether a keystroke redrew more than the input.
 */

import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const toolbarRenders = vi.hoisted(() => ({ count: 0 }));
vi.mock("@/components/tools/files/spreadsheet/SpreadsheetToolbar", () => ({
  SpreadsheetToolbar: () => {
    toolbarRenders.count += 1;
    return null;
  },
}));

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: (options: { count: number; estimateSize: (index: number) => number }) => {
    const items: { index: number; start: number; size: number; key: number }[] = [];
    let start = 0;
    // Enough of the sheet to cover the rows this test cares about.
    const shown = Math.min(options.count, 20);
    for (let index = 0; index < shown; index += 1) {
      const size = options.estimateSize(index);
      items.push({ index, start, size, key: index });
      start += size;
    }
    return {
      getVirtualItems: () => items,
      getTotalSize: () => start,
      measure: () => {},
      scrollToIndex: () => {},
      scrollToOffset: () => {},
      options,
    };
  },
}));

const content = (hidden: Record<string, { hidden: true }>) => ({
  schema_version: 3,
  kind: "spreadsheet",
  sheets: [
    {
      id: "s1",
      name: "Sheet1",
      dimensions: { rows: 20, cols: 4 },
      cells: { "0:0": "Test1", "1:0": "Test2", "2:0": "Test3" },
      columns: {},
      rows: hidden,
      cellStyles: {},
      frozen: { rows: 0, cols: 0 },
    },
  ],
});

const renderSheet = async (rows: Record<string, { hidden: true }>) => {
  const { SpreadsheetFileEditor } = await import("./SpreadsheetFileEditor");
  renderWithProviders(
    <SpreadsheetFileEditor
      initialContent={content(rows) as any}
      onContentChange={() => {}}
      fileTitle="Sheet"
      readOnly={false}
    />
  );
};

describe("a hidden row", () => {
  it("is drawn when nothing is hidden", async () => {
    await renderSheet({});

    expect(screen.getAllByText("Test2").length).toBeGreaterThan(0);
  });

  it("is not drawn once hidden, so it cannot land on the row below", async () => {
    await renderSheet({ "1": { hidden: true } });

    expect(screen.queryByText("Test2")).not.toBeInTheDocument();
    // Its neighbours are untouched. ``Test1`` is the focused cell, so it is
    // on screen twice — in the grid and in the formula bar.
    expect(screen.getAllByText("Test1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Test3").length).toBeGreaterThan(0);
  });
});

describe("a cell being edited", () => {
  it("redraws only its input as it is typed, and takes a clicked cell into the formula", async () => {
    await renderSheet({});

    fireEvent.doubleClick(screen.getByText("Test2"));
    const input = document.activeElement as HTMLInputElement;
    const renders = toolbarRenders.count;
    fireEvent.change(input, { target: { value: "T" } });
    fireEvent.change(input, { target: { value: "Te" } });
    fireEvent.change(input, { target: { value: "=" } });
    expect(input.value).toBe("=");
    expect(screen.getByLabelText(/^Formula bar/)).toHaveValue("=");
    expect(toolbarRenders.count).toBe(renders);

    fireEvent.mouseDown(screen.getByText("Test1"), { button: 0 });
    expect(input.value).toBe("=A1");

    fireEvent.keyDown(input, { key: "Enter" });
    // A1 itself, and A2 showing what its formula computes.
    expect(screen.getAllByText("Test1")).toHaveLength(2);
    expect(screen.queryByText("Test2")).not.toBeInTheDocument();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeAll, describe, expect, it } from "vitest";

import type { AppColumnDef } from "@/ui/lib/table";

import { DataTable } from "./data-table";

interface Row {
  id: number;
  name: string;
}

const columns: AppColumnDef<Row>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => row.original.name,
  },
];

const rows: Row[] = [
  { id: 1, name: "Alpha" },
  { id: 2, name: "Bravo" },
  { id: 3, name: "Charlie" },
  { id: 4, name: "Delta" },
  { id: 5, name: "Echo" },
];

/** Renders the table and exposes the latest reported selection via a data attr. */
function Harness({ data = rows }: { data?: Row[] }) {
  const [selected, setSelected] = useState<Row[]>([]);
  return (
    <div>
      <div data-testid="selection">{selected.map((r) => r.id).join(",")}</div>
      <DataTable
        columns={columns}
        data={data}
        enableRowSelection
        enableFilterInput
        getRowId={(row) => String(row.id)}
        onRowSelectionChange={setSelected}
      />
    </div>
  );
}

const reported = () => screen.getByTestId("selection").textContent;

/** Enter selection mode and return the per-row selection checkboxes in DOM order. */
async function enterSelectionMode(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Select" }));
  return () => screen.getAllByRole("checkbox", { name: "Select row" });
}

/** Render a harness in selection mode, ready to be clicked. */
async function selecting(harness: React.ReactElement) {
  const user = userEvent.setup();
  render(harness);
  return { user, getCheckboxes: await enterSelectionMode(user) };
}

describe("DataTable row selection", () => {
  it("shift+clicking selects the inclusive range in displayed order", async () => {
    const { user, getCheckboxes } = await selecting(<Harness />);

    // Anchor on row 2 (Bravo)...
    await user.click(getCheckboxes()[1]);
    expect(reported()).toBe("2");

    // ...then shift+click row 4 (Delta) → selects 2,3,4 inclusive.
    await user.keyboard("{Shift>}");
    await user.click(getCheckboxes()[3]);
    await user.keyboard("{/Shift}");

    expect(reported()).toBe("2,3,4");
  });

  it("shift+click after select-all does not range from a stale anchor", async () => {
    const { user, getCheckboxes } = await selecting(<Harness />);

    // Establish an anchor on row 1, then select-all + deselect-all. Select-all
    // clears the anchor, leaving an empty selection and no anchor.
    await user.click(getCheckboxes()[0]);
    const selectAll = screen.getByRole("checkbox", { name: "Select all" });
    await user.click(selectAll);
    expect(reported()).toBe("1,2,3,4,5");
    await user.click(selectAll);
    expect(reported()).toBe("");

    // A shift+click now behaves as a fresh single toggle. If the row-1 anchor had
    // leaked, this would range-select 1..4; instead only row 4 is selected.
    await user.keyboard("{Shift>}");
    await user.click(getCheckboxes()[3]);
    await user.keyboard("{/Shift}");

    expect(reported()).toBe("4");
  });

  it("keeps selection consistent across filtering (filter out, select more, clear)", async () => {
    const { user, getCheckboxes } = await selecting(<Harness />);

    // Select Alpha + Bravo.
    await user.click(getCheckboxes()[0]);
    await user.click(getCheckboxes()[1]);
    expect(reported()).toBe("1,2");

    // Filter to hide the selected rows (show only Echo).
    const filter = screen.getByPlaceholderText("Filter…");
    await user.type(filter, "Echo");

    // Only Echo is visible now; select it.
    const visible = screen.getAllByRole("checkbox", { name: "Select row" });
    expect(visible).toHaveLength(1);
    await user.click(visible[0]);

    // Selection persists across the filter: all three reported, not just Echo.
    expect(reported()).toBe("1,2,5");

    // Clear the filter → checkboxes and reported selection stay in sync.
    await user.clear(filter);
    const all = screen.getAllByRole("checkbox", { name: "Select row" });
    const checkedIds = rows
      .filter((_, i) => (all[i] as HTMLElement).getAttribute("data-state") === "checked")
      .map((r) => r.id);
    expect(checkedIds).toEqual([1, 2, 5]);
    expect(reported()).toBe("1,2,5");
  });

  // Alpha + Bravo are selected and then filtered out of sight. Even where the
  // filter leaves more rows than are selected — 2 selected, 3 matching — the
  // plain "2 of 3 selected" would be misleading, because neither of the two is
  // among the three. So the filtered variant is what both cases show.
  it.each([
    ["hidden by a filter that leaves one row", "Echo", "2 selected (1 match filter)"],
    [
      "hidden by a filter that leaves more rows than are selected",
      "e",
      "2 selected (3 match filter)",
    ],
  ])("shows a filter-aware count for rows %s", async (_label, filterText, count) => {
    const { user, getCheckboxes } = await selecting(<Harness />);

    await user.click(getCheckboxes()[0]);
    await user.click(getCheckboxes()[1]);
    await user.type(screen.getByPlaceholderText("Filter…"), filterText);

    expect(screen.getByText(count)).toBeInTheDocument();
    expect(screen.queryByText("2 of 3 row(s) selected")).not.toBeInTheDocument();
  });
});

/**
 * A row fanned out over a multi-valued field: the project task table groups by
 * tag this way, emitting one row per (task, tag) pair so a row shows up under
 * every value it carries.
 */
interface FannedRow extends Row {
  group?: string;
}

const fannedColumns: AppColumnDef<FannedRow>[] = [
  { accessorKey: "name", header: "Name", cell: ({ row }) => row.original.name },
  {
    id: "group",
    accessorFn: (row) => row.group ?? "Ungrouped",
    header: "Group",
    cell: ({ getValue }) => getValue<string>(),
    enableHiding: false,
  },
];

const fannedRows: FannedRow[] = [
  { id: 1, name: "Alpha", group: "bug" },
  { id: 1, name: "Alpha", group: "urgent" },
  { id: 2, name: "Bravo", group: "bug" },
  { id: 3, name: "Charlie" },
];

/** The same rows unfanned, as a consumer would pass them when not grouping. */
const plainRows: FannedRow[] = [
  { id: 1, name: "Alpha" },
  { id: 2, name: "Bravo" },
  { id: 3, name: "Charlie" },
];

const fannedRowId = (row: FannedRow) => (row.group ? `${row.id}::${row.group}` : String(row.id));

/** Renders the grouped table, with a button that re-shapes the data in place. */
function GroupedHarness() {
  const [fanned, setFanned] = useState(true);
  const [selected, setSelected] = useState<FannedRow[]>([]);
  const data = fanned ? fannedRows : plainRows;
  return (
    <div>
      <button type="button" onClick={() => setFanned((previous) => !previous)}>
        Reshape
      </button>
      <div data-testid="selection">{selected.map((r) => fannedRowId(r)).join(",")}</div>
      <DataTable
        columns={fannedColumns}
        data={data}
        enableRowSelection
        getRowId={fannedRowId}
        groupingOptions={[{ id: "group", label: "Group" }]}
        columnVisibility={{ group: false }}
        initialState={{ grouping: ["group"] }}
        onRowSelectionChange={setSelected}
      />
    </div>
  );
}

describe("DataTable filter", () => {
  it("keeps the rows that hold what was typed, whatever its case, and no near ones", async () => {
    const user = userEvent.setup();
    render(<DataTable columns={columns} data={rows} enableFilterInput />);
    const filter = screen.getByPlaceholderText("Filter…");

    await user.type(filter, "ARL");
    expect(screen.getByText("Charlie")).toBeInTheDocument();

    // The letters of Charlie in order, and Charlie with two swapped: neither is Charlie.
    for (const near of ["chrl", "Chralie"]) {
      await user.clear(filter);
      await user.type(filter, near);
      expect(screen.queryByText("Charlie")).not.toBeInTheDocument();
    }
  });
});

describe("DataTable grouping", () => {
  it("groups on a hidden column, listing a fanned-out row under each of its groups", () => {
    render(<GroupedHarness />);

    // The grouping column drives the group headers without becoming a column.
    expect(screen.queryByRole("columnheader", { name: "Group" })).not.toBeInTheDocument();
    const groupHeaders = screen
      .getAllByRole("row")
      .filter((row) => row.getAttribute("data-state") === "grouped")
      .map((row) => row.textContent);
    expect(groupHeaders).toEqual(["Ungrouped1", "bug2", "urgent1"]);

    // Alpha carries two groups, so it appears under both.
    expect(screen.getAllByText("Alpha")).toHaveLength(2);
    expect(screen.getAllByText("Bravo")).toHaveLength(1);
  });

  it("follows a grouping it is handed after it mounts", () => {
    const table = (grouping: string[]) => (
      <DataTable
        columns={fannedColumns}
        data={grouping.length > 0 ? fannedRows : plainRows}
        groupingOptions={[{ id: "group", label: "Group" }]}
        columnVisibility={{ group: false }}
        grouping={grouping}
      />
    );
    const groupHeaders = () =>
      screen.getAllByRole("row").filter((row) => row.getAttribute("data-state") === "grouped");
    const { rerender } = render(table(["group"]));
    expect(groupHeaders()).toHaveLength(3);

    rerender(table([]));

    expect(groupHeaders()).toHaveLength(0);
    expect(screen.getAllByText("Alpha")).toHaveLength(1);
  });

  it("re-reports the selection when the data is re-shaped under it", async () => {
    const { user, getCheckboxes } = await selecting(<GroupedHarness />);

    // Rows read Ungrouped (Charlie), bug (Alpha, Bravo), urgent (Alpha) — pick
    // Alpha's row in the "bug" group.
    await user.click(getCheckboxes()[1]);
    expect(reported()).toBe("1::bug");

    // Re-shaping the rows re-keys them, so nothing is checked any more — the
    // reported selection has to follow rather than keep the stale row.
    await user.click(screen.getByRole("button", { name: "Reshape" }));
    expect(reported()).toBe("");
  });

  it("does not bring a selection back when the original row keys return", async () => {
    const { user, getCheckboxes } = await selecting(<GroupedHarness />);

    await user.click(getCheckboxes()[1]);
    const reshape = screen.getByRole("button", { name: "Reshape" });

    // Away from the fanned shape the selected id no longer exists...
    await user.click(reshape);
    expect(reported()).toBe("");

    // ...and back in it, the row must stay unchecked rather than re-select
    // itself off a selection id nothing reported any more.
    await user.click(reshape);
    expect(reported()).toBe("");
    const checked = getCheckboxes().filter((box) => box.getAttribute("data-state") === "checked");
    expect(checked).toHaveLength(0);
  });
});

/** Enough rows to spill past a page, ordered so sorting is observable. */
const manyRows: Row[] = Array.from({ length: 25 }, (_, i) => ({
  id: i + 1,
  name: `Row ${String(i + 1).padStart(2, "0")}`,
}));

const sortableColumns: AppColumnDef<Row>[] = [
  {
    accessorKey: "name",
    header: ({ column }) => (
      <button type="button" onClick={() => column.toggleSorting()}>
        Name
      </button>
    ),
    cell: ({ row }) => row.original.name,
    sortFn: "alphanumeric",
  },
];

/** Body rows only — `getAllByRole("row")` counts the header row too. */
const bodyRows = () => screen.getAllByRole("row").slice(1);
const firstBodyRowText = () => bodyRows()[0].textContent;

describe("DataTable pagination", () => {
  // Guards the row-model wiring: the table must not silently slice a caller
  // that never asked to paginate down to a single page.
  it.each([
    ["renders every row when pagination is off", false, 25],
    ["slices to one page when pagination is on", true, 20],
  ])("%s", (_label, enablePagination, shown) => {
    render(<DataTable columns={columns} data={manyRows} enablePagination={enablePagination} />);

    expect(bodyRows()).toHaveLength(shown);
    expect(screen.getByText("Row 01")).toBeInTheDocument();
    // Row 25 is on the first page only where nothing was sliced away.
    expect(screen.queryByText("Row 25") !== null).toBe(!enablePagination);
  });

  it("moves between pages", async () => {
    const user = userEvent.setup();
    render(<DataTable columns={columns} data={manyRows} enablePagination />);

    expect(screen.queryByText("Row 21")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(bodyRows()).toHaveLength(5);
    expect(screen.getByText("Row 21")).toBeInTheDocument();
    expect(screen.queryByText("Row 01")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByText("Row 01")).toBeInTheDocument();
  });

  it("offers the caller's page sizes, with the size in use among them", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        columns={columns}
        data={manyRows}
        enablePagination
        pageSizeOptions={[5, 10]}
        initialState={{ pagination: { pageIndex: 0, pageSize: 20 } }}
      />
    );
    expect(screen.getByText("1–20 of 25")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Per page:" }));
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "5",
      "10",
      "20",
    ]);
    await user.click(screen.getByRole("option", { name: "5" }));
    expect(bodyRows()).toHaveLength(5);
    expect(screen.getByText("1–5 of 25")).toBeInTheDocument();
  });

  it("leaves paging to the caller under manualPagination", () => {
    // The caller has already sliced `data`; the table must render it as given
    // rather than paginate it a second time.
    const page = manyRows.slice(0, 5);
    render(
      <DataTable
        columns={columns}
        data={page}
        enablePagination
        manualPagination
        pageCount={5}
        rowCount={25}
        initialState={{ pagination: { pageIndex: 0, pageSize: 5 } }}
      />
    );
    expect(bodyRows()).toHaveLength(5);
    expect(screen.getByText("1–5 of 25")).toBeInTheDocument();
  });
});

describe("DataTable sorting", () => {
  it("sorts client-side through a registered sort function", async () => {
    const user = userEvent.setup();
    render(<DataTable columns={sortableColumns} data={[...manyRows].reverse()} />);
    expect(firstBodyRowText()).toContain("Row 25");

    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(firstBodyRowText()).toContain("Row 01");

    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(firstBodyRowText()).toContain("Row 25");
  });

  it("leaves row order alone under manualSorting", async () => {
    // The caller sorts server-side, so a header click reports the intent but
    // must not reorder the rows the table was handed.
    const user = userEvent.setup();
    const reversed = [...manyRows].reverse();
    render(<DataTable columns={sortableColumns} data={reversed} manualSorting />);
    expect(firstBodyRowText()).toContain("Row 25");

    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(firstBodyRowText()).toContain("Row 25");
  });

  it("keeps a pinned row first whichever way it sorts", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        columns={sortableColumns}
        data={manyRows}
        getRowId={(row) => String(row.id)}
        pinnedRowId="13"
      />
    );
    expect(firstBodyRowText()).toContain("Row 13");

    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(firstBodyRowText()).toContain("Row 13");
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(firstBodyRowText()).toContain("Row 13");
  });

  it("reports sorting changes to the caller", async () => {
    const user = userEvent.setup();
    const seen: string[] = [];
    render(
      <DataTable
        columns={sortableColumns}
        data={manyRows}
        manualSorting
        onSortingChange={(sorting) =>
          seen.push(sorting.map((s) => `${s.id}:${s.desc ? "desc" : "asc"}`).join(","))
        }
      />
    );
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(seen).toEqual(["name:asc"]);
  });
});

/** One sized column and one that leaves its width to the table. */
const sizedColumns: AppColumnDef<Row>[] = [
  { id: "pin", header: "Pin", cell: () => "\u00b7", size: 40 },
  { accessorKey: "name", header: "Name", cell: ({ row }) => row.original.name },
];

describe("DataTable virtualization", () => {
  // Which rows it mounts, against the page's scroller, is the collection
  // page's to show (`CollectionPage.test.tsx`); these cover the table's shape.
  it.each([
    ["drops the pagination controls, which scrolling the page replaces", true],
    ["keeps the pagination controls when virtualization is off", false],
  ])("%s", (_label, enableVirtualization) => {
    render(
      <DataTable
        columns={columns}
        data={manyRows}
        enablePagination
        enableVirtualization={enableVirtualization}
        virtualRowHeight={48}
      />
    );

    const next = screen.queryByRole("button", { name: "Next" });
    if (enableVirtualization) {
      expect(next).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Per page:")).not.toBeInTheDocument();
    } else {
      expect(next).toBeInTheDocument();
    }
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
  });

  // With the automatic layout algorithm the browser sizes columns from the
  // cells it can see, and a virtualized table swaps those out on every scroll —
  // so the widths have to come from the column definitions instead, and the
  // head, drawn apart from the body, takes the same ones.
  it.each([
    ["pins the head's and the body's column widths alike while virtualized", true],
    ["leaves the widths to the browser when virtualization is off", false],
  ])("%s", (_label, enableVirtualization) => {
    const { container } = render(
      <DataTable
        columns={sizedColumns}
        data={manyRows}
        enableVirtualization={enableVirtualization}
        virtualRowHeight={48}
      />
    );

    const tables = Array.from(container.querySelectorAll("table"));
    const widths = tables.map((table) =>
      Array.from(table.querySelectorAll("col"), (col) => col.style.width)
    );
    if (!enableVirtualization) {
      expect(tables.map((table) => table.classList.contains("table-fixed"))).toEqual([false]);
      expect(widths).toEqual([[]]);
      return;
    }
    expect(tables.map((table) => table.classList.contains("table-fixed"))).toEqual([true, true]);
    // A column that declares no size falls back to the table default.
    expect(widths).toEqual([
      ["40px", "150px"],
      ["40px", "150px"],
    ]);
  });

  it("keeps its head over the body's columns as the body scrolls sideways", () => {
    render(<DataTable columns={sizedColumns} data={manyRows} enableVirtualization />);

    const [head, body] = Array.from(screen.getByRole("table").children) as HTMLElement[];
    body.scrollLeft = 120;
    fireEvent.scroll(body);

    expect(head.scrollLeft).toBe(120);
  });
});

describe("DataTable grouping callback", () => {
  // Radix's Select relies on pointer-capture and scrollIntoView, neither of
  // which jsdom implements.
  beforeAll(() => {
    Element.prototype.hasPointerCapture ??= () => false;
    Element.prototype.releasePointerCapture ??= () => {};
    Element.prototype.scrollIntoView ??= () => {};
  });

  // Consumers re-shape their rows in response to this callback — the project
  // task table fans a task out into one row per tag — so a grouping the caller
  // never hears about leaves it grouping over data it never rebuilt.
  it.each([
    ["reports a grouping picked from the toolbar to the caller", undefined, "Group", ["group"]],
    ["reports clearing the grouping back to None", { grouping: ["group"] }, "None", []],
  ])("%s", async (_label, initialState, option, reported) => {
    const user = userEvent.setup();
    const seen: string[][] = [];
    render(
      <DataTable
        columns={fannedColumns}
        data={fannedRows}
        getRowId={fannedRowId}
        enableFilterInput
        groupingOptions={[{ id: "group", label: "Group" }]}
        initialState={initialState}
        onGroupingChange={(next) => seen.push(next)}
      />
    );

    await user.click(screen.getByRole("combobox", { name: "Group by" }));
    await user.click(screen.getByRole("option", { name: option }));

    expect(seen).toEqual([reported]);
  });
});

interface TreeRow extends Row {
  parts?: TreeRow[];
}

const treeColumns: AppColumnDef<TreeRow>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => (
      <span>
        {row.subRows.length > 0 ? (
          <button
            type="button"
            aria-expanded={row.getIsExpanded()}
            aria-label={`Fold ${row.original.name}`}
            onClick={row.getToggleExpandedHandler()}
          >
            Fold
          </button>
        ) : null}
        {row.original.name}
      </span>
    ),
  },
];

const tree: TreeRow[] = [
  {
    id: 1,
    name: "Post",
    parts: [
      { id: 2, name: "Script" },
      { id: 3, name: "Shoot", parts: [{ id: 4, name: "Lights" }] },
    ],
  },
  { id: 5, name: "Other" },
];

function TreeHarness() {
  const [selected, setSelected] = useState<TreeRow[]>([]);
  const [data, setData] = useState(tree);
  return (
    <div>
      <div data-testid="selection">{selected.map((r) => r.id).join(",")}</div>
      <button type="button" onClick={() => setData(structuredClone(tree))}>
        Refetch
      </button>
      <DataTable
        columns={treeColumns}
        data={data}
        enableRowSelection
        enableFilterInput
        getRowId={(row) => String(row.id)}
        getSubRows={(row) => row.parts}
        initialState={{ expanded: true }}
        onRowSelectionChange={setSelected}
      />
    </div>
  );
}

const names = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.textContent?.replace(/^Fold/, ""));

describe("DataTable nested rows", () => {
  it("draws a row's nested rows under it, and folds them with it", async () => {
    const user = userEvent.setup();
    render(<TreeHarness />);

    expect(names()).toEqual(["Post", "Script", "Shoot", "Lights", "Other"]);

    await user.click(screen.getByRole("button", { name: "Fold Post" }));

    expect(names()).toEqual(["Post", "Other"]);
  });

  it("keeps a folded row folded when its rows arrive again", async () => {
    const user = userEvent.setup();
    render(<TreeHarness />);

    await user.click(screen.getByRole("button", { name: "Fold Post" }));
    await user.click(screen.getByRole("button", { name: "Refetch" }));

    expect(names()).toEqual(["Post", "Other"]);
    expect(screen.getByRole("button", { name: "Fold Post" })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
  });

  it("selects only the row clicked, and reports a nested one", async () => {
    const { user, getCheckboxes } = await selecting(<TreeHarness />);

    await user.click(getCheckboxes()[0]);
    expect(reported()).toBe("1");

    await user.click(getCheckboxes()[3]);
    expect(reported()).toBe("1,4");
  });

  it("keeps the rows above a nested row that matches the filter", async () => {
    const user = userEvent.setup();
    render(<TreeHarness />);

    await user.type(screen.getByPlaceholderText("Filter…"), "Lights");

    expect(names()).toEqual(["Post", "Shoot", "Lights"]);
  });
});

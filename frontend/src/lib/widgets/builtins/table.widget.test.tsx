import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { TableNode } from "@/components/initiativeTools/dashboards/scene/TableNode";
import { dateTimeFormat } from "@/ui/lib/intl";

import { normalizeQueryRows } from "../normalize";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import { validateScene } from "../validateScene";

it("renders SQL calendar dates without shifting timestamp presentation", async () => {
  const source = builtinWidgetSource("table");
  if (!source) throw new Error("Missing table widget");
  const at = Date.parse("2026-08-03T00:00:00Z");
  const normalized = normalizeQueryRows(
    [
      { name: "Calendar day", type: "date", date_only: true },
      { name: "Instant", type: "date", date_only: false },
    ],
    [[at, at]]
  );
  const result = await renderInSandbox({
    source,
    data: { source: "rows", ...normalized },
    config: {},
  });
  if (!result.ok) throw new Error(JSON.stringify(result));
  const validated = validateScene(result.value);
  if (!validated.ok) throw new Error(JSON.stringify(validated));
  if (validated.spec.scene.kind !== "table") throw new Error("Expected a table");
  expect(validated.spec.scene.columns.map((column) => column.format)).toEqual([
    "date-only",
    "date",
  ]);
  render(<TableNode node={validated.spec.scene} />);
  const cells = screen.getAllByRole("cell");
  expect(cells[0]).toHaveTextContent("Aug 3, 2026");
  expect(cells[1]).toHaveTextContent(
    dateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(at)
  );
});

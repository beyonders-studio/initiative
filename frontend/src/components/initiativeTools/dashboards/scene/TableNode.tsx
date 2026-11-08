import { formatValue } from "@/lib/widgets/format";
import type { SceneNode, TableCell, TableColumn, Tone } from "@/lib/widgets/sceneSpec";
import { toneTextClass } from "@/lib/widgets/tone";
import { cn } from "@/ui/lib/utils";

type Node = Extract<SceneNode, { kind: "table" }>;

/** A cell is a scalar, or a scalar carrying a tone (the validator drops
 *  anything else), so this only has to decide how each scalar reads and which
 *  ink it wears. */
const readCell = (cell: TableCell): { value: Exclude<TableCell, object>; tone?: Tone } =>
  cell !== null && typeof cell === "object"
    ? { value: cell.value, tone: cell.tone }
    : { value: cell };

const renderCell = (value: Exclude<TableCell, object>, column: TableColumn): string => {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return formatValue(value, column.format);
  return value;
};

/**
 * A read-only grid. No row actions, no inline editing, no selection — a
 * dashboard shows what is there and working with it is a project view's job.
 */
export function TableNode({ node }: { node: Node }) {
  return (
    <div className="h-full w-full overflow-auto">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-card">
          <tr className="border-border border-b">
            {node.columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "px-2 py-1.5 font-medium text-muted-foreground text-xs",
                  column.align === "end" ? "text-right" : "text-left"
                )}
              >
                {column.label ?? column.key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {node.rows.map((row, index) => (
            <tr
              // biome-ignore lint/suspicious/noArrayIndexKey: scene rows have no id — the widget already fixed the order, so row position is the only identity a table row has
              key={index}
              className="border-border/50 border-b last:border-0"
            >
              {node.columns.map((column) => {
                const cell = readCell(row[column.key] ?? null);
                return (
                  <td
                    key={column.key}
                    className={cn(
                      "max-w-[16rem] truncate px-2 py-1.5",
                      column.align === "end" ? "text-right tabular-nums" : "text-left",
                      // A toned cell wears a text token, never the raw color —
                      // a light categorical hue is illegible as text.
                      cell.tone && toneTextClass(cell.tone)
                    )}
                  >
                    {renderCell(cell.value, column)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

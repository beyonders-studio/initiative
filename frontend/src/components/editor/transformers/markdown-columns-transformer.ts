import {
  $convertFromMarkdownString,
  $convertToMarkdownString,
  type MultilineElementTransformer,
  type Transformer,
} from "@lexical/markdown";
import { $createParagraphNode, type LexicalNode } from "lexical";

import {
  $createLayoutContainerNode,
  $isLayoutContainerNode,
  LayoutContainerNode,
} from "@/components/editor/nodes/layout-container-node";
import {
  $createLayoutItemNode,
  $isLayoutItemNode,
  LayoutItemNode,
} from "@/components/editor/nodes/layout-item-node";

/*
 * Columns have no markdown of their own, so they are written the way Pandoc
 * and Quarto write them — fenced divs:
 *
 *   :::: {.columns}
 *   ::: {.column width="25%"}
 *   The narrow one.
 *   :::
 *   ::: {.column width="75%"}
 *   The wide one.
 *   :::
 *   ::::
 *
 * Widths are the editor's column template as percentages, and read back into
 * the smallest whole ratio that says the same thing.
 */

const COLUMNS_START = /^:{3,}\s*(?:\{\s*\.columns\b[^}]*\}|columns)\s*$/;
const COLUMN_START = /^:{3,}\s*(?:\{\s*\.column\b([^}]*)\}|column)\s*$/;
const FENCE_END = /^:{3,}\s*$/;
const WIDTH = /width\s*=\s*"?(\d+(?:\.\d+)?)%"?/;

const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));

/** Percentages → the column template, as small whole fractions. */
export function templateFromWidths(widths: Array<number | null>): string {
  if (widths.length === 0) {
    return "1fr";
  }
  const known = widths.filter((width): width is number => width !== null && width > 0);
  // A column with no width shares what the others left.
  const fallback =
    known.length < widths.length
      ? Math.max(1, (100 - known.reduce((a, b) => a + b, 0)) / (widths.length - known.length))
      : 0;
  const rounded = widths.map((width) => Math.max(1, Math.round(width ?? fallback)));
  const divisor = rounded.reduce(gcd);
  return rounded.map((width) => `${width / divisor}fr`).join(" ");
}

/** The column template → each column's share, as a whole percentage. */
export function widthsFromTemplate(template: string): number[] {
  const parts = template
    .trim()
    .split(/\s+/)
    .map((part) => Number.parseFloat(part))
    .map((value) => (Number.isFinite(value) && value > 0 ? value : 1));
  const total = parts.reduce((a, b) => a + b, 0);
  return parts.map((part) => Math.round((part / total) * 100));
}

export function createColumnsTransformer(
  transformers: () => Transformer[]
): MultilineElementTransformer {
  return {
    dependencies: [LayoutContainerNode, LayoutItemNode],
    type: "multiline-element",
    regExpStart: COLUMNS_START,
    export: (node: LexicalNode) => {
      if (!$isLayoutContainerNode(node)) {
        return null;
      }
      const widths = widthsFromTemplate(node.getTemplateColumns());
      const lines = [":::: {.columns}"];
      node.getChildren().forEach((item, index) => {
        if (!$isLayoutItemNode(item)) {
          return;
        }
        lines.push(`::: {.column width="${widths[index] ?? 0}%"}`);
        const body = $convertToMarkdownString(transformers(), item);
        if (body !== "") {
          lines.push(body);
        }
        lines.push(":::");
      });
      lines.push("::::");
      return lines.join("\n");
    },
    handleImportAfterStartMatch: ({ lines, rootNode, startLineIndex }) => {
      const columns: Array<{ width: number | null; body: string[] }> = [];
      let current: { width: number | null; body: string[] } | null = null;
      let end = startLineIndex + 1;
      for (; end < lines.length; end++) {
        const line = lines[end];
        const column = line.match(COLUMN_START);
        if (column && current === null) {
          const width = column[1]?.match(WIDTH);
          current = { width: width ? Number.parseFloat(width[1]) : null, body: [] };
          continue;
        }
        if (FENCE_END.test(line)) {
          if (current !== null) {
            columns.push(current);
            current = null;
            continue;
          }
          break;
        }
        if (current !== null) {
          current.body.push(line);
        }
        // Anything between columns that is not a column is not ours to keep.
      }
      if (current !== null) {
        columns.push(current);
      }
      if (columns.length === 0) {
        // `:::: columns` with nothing in it: not a layout, leave it be.
        return null;
      }
      const container = $createLayoutContainerNode(
        templateFromWidths(columns.map((column) => column.width))
      );
      for (const column of columns) {
        const item = $createLayoutItemNode();
        $convertFromMarkdownString(column.body.join("\n"), transformers(), item);
        if (item.getChildrenSize() === 0) {
          item.append($createParagraphNode());
        }
        container.append(item);
      }
      rootNode.append(container);
      return [true, Math.min(end, lines.length - 1)];
    },
    replace: () => false,
  };
}

import {
  $convertFromMarkdownString,
  $convertToMarkdownString,
  CHECK_LIST,
  ELEMENT_TRANSFORMERS,
  type ElementTransformer,
  MULTILINE_ELEMENT_TRANSFORMERS,
  TEXT_FORMAT_TRANSFORMERS,
  TEXT_MATCH_TRANSFORMERS,
} from "@lexical/markdown";
import {
  $computeTableMapSkipCellCheck,
  $createTableCellNode,
  $createTableNode,
  $createTableRowNode,
  $isTableCellNode,
  $isTableNode,
  $isTableRowNode,
  TableCellHeaderStates,
  TableCellNode,
  TableNode,
  TableRowNode,
} from "@lexical/table";
import { $isParagraphNode, $isTextNode, type LexicalNode } from "lexical";

// import { EMOJI } from "@/components/editor/transformers/markdown-emoji-transformer"
import { HR } from "@/components/editor/transformers/markdown-hr-transformer";
import { IMAGE } from "@/components/editor/transformers/markdown-image-transformer";
import {
  PERSON_MENTION,
  REFERENCE,
} from "@/components/editor/transformers/markdown-reference-transformers";
import { STATUS } from "@/components/editor/transformers/markdown-status-transformer";

// import { TWEET } from "@/components/editor/transformers/markdown-tweet-transformer"

// Tables, with MultiMarkdown's syntax for merged cells.
const TABLE_ROW_REG_EXP = /^(?:\|)(.+)(?:\|)\s?$/;
const TABLE_ROW_DIVIDER_REG_EXP = /^(\| ?:?-+:? ?)+\|\s?$/;

const OTHER_MARKDOWN_TRANSFORMERS = [
  HR,
  IMAGE,
  // EMOJI,
  // TWEET,
  CHECK_LIST,
  // What a cell points at, as anywhere else in the page.
  STATUS,
  REFERENCE,
  PERSON_MENTION,
  ...ELEMENT_TRANSFORMERS,
  ...MULTILINE_ELEMENT_TRANSFORMERS,
  ...TEXT_FORMAT_TRANSFORMERS,
  ...TEXT_MATCH_TRANSFORMERS,
];

/** One row of a markdown table, as MultiMarkdown writes merged cells: a
 * cell followed by an empty `||` spans the next column too, and a cell that
 * reads `^^` is the one above reaching down into this row. */
interface ParsedCell {
  text: string;
  colSpan: number;
  /** `^^`: this position belongs to the cell above. */
  up: boolean;
}

const parseRow = (textContent: string): ParsedCell[] | null => {
  const match = textContent.match(TABLE_ROW_REG_EXP);
  if (!match?.[1]) {
    return null;
  }
  const cells: ParsedCell[] = [];
  // A pipe inside a cell is written `\|` — a link's alias, or the character
  // itself — so only a bare one ends the cell.
  for (const raw of match[1].split(/(?<!\\)\|/)) {
    const segment = raw.replace(/\\\|/g, "|");
    // Nothing at all between two pipes is a span, not an empty cell — an
    // empty cell is written with a space in it.
    if (segment === "" && cells.length > 0) {
      cells[cells.length - 1].colSpan += 1;
      continue;
    }
    cells.push({ text: segment.trim(), colSpan: 1, up: segment.trim() === "^^" });
  }
  return cells;
};

const gridWidth = (cells: ParsedCell[]) => cells.reduce((sum, cell) => sum + cell.colSpan, 0);

/** Append parsed rows to a table, reaching `^^` cells up into the row above
 * and padding a short row out to the table's width. */
function $appendRows(table: TableNode, rows: ParsedCell[][], width: number): void {
  for (const cells of rows) {
    const [map] = $computeTableMapSkipCellCheck(table, null, null);
    const above = map[map.length - 1];
    const row = $createTableRowNode();
    let column = 0;
    for (const cell of cells) {
      const owner = cell.up ? above?.[column]?.cell : undefined;
      if (owner) {
        owner.setRowSpan(owner.getRowSpan() + 1);
      } else {
        const created = $createTableCell(cell.up ? "" : cell.text);
        if (cell.colSpan > 1) {
          created.setColSpan(cell.colSpan);
        }
        row.append(created);
      }
      column += cell.colSpan;
    }
    for (; column < width; column++) {
      row.append($createTableCell(""));
    }
    table.append(row);
  }
}

const tableWidth = (table: TableNode): number => {
  const [map] = $computeTableMapSkipCellCheck(table, null, null);
  return map[0]?.length ?? 0;
};

export const TABLE: ElementTransformer = {
  dependencies: [TableNode, TableRowNode, TableCellNode],
  export: (node: LexicalNode) => {
    if (!$isTableNode(node)) {
      return null;
    }

    const [map] = $computeTableMapSkipCellCheck(node, null, null);
    const width = map[0]?.length ?? 0;
    const output: string[] = [];

    map.forEach((line, rowIndex) => {
      const parts: string[] = [];
      let isHeaderRow = false;
      for (let column = 0; column < width; column++) {
        const entry = line[column];
        if (!entry || entry.startColumn !== column) {
          continue;
        }
        const span = entry.cell.getColSpan();
        const pipes = "|".repeat(Math.max(0, span - 1));
        if (entry.startRow !== rowIndex) {
          parts.push(`| ^^ ${pipes}`);
          continue;
        }
        if (entry.cell.__headerState === TableCellHeaderStates.ROW) {
          isHeaderRow = true;
        }
        const text = $convertToMarkdownString(OTHER_MARKDOWN_TRANSFORMERS, entry.cell)
          .replace(/\n/g, "\\n")
          .replace(/\|/g, "\\|");
        parts.push(`| ${text} ${pipes}`);
      }
      output.push(`${parts.join("")}|`);
      if (isHeaderRow) {
        output.push(`| ${Array.from({ length: width }, () => "---").join(" | ")} |`);
      }
    });

    return output.join("\n");
  },
  regExp: TABLE_ROW_REG_EXP,
  replace: (parentNode, _1, match) => {
    // Header row
    if (TABLE_ROW_DIVIDER_REG_EXP.test(match[0])) {
      const table = parentNode.getPreviousSibling();
      if (!table || !$isTableNode(table)) {
        return;
      }

      const rows = table.getChildren();
      const lastRow = rows[rows.length - 1];
      if (!lastRow || !$isTableRowNode(lastRow)) {
        return;
      }

      // Add header state to row cells
      lastRow.getChildren().forEach((cell) => {
        if (!$isTableCellNode(cell)) {
          return;
        }
        cell.setHeaderStyles(TableCellHeaderStates.ROW, TableCellHeaderStates.ROW);
      });

      // Remove line
      parentNode.remove();
      return;
    }

    const matchCells = parseRow(match[0]);

    if (matchCells == null) {
      return;
    }

    const rows = [matchCells];
    let sibling = parentNode.getPreviousSibling();
    let width = gridWidth(matchCells);

    while (sibling) {
      if (!$isParagraphNode(sibling)) {
        break;
      }

      if (sibling.getChildrenSize() !== 1) {
        break;
      }

      const firstChild = sibling.getFirstChild();

      if (!$isTextNode(firstChild)) {
        break;
      }

      const cells = parseRow(firstChild.getTextContent());

      if (cells == null) {
        break;
      }

      width = Math.max(width, gridWidth(cells));
      rows.unshift(cells);
      const previousSibling = sibling.getPreviousSibling();
      sibling.remove();
      sibling = previousSibling;
    }

    const previousSibling = parentNode.getPreviousSibling();
    if ($isTableNode(previousSibling) && tableWidth(previousSibling) === width) {
      $appendRows(previousSibling, rows, width);
      parentNode.remove();
      previousSibling.selectEnd();
      return;
    }

    const table = $createTableNode();
    $appendRows(table, rows, width);
    parentNode.replace(table);
    table.selectEnd();
  },
  type: "element",
};

const $createTableCell = (textContent: string): TableCellNode => {
  textContent = textContent.replace(/\\n/g, "\n");
  const cell = $createTableCellNode(TableCellHeaderStates.NO_STATUS);
  $convertFromMarkdownString(textContent, OTHER_MARKDOWN_TRANSFORMERS, cell);
  return cell;
};

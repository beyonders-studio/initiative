import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  $computeTableMapSkipCellCheck,
  $deleteTableColumnAtSelection,
  $deleteTableRowAtSelection,
  $getTableNodeFromLexicalNodeOrThrow,
  $insertTableColumnAtSelection,
  $insertTableRowAtSelection,
  $isTableCellNode,
  $isTableSelection,
  $mergeCells,
  $unmergeCell,
  TableCellHeaderStates,
  type TableCellNode,
  type TableNode,
} from "@lexical/table";
import { $getSelection, $isRangeSelection } from "lexical";
import {
  ArrowDownToLine,
  ArrowLeftToLine,
  ArrowRightToLine,
  ArrowUpToLine,
  ChevronDown,
  Heading,
  Merge,
  Split,
  Trash2,
} from "lucide-react";
import { type CSSProperties, type ReactPortal, useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

interface MenuPosition {
  top: number;
  left: number;
  /** More than one cell is selected, so they can become one. */
  canMerge: boolean;
  /** The cell the caret is in spans more than itself. */
  canUnmerge: boolean;
}

function TableActionMenuContainer({ anchorElem }: { anchorElem: HTMLElement }) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const [position, setPosition] = useState<MenuPosition | null>(null);

  // Find the active table cell from the selection; only compute DOM position
  // when the cursor is actually inside a table to avoid unnecessary layout reads.
  const updatePosition = useCallback(() => {
    let cellKey: string | null = null;
    let canMerge = false;
    let canUnmerge = false;

    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if ($isTableSelection(selection)) {
        const cells = selection.getNodes().filter($isTableCellNode);
        canMerge = cells.length > 1;
        cellKey = cells[0]?.getKey() ?? null;
        return;
      }
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      while (node !== null) {
        if ($isTableCellNode(node)) {
          cellKey = node.getKey();
          canUnmerge = node.getColSpan() > 1 || node.getRowSpan() > 1;
          return;
        }
        node = node.getParent();
      }
    });

    if (!cellKey) {
      setPosition((prev) => (prev === null ? prev : null));
      return;
    }

    const cellElement = editor.getElementByKey(cellKey);
    if (!cellElement) {
      setPosition((prev) => (prev === null ? prev : null));
      return;
    }

    const cellRect = cellElement.getBoundingClientRect();
    const anchorRect = anchorElem.getBoundingClientRect();
    setPosition({
      top: cellRect.top - anchorRect.top + 4,
      left: cellRect.right - anchorRect.left - 24,
      canMerge,
      canUnmerge,
    });
  }, [editor, anchorElem]);

  useEffect(() => {
    updatePosition();
    const unregister = editor.registerUpdateListener(() => updatePosition());
    anchorElem.addEventListener("scroll", updatePosition, true);
    return () => {
      unregister();
      anchorElem.removeEventListener("scroll", updatePosition, true);
    };
  }, [editor, updatePosition, anchorElem]);

  // ── Action handlers ─────────────────────────────────────────────────────

  const insertRowAbove = useCallback(() => {
    editor.update(() => {
      $insertTableRowAtSelection(false);
    });
  }, [editor]);

  const insertRowBelow = useCallback(() => {
    editor.update(() => {
      $insertTableRowAtSelection(true);
    });
  }, [editor]);

  const insertColumnLeft = useCallback(() => {
    editor.update(() => {
      $insertTableColumnAtSelection(false);
    });
  }, [editor]);

  const insertColumnRight = useCallback(() => {
    editor.update(() => {
      $insertTableColumnAtSelection(true);
    });
  }, [editor]);

  const deleteRow = useCallback(() => {
    editor.update(() => {
      $deleteTableRowAtSelection();
    });
  }, [editor]);

  const deleteColumn = useCallback(() => {
    editor.update(() => {
      $deleteTableColumnAtSelection();
    });
  }, [editor]);

  const mergeCells = useCallback(() => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isTableSelection(selection)) return;
      $mergeCells(selection.getNodes().filter($isTableCellNode));
    });
  }, [editor]);

  const unmergeCell = useCallback(() => {
    editor.update(() => {
      $unmergeCell();
    });
  }, [editor]);

  const deleteTable = useCallback(() => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      let cellNode: TableCellNode | null = null;
      while (node !== null) {
        if ($isTableCellNode(node)) {
          cellNode = node;
          break;
        }
        node = node.getParent();
      }
      if (!cellNode) return;
      const tableNode: TableNode = $getTableNodeFromLexicalNodeOrThrow(cellNode);
      tableNode.remove();
    });
  }, [editor]);

  // Toggle the header state for the entire row containing the active cell
  const toggleHeaderRow = useCallback(() => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      let activeCell: TableCellNode | null = null;
      while (node !== null) {
        if ($isTableCellNode(node)) {
          activeCell = node;
          break;
        }
        node = node.getParent();
      }
      if (!activeCell) return;
      const rowNode = activeCell.getParent();
      if (!rowNode) return;
      // Apply toggleHeaderStyle to every cell in the row
      for (const child of rowNode.getChildren()) {
        if ($isTableCellNode(child)) {
          child.toggleHeaderStyle(TableCellHeaderStates.ROW);
        }
      }
    });
  }, [editor]);

  // Toggle the header state for the entire column containing the active cell
  const toggleHeaderColumn = useCallback(() => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      let activeCell: TableCellNode | null = null;
      while (node !== null) {
        if ($isTableCellNode(node)) {
          activeCell = node;
          break;
        }
        node = node.getParent();
      }
      if (!activeCell) return;
      const tableNode = $getTableNodeFromLexicalNodeOrThrow(activeCell);
      // The column is found on the table's grid rather than by counting
      // cells in the row: a merged cell earlier in a row shifts every cell
      // after it.
      const [map, cellMap] = $computeTableMapSkipCellCheck(tableNode, activeCell, null);
      const columnIndex = cellMap?.startColumn ?? -1;
      if (columnIndex < 0) return;
      const toggled = new Set<string>();
      for (const row of map) {
        const cell = row[columnIndex]?.cell;
        if (cell && !toggled.has(cell.getKey())) {
          toggled.add(cell.getKey());
          cell.toggleHeaderStyle(TableCellHeaderStates.COLUMN);
        }
      }
    });
  }, [editor]);

  if (!position) {
    return null;
  }

  const style: CSSProperties = {
    position: "absolute",
    top: `${position.top}px`,
    left: `${position.left}px`,
    zIndex: 20,
  };

  return (
    <div style={style}>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="inline-flex h-5 w-5 items-center justify-center rounded border bg-background text-muted-foreground shadow-sm outline-none hover:bg-accent"
          aria-label={t("tableActions")}
        >
          <ChevronDown className="h-3 w-3" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem onSelect={insertRowAbove}>
            <ArrowUpToLine className="h-4 w-4" />
            {t("insertRowAbove")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={insertRowBelow}>
            <ArrowDownToLine className="h-4 w-4" />
            {t("insertRowBelow")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={insertColumnLeft}>
            <ArrowLeftToLine className="h-4 w-4" />
            {t("insertColumnLeft")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={insertColumnRight}>
            <ArrowRightToLine className="h-4 w-4" />
            {t("insertColumnRight")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={deleteRow}>
            <Trash2 className="h-4 w-4" />
            {t("deleteRow")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={deleteColumn}>
            <Trash2 className="h-4 w-4" />
            {t("deleteColumn")}
          </DropdownMenuItem>
          {(position.canMerge || position.canUnmerge) && (
            <>
              <DropdownMenuSeparator />
              {position.canMerge && (
                <DropdownMenuItem onSelect={mergeCells}>
                  <Merge className="h-4 w-4" />
                  {t("mergeCells")}
                </DropdownMenuItem>
              )}
              {position.canUnmerge && (
                <DropdownMenuItem onSelect={unmergeCell}>
                  <Split className="h-4 w-4" />
                  {t("unmergeCells")}
                </DropdownMenuItem>
              )}
            </>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={toggleHeaderRow}>
            <Heading className="h-4 w-4" />
            {t("toggleHeaderRow")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={toggleHeaderColumn}>
            <Heading className="h-4 w-4" />
            {t("toggleHeaderColumn")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={deleteTable} className="text-destructive">
            <Trash2 className="h-4 w-4" />
            {t("deleteTable")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function TableActionMenuPlugin({
  anchorElem = null,
  readOnly = false,
}: {
  anchorElem: HTMLElement | null;
  readOnly?: boolean;
}): ReactPortal | null {
  if (!anchorElem || readOnly) {
    return null;
  }
  return createPortal(<TableActionMenuContainer anchorElem={anchorElem} />, anchorElem);
}

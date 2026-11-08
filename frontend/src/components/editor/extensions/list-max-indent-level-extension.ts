import { $getListDepth, $isListItemNode, $isListNode } from "@lexical/list";
import type { ElementNode, RangeSelection } from "lexical";
import {
  $getSelection,
  $isElementNode,
  $isRangeSelection,
  COMMAND_PRIORITY_CRITICAL,
  defineExtension,
  INDENT_CONTENT_COMMAND,
} from "lexical";

const MAX_DEPTH = 7;

function getElementNodesInSelection(selection: RangeSelection): Set<ElementNode> {
  const nodesInSelection = selection.getNodes();

  if (nodesInSelection.length === 0) {
    return new Set([
      selection.anchor.getNode().getParentOrThrow(),
      selection.focus.getNode().getParentOrThrow(),
    ]);
  }

  return new Set(nodesInSelection.map((n) => ($isElementNode(n) ? n : n.getParentOrThrow())));
}

function $shouldPreventIndent(maxDepth: number): boolean {
  const selection = $getSelection();

  if (!$isRangeSelection(selection)) {
    return false;
  }

  const elementNodesInSelection = getElementNodesInSelection(selection);
  let totalDepth = 0;

  for (const elementNode of Array.from(elementNodesInSelection)) {
    if ($isListNode(elementNode)) {
      totalDepth = Math.max($getListDepth(elementNode) + 1, totalDepth);
    } else if ($isListItemNode(elementNode)) {
      const parent = elementNode.getParent();
      if (!$isListNode(parent)) {
        throw new Error(
          "ListMaxIndentLevelExtension: A ListItemNode must have a ListNode for a parent."
        );
      }
      totalDepth = Math.max($getListDepth(parent) + 1, totalDepth);
    }
  }

  return totalDepth > maxDepth;
}

export const ListMaxIndentLevelExtension = defineExtension({
  name: "@initiative/list-max-indent-level",
  register: (editor) =>
    editor.registerCommand(
      INDENT_CONTENT_COMMAND,
      () => $shouldPreventIndent(MAX_DEPTH),
      COMMAND_PRIORITY_CRITICAL
    ),
});

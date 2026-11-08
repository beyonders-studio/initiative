import { $findMatchingParent, $insertNodeToNearestRoot, mergeRegister } from "@lexical/utils";
import type { ElementNode, LexicalNode } from "lexical";
import {
  $createParagraphNode,
  $getNodeByKey,
  $getSelection,
  $isRangeSelection,
  COMMAND_PRIORITY_EDITOR,
  COMMAND_PRIORITY_LOW,
  defineExtension,
  KEY_ARROW_DOWN_COMMAND,
  KEY_ARROW_LEFT_COMMAND,
  KEY_ARROW_RIGHT_COMMAND,
  KEY_ARROW_UP_COMMAND,
} from "lexical";

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
import {
  INSERT_LAYOUT_COMMAND,
  UPDATE_LAYOUT_COMMAND,
} from "@/components/editor/plugins/layout-plugin";

function getItemsCountFromTemplate(template: string): number {
  return template.trim().split(/\s+/).length;
}

const $onEscape = (before: boolean) => {
  const selection = $getSelection();
  if ($isRangeSelection(selection) && selection.isCollapsed() && selection.anchor.offset === 0) {
    const container = $findMatchingParent(selection.anchor.getNode(), $isLayoutContainerNode);

    if ($isLayoutContainerNode(container)) {
      const parent = container.getParent<ElementNode>();
      const child =
        parent &&
        (before ? parent.getFirstChild<LexicalNode>() : parent?.getLastChild<LexicalNode>());
      const descendant = before
        ? container.getFirstDescendant<LexicalNode>()?.getKey()
        : container.getLastDescendant<LexicalNode>()?.getKey();

      if (parent !== null && child === container && selection.anchor.key === descendant) {
        if (before) {
          container.insertBefore($createParagraphNode());
        } else {
          container.insertAfter($createParagraphNode());
        }
      }
    }
  }

  return false;
};

export const LayoutExtension = defineExtension({
  name: "@initiative/layout",
  nodes: [LayoutContainerNode, LayoutItemNode],
  register: (editor) =>
    mergeRegister(
      editor.registerCommand(KEY_ARROW_DOWN_COMMAND, () => $onEscape(false), COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_ARROW_RIGHT_COMMAND, () => $onEscape(false), COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_ARROW_UP_COMMAND, () => $onEscape(true), COMMAND_PRIORITY_LOW),
      editor.registerCommand(KEY_ARROW_LEFT_COMMAND, () => $onEscape(true), COMMAND_PRIORITY_LOW),
      editor.registerCommand(
        INSERT_LAYOUT_COMMAND,
        (template) => {
          editor.update(() => {
            const container = $createLayoutContainerNode(template);
            const itemsCount = getItemsCountFromTemplate(template);

            for (let i = 0; i < itemsCount; i++) {
              container.append($createLayoutItemNode().append($createParagraphNode()));
            }

            $insertNodeToNearestRoot(container);
            container.selectStart();
          });
          return true;
        },
        COMMAND_PRIORITY_EDITOR
      ),
      editor.registerCommand(
        UPDATE_LAYOUT_COMMAND,
        ({ template, nodeKey }) => {
          editor.update(() => {
            const container = $getNodeByKey<LexicalNode>(nodeKey);

            if (!$isLayoutContainerNode(container)) {
              return;
            }

            const itemsCount = getItemsCountFromTemplate(template);
            const prevItemsCount = getItemsCountFromTemplate(container.getTemplateColumns());

            if (itemsCount > prevItemsCount) {
              for (let i = prevItemsCount; i < itemsCount; i++) {
                container.append($createLayoutItemNode().append($createParagraphNode()));
              }
            } else if (itemsCount < prevItemsCount) {
              for (let i = prevItemsCount - 1; i >= itemsCount; i--) {
                const layoutItem = container.getChildAtIndex<LexicalNode>(i);

                if ($isLayoutItemNode(layoutItem)) {
                  layoutItem.remove();
                }
              }
            }

            container.setTemplateColumns(template);
          });
          return true;
        },
        COMMAND_PRIORITY_EDITOR
      ),
      editor.registerNodeTransform(LayoutItemNode, (node) => {
        const parent = node.getParent<ElementNode>();
        if (!$isLayoutContainerNode(parent)) {
          const children = node.getChildren<LexicalNode>();
          for (const child of children) {
            node.insertBefore(child);
          }
          node.remove();
        }
      }),
      editor.registerNodeTransform(LayoutContainerNode, (node) => {
        const children = node.getChildren<LexicalNode>();
        if (!children.every($isLayoutItemNode)) {
          for (const child of children) {
            node.insertBefore(child);
          }
          node.remove();
        }
      })
    ),
});

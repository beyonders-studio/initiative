import { $wrapNodeInElement } from "@lexical/utils";
import {
  $createParagraphNode,
  $insertNodes,
  $isRootOrShadowRoot,
  COMMAND_PRIORITY_EDITOR,
  createCommand,
  defineExtension,
  type LexicalCommand,
} from "lexical";

import { $createExcalidrawNode, ExcalidrawNode } from "@/components/editor/nodes/excalidraw-node";

/** Insert an empty drawing where the caret is; it opens for drawing at once. */
export const INSERT_EXCALIDRAW_COMMAND: LexicalCommand<void> = createCommand(
  "INSERT_EXCALIDRAW_COMMAND"
);

export const ExcalidrawExtension = defineExtension({
  name: "@initiative/excalidraw",
  nodes: [ExcalidrawNode],
  register: (editor) =>
    editor.registerCommand(
      INSERT_EXCALIDRAW_COMMAND,
      () => {
        const node = $createExcalidrawNode();
        $insertNodes([node]);
        if ($isRootOrShadowRoot(node.getParentOrThrow())) {
          $wrapNodeInElement(node, $createParagraphNode).selectEnd();
        }
        return true;
      },
      COMMAND_PRIORITY_EDITOR
    ),
});

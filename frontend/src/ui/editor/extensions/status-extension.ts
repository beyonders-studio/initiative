import {
  $insertNodes,
  COMMAND_PRIORITY_EDITOR,
  createCommand,
  defineExtension,
  type LexicalCommand,
} from "lexical";

import { $createStatusNode, StatusNode } from "@/ui/editor/nodes/status-node";

/** Insert an empty status at the caret; it opens to be written at once. */
export const INSERT_STATUS_COMMAND: LexicalCommand<void> = createCommand("INSERT_STATUS_COMMAND");

export const StatusExtension = defineExtension({
  name: "@initiative/status",
  nodes: [StatusNode],
  register: (editor) =>
    editor.registerCommand(
      INSERT_STATUS_COMMAND,
      () => {
        $insertNodes([$createStatusNode()]);
        return true;
      },
      COMMAND_PRIORITY_EDITOR
    ),
});

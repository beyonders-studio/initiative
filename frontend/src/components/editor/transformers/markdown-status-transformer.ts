import type { TextMatchTransformer } from "@lexical/markdown";
import type { LexicalNode } from "lexical";

import {
  $createStatusNode,
  $isStatusNode,
  isStatusColor,
  StatusNode,
} from "@/components/editor/nodes/status-node";

/*
 * A status in markdown is a generic text directive — the proposed CommonMark
 * syntax remark-directive and others read:
 *
 *   :status[In progress]{color="blue"}
 *
 * A reader that does not know directives still sees the word.
 */

const DIRECTIVE = /:status\[([^\]\n]+)\](?:\{\s*color\s*=\s*"?([a-z]+)"?\s*\})?/;

export const STATUS: TextMatchTransformer = {
  dependencies: [StatusNode],
  type: "text-match",
  importRegExp: DIRECTIVE,
  regExp: new RegExp(`${DIRECTIVE.source}$`),
  trigger: "}",
  export: (node: LexicalNode) => {
    if (!$isStatusNode(node)) {
      return null;
    }
    const text = node.getText().replace(/[[\]]/g, "");
    return `:status[${text}]{color="${node.getColor()}"}`;
  },
  replace: (textNode, match) => {
    const [, text, color] = match;
    textNode.replace($createStatusNode(text.trim(), isStatusColor(color) ? color : "neutral"));
  },
};

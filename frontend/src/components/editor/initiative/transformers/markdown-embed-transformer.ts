import type { ElementTransformer } from "@lexical/markdown";

import {
  $createReferenceEmbedNode,
  $isReferenceEmbedNode,
  ReferenceEmbedNode,
} from "@/components/editor/initiative/nodes/reference-embed-node";
import { storedEntityType } from "@/lib/smartChips";

/**
 * `![[ ]]` in markdown: the embed with the reference it names ahead of a `|`
 * and the name it had after — `![[task:12|Roll call]]`. The name is what a
 * reader of the raw text sees; the reference is what comes back live. An
 * embed of a filter names no one thing, so it is written as its label.
 */
export const EMBED: ElementTransformer = {
  dependencies: [ReferenceEmbedNode],
  export: (node) => {
    if (!$isReferenceEmbedNode(node)) return null;
    if (node.getQuery()) return node.getTextContent();
    // The name sits between `|` and `]]`, so neither can be in it.
    const name = node.getTextContent().replace(/[|\]]/g, "");
    return `![[${node.getEntityType()}:${node.getEntityId()}|${name}]]`;
  },
  regExp: /^!\[\[([a-z_]+):(\d+)(?:\|([^\]]*))?\]\]\s?$/,
  replace: (parentNode, _children, match) => {
    const [, entityType, entityId, name] = match;
    const kind = storedEntityType(entityType);
    if (!kind) return false;
    parentNode.replace($createReferenceEmbedNode(kind, Number(entityId), name ?? ""));
  },
  type: "element",
};

import { HashtagNode } from "@lexical/hashtag";
import { mergeRegister } from "@lexical/utils";
import {
  $createTextNode,
  $nodesOfType,
  type Klass,
  type LexicalEditor,
  type LexicalNode,
} from "lexical";

/**
 * Node types documents still hold that nothing writes any more.
 *
 * They stay registered so a stored document opens at all — Lexical refuses a
 * type it does not know — and each one is rewritten as current content on the
 * way in.
 */
export const LEGACY_NODES: Klass<LexicalNode>[] = [HashtagNode];

/** What a legacy node is in today's document. */
function $modernize(node: LexicalNode): void {
  if (node instanceof HashtagNode) {
    // `#` opens the reference picker now, so the word after it names a thing
    // rather than styling itself. What was stored reads back as the plain word
    // it already looked like.
    node.replace($createTextNode(node.getTextContent()));
  }
}

/**
 * Rewrites the legacy nodes a document opens with, and any that arrive later.
 *
 * The sweep covers the document as loaded; the transforms cover what a paste or
 * a collaborator's update brings in afterwards. Either way the rewrite reaches
 * storage the next time the document is saved, and a document nobody opens
 * again is left as it is.
 */
export function registerLegacyNodes(editor: LexicalEditor): () => void {
  editor.update(
    () => {
      for (const klass of LEGACY_NODES) {
        for (const node of $nodesOfType(klass)) $modernize(node);
      }
    },
    { discrete: true }
  );
  return mergeRegister(
    ...LEGACY_NODES.map((klass) => editor.registerNodeTransform(klass, $modernize))
  );
}

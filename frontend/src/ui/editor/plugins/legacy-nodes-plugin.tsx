import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useEffect } from "react";

import { registerLegacyNodes } from "@/ui/editor/nodes/legacy-nodes";

/**
 * Reads what older versions of the editor wrote as what it means today.
 *
 * See `legacy-nodes` for which node types those are and what each becomes.
 */
export function LegacyNodesPlugin(): null {
  const [editor] = useLexicalComposerContext();
  useEffect(() => registerLegacyNodes(editor), [editor]);
  return null;
}

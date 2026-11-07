import type { MultilineElementTransformer, TextMatchTransformer } from "@lexical/markdown";
import { $createParagraphNode, type LexicalNode } from "lexical";

import {
  $createExcalidrawNode,
  $isExcalidrawNode,
  ExcalidrawNode,
} from "@/components/editor/nodes/excalidraw-node";

/*
 * A drawing in markdown is its scene in a fenced block tagged `excalidraw`,
 * the way a Mermaid diagram rides in a `mermaid` one:
 *
 *   ```excalidraw
 *   {"elements":[…],"appState":{…},"files":{…}}
 *   ```
 *
 * The fence is made longer than any run of backticks in the scene, so text
 * somebody typed into the drawing cannot close it early.
 */

const START = /^(`{3,})excalidraw\s*$/;

function fenceFor(data: string): string {
  const longest = Math.max(0, ...(data.match(/`+/g) ?? []).map((run) => run.length));
  return "`".repeat(Math.max(3, longest + 1));
}

/** Writing: a drawing sits inline in its paragraph, so it is exported as
 * text — a fence on lines of its own. */
export const EXCALIDRAW_EXPORT: TextMatchTransformer = {
  dependencies: [ExcalidrawNode],
  type: "text-match",
  // Never matched while typing or importing; the block below reads it back.
  regExp: /(?!)/,
  importRegExp: /(?!)/,
  export: (node: LexicalNode) => {
    if (!$isExcalidrawNode(node)) {
      return null;
    }
    const data = node.getData();
    const fence = fenceFor(data);
    return `\n${fence}excalidraw\n${data}\n${fence}\n`;
  },
  replace: () => {},
};

/** Reading: the fenced block back into a drawing, in a paragraph of its own.
 * A block whose contents are not a scene is left for the code block to take. */
export const EXCALIDRAW_IMPORT: MultilineElementTransformer = {
  dependencies: [ExcalidrawNode],
  type: "multiline-element",
  regExpStart: START,
  handleImportAfterStartMatch: ({ lines, rootNode, startLineIndex, startMatch }) => {
    const fence = startMatch[1];
    let end = startLineIndex + 1;
    while (end < lines.length && lines[end].trim() !== fence) {
      end += 1;
    }
    if (end >= lines.length) {
      return null;
    }
    const data = lines.slice(startLineIndex + 1, end).join("\n");
    try {
      const scene = JSON.parse(data) as { elements?: unknown };
      if (!Array.isArray(scene.elements)) {
        return null;
      }
    } catch {
      return null;
    }
    rootNode.append($createParagraphNode().append($createExcalidrawNode(data)));
    return [true, end];
  },
  replace: () => false,
};

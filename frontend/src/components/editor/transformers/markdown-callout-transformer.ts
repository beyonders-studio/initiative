import {
  $convertFromMarkdownString,
  $convertToMarkdownString,
  type MultilineElementTransformer,
  type Transformer,
} from "@lexical/markdown";

import {
  $createCalloutNode,
  $isCalloutNode,
  CalloutNode,
  calloutVariantFrom,
} from "@/components/editor/nodes/callout-node";

/** `> [!info] Optional title` — Obsidian's callout, which GitHub's alerts
 * share. The `+`/`-` after the kind is Obsidian's fold marker: `-` is folded,
 * `+` open, and every callout here can fold, so only `-` changes anything. */
const START = /^>\s*\[!([A-Za-z-]+)\]([+-]?)(?:\s+(.*))?$/;
const QUOTED = /^>\s?/;

/**
 * Callouts to and from markdown. The body is ordinary markdown behind `> `,
 * converted with the same transformers as the rest of the document, so a
 * list or a code block inside one survives the round trip. A title after the
 * kind becomes the callout's first line, in bold.
 *
 * Takes the transformer list lazily: the list it recurses with is the one it
 * is a member of.
 */
export function createCalloutTransformer(
  transformers: () => Transformer[]
): MultilineElementTransformer {
  return {
    dependencies: [CalloutNode],
    type: "multiline-element",
    regExpStart: START,
    export: (node) => {
      if (!$isCalloutNode(node)) {
        return null;
      }
      const body = $convertToMarkdownString(transformers(), node);
      const lines = body === "" ? [] : body.split("\n");
      return [
        `> [!${node.getVariant()}]${node.getCollapsed() ? "-" : ""}`,
        ...lines.map((line) => (line === "" ? ">" : `> ${line}`)),
      ].join("\n");
    },
    handleImportAfterStartMatch: ({ lines, rootNode, startLineIndex, startMatch }) => {
      let end = startLineIndex;
      const body: string[] = [];
      while (end + 1 < lines.length && QUOTED.test(lines[end + 1])) {
        end += 1;
        body.push(lines[end].replace(QUOTED, ""));
      }
      const title = (startMatch[3] ?? "").trim();
      // The title is a line of its own, not the start of the body's first.
      const markdown = [...(title ? [`**${title}**`, ""] : []), ...body].join("\n");
      const callout = $createCalloutNode(calloutVariantFrom(startMatch[1]), startMatch[2] === "-");
      $convertFromMarkdownString(markdown, transformers(), callout);
      rootNode.append(callout);
      return [true, end];
    },
    replace: () => false,
  };
}

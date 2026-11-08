import {
  CHECK_LIST,
  ELEMENT_TRANSFORMERS,
  MULTILINE_ELEMENT_TRANSFORMERS,
  registerMarkdownShortcuts,
  TEXT_FORMAT_TRANSFORMERS,
  TEXT_MATCH_TRANSFORMERS,
  type Transformer,
} from "@lexical/markdown";
import { defineExtension, safeCast } from "lexical";

import { createCalloutTransformer } from "@/components/editor/transformers/markdown-callout-transformer";
import { createColumnsTransformer } from "@/components/editor/transformers/markdown-columns-transformer";
import { EMOJI } from "@/components/editor/transformers/markdown-emoji-transformer";
import {
  EXCALIDRAW_EXPORT,
  EXCALIDRAW_IMPORT,
} from "@/components/editor/transformers/markdown-excalidraw-transformer";
import { HR } from "@/components/editor/transformers/markdown-hr-transformer";
import { IMAGE } from "@/components/editor/transformers/markdown-image-transformer";
import { STATUS } from "@/components/editor/transformers/markdown-status-transformer";
import { createTableTransformer } from "@/components/editor/transformers/markdown-table-transformer";
import { TWEET } from "@/components/editor/transformers/markdown-tweet-transformer";

/** The transformers a document's Markdown is read and written with: the
 *  host's, then the core's. */
export function markdownTransformers(host: readonly Transformer[]): Transformer[] {
  const transformers: Transformer[] = [
    // Ahead of the Markdown their syntax would otherwise be read as.
    ...host,
    // Ahead of the quote it would otherwise be read as.
    createCalloutTransformer(() => transformers),
    createColumnsTransformer(() => transformers),
    // Ahead of the code block a drawing's fence would otherwise be read as.
    EXCALIDRAW_IMPORT,
    EXCALIDRAW_EXPORT,
    createTableTransformer(host.filter((transformer) => transformer.type === "text-match")),
    HR,
    IMAGE,
    EMOJI,
    TWEET,
    CHECK_LIST,
    STATUS,
    ...ELEMENT_TRANSFORMERS,
    ...MULTILINE_ELEMENT_TRANSFORMERS,
    ...TEXT_FORMAT_TRANSFORMERS,
    ...TEXT_MATCH_TRANSFORMERS,
  ];
  return transformers;
}

/**
 * Markdown shortcuts, through the transformers the host adds to the core's.
 * Its output is the whole list, for whatever else reads or writes the
 * document as Markdown.
 */
export const MarkdownShortcutsExtension = defineExtension({
  name: "@initiative/markdown-shortcuts",
  config: safeCast<{ transformers: Transformer[] }>({ transformers: [] }),
  mergeConfig: (config, overrides) => ({
    transformers: [...config.transformers, ...(overrides.transformers ?? [])],
  }),
  build: (_editor, { transformers }) => markdownTransformers(transformers),
  register: (editor, _config, state) => registerMarkdownShortcuts(editor, state.getOutput()),
});

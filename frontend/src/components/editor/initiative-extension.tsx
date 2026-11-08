import i18n from "i18next";
import { configExtension, defineExtension } from "lexical";

import { EntityMentionNode } from "@/components/editor/nodes/entity-mention-node";
import { MentionNode } from "@/components/editor/nodes/mention-node";
import { ReferenceEmbedNode } from "@/components/editor/nodes/reference-embed-node";
import { SmartChipNode } from "@/components/editor/nodes/smart-chip-node";
import { InsertImageDialog } from "@/components/editor/plugins/images-plugin";
import { EMBED } from "@/components/editor/transformers/markdown-embed-transformer";
import {
  PERSON_MENTION,
  REFERENCE,
} from "@/components/editor/transformers/markdown-reference-transformers";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { ImagesExtension } from "@/ui/editor/extensions/images-extension";
import { MarkdownShortcutsExtension } from "@/ui/editor/extensions/markdown-shortcuts-extension";

/**
 * What Initiative adds to the document editor: what a document points at —
 * smart chips, `#` references, embeds and @-mentions, with their Markdown —
 * and pictures from Initiative's uploads and Files.
 *
 * Initiative's editor and the server's are both the core with this added, so
 * the two read and write the same nodes.
 */
export const InitiativeExtension = defineExtension({
  name: "@initiative/initiative",
  nodes: [MentionNode, EntityMentionNode, SmartChipNode, ReferenceEmbedNode],
  dependencies: [
    configExtension(MarkdownShortcutsExtension, {
      // Read ahead of the core's: `![[` would otherwise begin an image, and
      // `@[Ada](4)` hold a link.
      transformers: [EMBED, REFERENCE, PERSON_MENTION],
    }),
    configExtension(ImagesExtension, {
      insert: (editor, showModal) =>
        showModal(i18n.t("editor:insertImage"), (onClose) => (
          <InsertImageDialog activeEditor={editor} onClose={onClose} />
        )),
      resolveSrc: (src) => resolveUploadUrl(src) ?? src,
    }),
  ],
});

import type { TextMatchTransformer } from "@lexical/markdown";
import type { LexicalNode } from "lexical";

import {
  $createEntityMentionNode,
  $isEntityMentionNode,
  EntityMentionNode,
} from "@/components/editor/nodes/entity-mention-node";
import {
  $createMentionNode,
  $isMentionNode,
  MentionNode,
} from "@/components/editor/nodes/mention-node";
import {
  $createSmartChipNode,
  $isSmartChipNode,
  SmartChipNode,
} from "@/components/editor/nodes/smart-chip-node";
import { isSmartChipKind, storedEntityType } from "@/lib/smartChips";

/*
 * What a document points at, written into markdown so that it comes back.
 *
 * The node itself stores only a reference; the name beside a thing is what it
 * said when written, for a reader of the raw text. A person has none: their
 * name is only ever read, so it is not written down here either. Left to
 * Lexical, each would export as its words alone and return as plain words —
 * the link, the chip and the person lost to a trip through the Markdown view.
 *
 *   [[task:12|Roll call]]               a `#` link, Obsidian's wikilink —
 *                                       the embed is the same with a `!`
 *   [[task:12:status|In Progress]]      a smart chip: the link, plus the fact
 *   @[](4)                              a person, as a comment writes one
 *
 * None has a `trigger`: these read and write markdown, and typing a reference
 * is the pickers' job.
 */

/** A label sits between delimiters, so it cannot contain them. */
const label = (text: string, delimiters: RegExp) => text.replace(delimiters, "");

// Not after a `!`, which makes the same brackets an embed.
const LINK = /(?<!!)\[\[([a-z_]+):(\d+)(?::([a-z_]+))?\|([^\]\n]*)\]\]/;

/** A `#` link or a smart chip: the two differ only by the chip's aspect. */
export const REFERENCE: TextMatchTransformer = {
  dependencies: [EntityMentionNode, SmartChipNode],
  type: "text-match",
  importRegExp: LINK,
  regExp: new RegExp(`${LINK.source}$`),
  export: (node: LexicalNode) => {
    if ($isSmartChipNode(node)) {
      return `[[${node.getRef()}|${label(node.getTextContent(), /[|\]]/g)}]]`;
    }
    if ($isEntityMentionNode(node)) {
      const name = label(node.getTextContent(), /[|\]]/g);
      return `[[${node.getEntityType()}:${node.getEntityId()}|${name}]]`;
    }
    return null;
  },
  replace: (textNode, match) => {
    const [, entityType, rawId, aspect, name] = match;
    const entityId = Number(rawId);
    if (aspect !== undefined) {
      const chipKind = `${entityType}:${aspect}`;
      // A fact this build does not offer stays the words it was written as.
      if (!isSmartChipKind(chipKind)) return;
      textNode.replace($createSmartChipNode(chipKind, entityId, name));
      return;
    }
    const kind = storedEntityType(entityType);
    if (!kind) return;
    textNode.replace($createEntityMentionNode(kind, entityId, name));
  },
};

const PERSON = /@\[([^\]\n]*)\]\((\d*)\)/;

/** Somebody named: `@[](4)`. A mention of somebody with no account here
 *  writes their name and an empty id, `@[Ada]()`, and reads back the same.
 *  Older text that names an account as well, `@[Ada](4)`, reads as `@[](4)`. */
export const PERSON_MENTION: TextMatchTransformer = {
  dependencies: [MentionNode],
  type: "text-match",
  importRegExp: PERSON,
  regExp: new RegExp(`${PERSON.source}$`),
  export: (node: LexicalNode) => {
    if (!$isMentionNode(node)) return null;
    return `@[${label(node.getTextContent(), /\]/g)}](${node.getMentionUserId() ?? ""})`;
  },
  replace: (textNode, match) => {
    const [, name, rawId] = match;
    textNode.replace($createMentionNode(name, rawId === "" ? null : Number(rawId)));
  },
};

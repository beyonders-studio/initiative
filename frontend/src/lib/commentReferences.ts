/**
 * What a comment points at.
 *
 * A comment is markdown, and its references are written into the text —
 * `#task[Ship it](12)`, `@[](4)`. A thing's label is what the writer saw when
 * they wrote it, so it is a fallback rather than the answer: what a reader
 * should see is what the thing is called now. A person is stored without one,
 * because their name is only ever read (older text still carries `@[Ada](4)`).
 *
 * This finds them so a whole thread can be resolved in one request, rather than
 * each comment asking for itself.
 */

import { TRIGGER_WORD, typeForTrigger, userMentionSyntax } from "@/lib/mentions";
import { referenceRef } from "@/lib/smartChips";

//: `#task[Label](12)` — the trigger word, then a label, then the id.
const ENTITY_PATTERN = new RegExp(String.raw`#(${TRIGGER_WORD})\[[^\]]*\]\((\d+)\)`, "g");
//: `@[](4)`, or `@[Ada](4)` as it was written before names were left out — the
//: label, then the id.
export const USER_MENTION_PATTERN = /@\[([^\]]*)\]\((\d+)\)/g;

export interface CommentReferences {
  /** `task:12` for every thing named, ready to be read together. */
  refs: string[];
  /** Everyone mentioned, so their current names can be read together. */
  userIds: number[];
}

/** Every reference across a whole thread, deduplicated. */
export const collectCommentReferences = (contents: string[]): CommentReferences => {
  const refs = new Set<string>();
  const userIds = new Set<number>();

  for (const content of contents) {
    for (const [, trigger, id] of content.matchAll(ENTITY_PATTERN)) {
      const entityType = typeForTrigger(trigger);
      // A trigger this build does not know is left alone: the comment still
      // renders, showing the words it was written with.
      if (entityType) refs.add(referenceRef(entityType, Number(id)));
    }
    for (const [, , id] of content.matchAll(USER_MENTION_PATTERN)) {
      userIds.add(Number(id));
    }
  }

  return { refs: [...refs].sort(), userIds: [...userIds].sort((a, b) => a - b) };
};

/**
 * `text` with every nameless mention of somebody `nameOf` knows written out
 * with their name, `@[Ada](4)` — so that text opened for editing says who it
 * points at. A mention `nameOf` cannot name, and one that already carries a
 * name, is left as it is.
 */
export const withMentionNames = (
  text: string,
  nameOf: (userId: number) => string | undefined
): string =>
  text.replace(USER_MENTION_PATTERN, (written, label: string, id: string) => {
    const name = label ? undefined : nameOf(Number(id));
    return name ? userMentionSyntax(name, Number(id)) : written;
  });

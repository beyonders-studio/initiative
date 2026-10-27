/**
 * Remark plugins for rendering comment bodies.
 *
 * Comments are markdown, but they also carry the mention syntax the composer
 * writes — `@[](12)`, `#task[Title](3)`, `#file[…](3)`, `#project[…](3)`.
 * That syntax is shaped like a markdown link, so remark parses it before any
 * text-level pass can see it: the result is a text node ending in the trigger
 * followed by a link whose url is the entity id. `remarkMentions` recognises
 * that pair and folds it back into a single mention node.
 *
 * Working after the parse (rather than pre-processing the raw string) means a
 * mention written inside code stays literal, because remark never turned it
 * into a link there.
 */

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { ENTITY_TRIGGER, TRIGGER_WORDS, typeForTrigger, USER_TRIGGER } from "@/lib/mentions";
import { type MdastNode, visitParents } from "@/lib/remarkProse";

export type MentionType = "user" | SearchEntityType;

/** Trigger text preceding the link, longest first so `#counter` can't shadow
 *  a longer trigger that happens to share its prefix.
 *
 * Derived from the same table the composer writes with, so a kind that can be
 * mentioned can be read back. */
const TRIGGERS: { trigger: string; type: MentionType }[] = [
  ...TRIGGER_WORDS.flatMap((word) => {
    const type = typeForTrigger(word);
    return type ? [{ trigger: `${ENTITY_TRIGGER}${word}`, type }] : [];
  }),
  { trigger: USER_TRIGGER, type: "user" as const },
];

const ENTITY_ID = /^\d+$/;
/** A person is stored by id alone, `@[](12)`; somebody an import could match
 *  to no account, by name alone, `@[Ada]()`. Each is still a mention. */
const PERSON_ID = /^\d*$/;

/** Collect the plain text of a node subtree — a mention's label renders as a
 *  badge or link, so any inline formatting inside it is dropped. */
function textOf(node: MdastNode): string {
  if (typeof node.value === "string") return node.value;
  return (node.children ?? []).map(textOf).join("");
}

/** A trigger only counts at a word boundary, so `email@[x](1)` stays a link. */
function triggerAt(text: string): { trigger: string; type: MentionType } | null {
  for (const candidate of TRIGGERS) {
    if (!text.endsWith(candidate.trigger)) continue;
    const before = text[text.length - candidate.trigger.length - 1];
    if (before === undefined || /[\s([{]/.test(before)) return candidate;
  }
  return null;
}

function mentionNode(type: MentionType, id: string, label: string): MdastNode {
  return {
    type: "mention",
    data: {
      hName: "span",
      hProperties: {
        "data-mention-type": type,
        "data-mention-id": id,
        "data-mention-label": label,
      },
    },
    children: [{ type: "text", value: label }],
  };
}

/** Fold `text-ending-in-trigger` + `link` pairs back into mention nodes. */
export function remarkMentions() {
  return (tree: MdastNode) => {
    visitParents(tree, (parent) => {
      const children = parent.children;
      if (!children) return;

      for (let i = children.length - 1; i >= 0; i--) {
        const link = children[i];
        if (link.type !== "link" || typeof link.url !== "string") continue;

        const previous = children[i - 1];
        if (previous?.type !== "text" || typeof previous.value !== "string") continue;

        const match = triggerAt(previous.value);
        if (!match) continue;

        const label = textOf(link);
        if (match.type === "user") {
          if (!PERSON_ID.test(link.url)) continue;
        } else if (!ENTITY_ID.test(link.url) || !label) {
          continue;
        }

        previous.value = previous.value.slice(0, -match.trigger.length);
        children[i] = mentionNode(match.type, link.url, label);
        if (!previous.value) children.splice(i - 1, 1);
      }
    });
  };
}

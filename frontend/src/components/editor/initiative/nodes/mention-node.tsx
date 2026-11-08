/**
 * Somebody named inside a document — `@Ada`.
 *
 * A `DecoratorNode`, for the same reason `EntityMentionNode` is one: the name
 * it shows is read rather than stored, so a person who changes their name is
 * renamed in every sentence that mentions them, in every document, with none
 * of them edited. It also makes the mention a real chip — a link to their
 * profile, and their card on hover — which a `TextNode` could never host.
 *
 * Somebody with an account is held by id alone: `mentionName` and `text` are
 * serialized empty, so their name is in neither the saved document nor the
 * collaboration state, and is read whenever the chip is drawn. Mention
 * notifications are raised off `mentionUserId` (see `extractMentionUserIds`).
 * A mention with no id — somebody an import could match to no account — has
 * nothing to look up, so it keeps the name it was written with.
 *
 * Documents written when this was a `TextNode`, or before names were left out,
 * carry the same three fields with the name filled in. They load as the same
 * node, and the name is dropped on the way in.
 */

import {
  DecoratorNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import type { JSX } from "react";

import { UserMention } from "@/components/user/UserMention";

export type SerializedMentionNode = Spread<
  {
    mentionName: string;
    mentionUserId?: number | null;
    /** The same as `mentionName`: what a renderer reading `text` shows. */
    text: string;
  },
  SerializedLexicalNode
>;

const MENTION_ATTR = "data-lexical-mention";
const USER_ID_ATTR = "data-mention-user-id";

function $convertMentionElement(domNode: HTMLElement): DOMConversionOutput | null {
  const textContent = domNode.textContent;
  if (textContent === null) return null;
  const userId = domNode.getAttribute(USER_ID_ATTR);
  return { node: $createMentionNode(textContent, userId ? Number(userId) : null) };
}

export class MentionNode extends DecoratorNode<JSX.Element> {
  __mention: string;
  __mentionUserId: number | null;

  static getType(): string {
    return "mention";
  }

  static clone(node: MentionNode): MentionNode {
    return new MentionNode(node.__mention, node.__mentionUserId, node.__key);
  }

  static importJSON(serializedNode: SerializedMentionNode): MentionNode {
    // `text` is what a document written before this was a decorator carries,
    // and it is the same string either way. Only an id-less mention keeps it.
    return $createMentionNode(
      serializedNode.mentionName ?? serializedNode.text ?? "",
      serializedNode.mentionUserId ?? null
    );
  }

  /** `mentionName` is kept only without an id: a person with an account is
   *  named when the chip is drawn, never by what the picker or an older
   *  document said. */
  constructor(mentionName: string, mentionUserId?: number | null, key?: NodeKey) {
    super(key);
    this.__mentionUserId = mentionUserId ?? null;
    this.__mention = this.__mentionUserId === null ? mentionName : "";
  }

  exportJSON(): SerializedMentionNode {
    return {
      ...super.exportJSON(),
      mentionName: this.__mention,
      mentionUserId: this.__mentionUserId,
      text: this.__mention,
      type: "mention",
      version: 1,
    };
  }

  getMentionUserId(): number | null {
    return this.__mentionUserId;
  }

  getTextContent(): string {
    return this.__mention;
  }

  createDOM(): HTMLElement {
    const dom = document.createElement("span");
    dom.className = "inline-block align-baseline";
    return dom;
  }

  updateDOM(): false {
    return false;
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("span");
    element.setAttribute(MENTION_ATTR, "true");
    if (this.__mentionUserId !== null) {
      element.setAttribute(USER_ID_ATTR, String(this.__mentionUserId));
    }
    element.textContent = this.__mention;
    return { element };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) =>
        domNode.hasAttribute(MENTION_ATTR)
          ? { conversion: $convertMentionElement, priority: 1 }
          : null,
    };
  }

  /** Inline: a mention sits in a sentence. */
  isInline(): true {
    return true;
  }

  isKeyboardSelectable(): true {
    return true;
  }

  decorate(): JSX.Element {
    return <UserMention userId={this.__mentionUserId} fallback={this.__mention} />;
  }
}

export function $createMentionNode(
  mentionName: string,
  mentionUserId?: number | null
): MentionNode {
  return new MentionNode(mentionName, mentionUserId);
}

export function $isMentionNode(node: LexicalNode | null | undefined): node is MentionNode {
  return node instanceof MentionNode;
}

/**
 * A live chip in a document: `task:12:status`, rendered as whatever that task's
 * column says right now.
 *
 * A `DecoratorNode` rather than a `TextNode`, because the chip has to re-render
 * when the thing changes and a text node cannot without the document being
 * edited — which in a shared document would be a stream of edits from whoever
 * happened to have it open.
 *
 * It still serializes `text`, and that is deliberate: the export renderers
 * degrade any node carrying `text` to its text, and the search index reads
 * `$.**.text`. So a chip exports and is findable by the label it had when it
 * was inserted, while the app shows the live one. A PDF cannot poll.
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

import type { SmartChipKind } from "@/api/generated/initiativeAPI.schemas";
import { SmartChip } from "@/components/editor/nodes/smart-chip";
import { chipRef, isSmartChipKind } from "@/lib/smartChips";

export type SerializedSmartChipNode = Spread<
  {
    chipKind: SmartChipKind;
    entityId: number;
    /** The label as it read when inserted — what an export shows, and what the
     *  chip falls back to when the thing cannot be read. */
    text: string;
  },
  SerializedLexicalNode
>;

const CHIP_ATTR = "data-lexical-smart-chip";
const ENTITY_ATTR = "data-entity-id";

function $convertSmartChipElement(domNode: HTMLElement): DOMConversionOutput | null {
  const chipKind = domNode.getAttribute(CHIP_ATTR);
  const entityId = Number(domNode.getAttribute(ENTITY_ATTR));
  // A pair this build does not know, or an id that is not one, is left as the
  // text it was rendering — better a stale word than a chip pointing nowhere.
  if (!chipKind || !isSmartChipKind(chipKind) || !Number.isFinite(entityId)) return null;
  return {
    node: $createSmartChipNode(chipKind, entityId, domNode.textContent ?? ""),
  };
}

export class SmartChipNode extends DecoratorNode<JSX.Element> {
  __chipKind: SmartChipKind;
  __entityId: number;
  __text: string;

  static getType(): string {
    return "smart-chip";
  }

  static clone(node: SmartChipNode): SmartChipNode {
    return new SmartChipNode(node.__chipKind, node.__entityId, node.__text, node.__key);
  }

  static importJSON(serialized: SerializedSmartChipNode): SmartChipNode {
    return $createSmartChipNode(serialized.chipKind, serialized.entityId, serialized.text);
  }

  constructor(chipKind: SmartChipKind, entityId: number, text: string, key?: NodeKey) {
    super(key);
    this.__chipKind = chipKind;
    this.__entityId = entityId;
    this.__text = text;
  }

  exportJSON(): SerializedSmartChipNode {
    return {
      ...super.exportJSON(),
      chipKind: this.__chipKind,
      entityId: this.__entityId,
      text: this.__text,
      type: "smart-chip",
      version: 1,
    };
  }

  /** The reference this chip reads — what the scope collects and asks for. */
  getRef(): string {
    return chipRef(this.__chipKind, this.__entityId);
  }

  getChipKind(): SmartChipKind {
    return this.__chipKind;
  }

  getEntityId(): number {
    return this.__entityId;
  }

  getTextContent(): string {
    return this.__text;
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
    element.setAttribute(CHIP_ATTR, this.__chipKind);
    element.setAttribute(ENTITY_ATTR, String(this.__entityId));
    element.textContent = this.__text;
    return { element };
  }

  /** Reads back what `exportDOM` wrote, so a chip survives being copied and
   *  pasted as a live chip rather than arriving as the words it happened to
   *  show. */
  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) => {
        if (!domNode.hasAttribute(CHIP_ATTR)) return null;
        return { conversion: $convertSmartChipElement, priority: 1 };
      },
    };
  }

  /** Inline: a chip sits in a sentence, not between paragraphs. */
  isInline(): true {
    return true;
  }

  isKeyboardSelectable(): true {
    return true;
  }

  decorate(): JSX.Element {
    return (
      <SmartChip chipKind={this.__chipKind} entityId={this.__entityId} fallback={this.__text} />
    );
  }
}

export function $createSmartChipNode(
  chipKind: SmartChipKind,
  entityId: number,
  text: string
): SmartChipNode {
  return new SmartChipNode(chipKind, entityId, text);
}

export function $isSmartChipNode(node: LexicalNode | null | undefined): node is SmartChipNode {
  return node instanceof SmartChipNode;
}

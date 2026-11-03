/**
 * A thing named inside a document — `#task`, `[[Queue]]`, and anything else
 * that points at work.
 *
 * A `DecoratorNode`, because the name it shows is read rather than stored: it
 * renders what the thing is called NOW, so a rename reaches every document
 * that mentions it without any of them being edited.
 *
 * It still serializes `text`, and that is deliberate. The export renderers
 * degrade any node carrying `text` to its text, and the search index reads
 * `$.**.text`, so a reference exports and is findable by the name it had when
 * it was written. A PDF cannot poll.
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

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { EditorEntityReference } from "@/components/ui/editor/nodes/entity-reference";
import { storedEntityType } from "@/lib/smartChips";

export type SerializedEntityMentionNode = Spread<
  {
    entityType: SearchEntityType;
    entityId: number;
    /** The name as it read when written — the export and index fallback. */
    text: string;
  },
  SerializedLexicalNode
>;

const TYPE_ATTR = "data-lexical-entity-mention";
const ID_ATTR = "data-entity-id";

function $convertEntityMentionElement(domNode: HTMLElement): DOMConversionOutput | null {
  const entityType = storedEntityType(domNode.getAttribute(TYPE_ATTR) ?? "");
  const entityId = Number(domNode.getAttribute(ID_ATTR));
  if (!entityType || !Number.isFinite(entityId)) return null;
  return {
    node: $createEntityMentionNode(entityType, entityId, domNode.textContent ?? ""),
  };
}

export class EntityMentionNode extends DecoratorNode<JSX.Element> {
  __entityType: SearchEntityType;
  __entityId: number;
  __text: string;

  static getType(): string {
    return "entity-mention";
  }

  static clone(node: EntityMentionNode): EntityMentionNode {
    return new EntityMentionNode(node.__entityType, node.__entityId, node.__text, node.__key);
  }

  static importJSON(serialized: SerializedEntityMentionNode): EntityMentionNode {
    return $createEntityMentionNode(
      storedEntityType(serialized.entityType) ?? serialized.entityType,
      serialized.entityId,
      serialized.text ?? ""
    );
  }

  constructor(entityType: SearchEntityType, entityId: number, text: string, key?: NodeKey) {
    super(key);
    this.__entityType = entityType;
    this.__entityId = entityId;
    this.__text = text;
  }

  exportJSON(): SerializedEntityMentionNode {
    return {
      ...super.exportJSON(),
      entityType: this.__entityType,
      entityId: this.__entityId,
      text: this.__text,
      type: "entity-mention",
      version: 1,
    };
  }

  getEntityType(): SearchEntityType {
    return this.__entityType;
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
    element.setAttribute(TYPE_ATTR, this.__entityType);
    element.setAttribute(ID_ATTR, String(this.__entityId));
    element.textContent = this.__text;
    return { element };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) =>
        domNode.hasAttribute(TYPE_ATTR)
          ? { conversion: $convertEntityMentionElement, priority: 1 }
          : null,
    };
  }

  /** Inline: a reference sits in a sentence. */
  isInline(): true {
    return true;
  }

  isKeyboardSelectable(): true {
    return true;
  }

  decorate(): JSX.Element {
    return (
      <EditorEntityReference
        entityType={this.__entityType}
        entityId={this.__entityId}
        fallback={this.__text}
        nodeKey={this.getKey()}
      />
    );
  }
}

export function $createEntityMentionNode(
  entityType: SearchEntityType,
  entityId: number,
  text: string
): EntityMentionNode {
  return new EntityMentionNode(entityType, entityId, text);
}

export function $isEntityMentionNode(
  node: LexicalNode | null | undefined
): node is EntityMentionNode {
  return node instanceof EntityMentionNode;
}

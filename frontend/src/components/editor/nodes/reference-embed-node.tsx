/**
 * A reference shown in full — `![[ ]]` where `#` shows a name.
 *
 * The same reference a `#` link holds (`task:12`), drawn as a callout: what
 * the thing is called now, and what it says about itself. Nothing but the
 * reference is stored, so a rename or a rewritten description reaches every
 * page that embeds it without any of them being edited.
 *
 * Like the link, it serializes `text` — the name it had when written — which
 * is what an export shows and what the search index reads.
 *
 * It folds to its name, and folded is saved with the page, as a callout's is.
 *
 * What it shows is its `display`: the thing's card, or the facts about it
 * that matter here. With a `query` it shows tasks matching a filter instead —
 * a list, a table or a count — and names no one thing: its `entityId` is 0,
 * which every reader of stored pages already passes over, and `text` is the
 * label its author gave it.
 */

import { addClassNamesToElement } from "@lexical/utils";
import {
  $createParagraphNode,
  $isElementNode,
  $isTextNode,
  DecoratorNode,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import type { JSX } from "react";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  $createEntityMentionNode,
  type EntityMentionNode,
} from "@/components/editor/nodes/entity-mention-node";
import { ReferenceEmbed } from "@/components/editor/nodes/reference-embed";
import { CARD, type EmbedDisplay, readDisplay, readQuery, type TaskQuery } from "@/lib/embeds";
import { storedEntityType } from "@/lib/smartChips";

export type SerializedReferenceEmbedNode = Spread<
  {
    entityType: SearchEntityType;
    entityId: number;
    /** The name as it read when written — the export and index fallback. */
    text: string;
    /** Folded to its name. Absent in anything saved before embeds could fold,
     * which reads as open. */
    collapsed?: boolean;
    /** How it draws. Absent in anything saved before it had a choice: a card. */
    display?: EmbedDisplay;
    /** The tasks it shows, for an embed of a filter rather than of one thing. */
    query?: TaskQuery | null;
  },
  SerializedLexicalNode
>;

const TYPE_ATTR = "data-lexical-reference-embed";
const ID_ATTR = "data-entity-id";
const CONFIG_ATTR = "data-embed-config";

function $convertEmbedElement(domNode: HTMLElement): DOMConversionOutput | null {
  const entityType = storedEntityType(domNode.getAttribute(TYPE_ATTR) ?? "");
  const entityId = Number(domNode.getAttribute(ID_ATTR));
  if (!entityType || !Number.isFinite(entityId)) return null;
  let config: { display?: unknown; query?: unknown } = {};
  try {
    config = JSON.parse(domNode.getAttribute(CONFIG_ATTR) ?? "{}");
  } catch {
    // A pasted embed whose settings did not survive is still its card.
  }
  return {
    node: new ReferenceEmbedNode(
      entityType,
      entityId,
      domNode.textContent ?? "",
      undefined,
      false,
      readDisplay(config.display),
      readQuery(config.query)
    ),
  };
}

export class ReferenceEmbedNode extends DecoratorNode<JSX.Element> {
  __entityType: SearchEntityType;
  __entityId: number;
  __text: string;
  __collapsed: boolean;
  __display: EmbedDisplay;
  __query: TaskQuery | null;

  static getType(): string {
    return "reference-embed";
  }

  static clone(node: ReferenceEmbedNode): ReferenceEmbedNode {
    return new ReferenceEmbedNode(
      node.__entityType,
      node.__entityId,
      node.__text,
      node.__key,
      node.__collapsed,
      node.__display,
      node.__query
    );
  }

  static importJSON(serialized: SerializedReferenceEmbedNode): ReferenceEmbedNode {
    return new ReferenceEmbedNode(
      storedEntityType(serialized.entityType) ?? serialized.entityType,
      serialized.entityId,
      serialized.text,
      undefined,
      serialized.collapsed === true,
      readDisplay(serialized.display),
      readQuery(serialized.query)
    );
  }

  constructor(
    entityType: SearchEntityType,
    entityId: number,
    text: string,
    key?: NodeKey,
    collapsed = false,
    display: EmbedDisplay = CARD,
    query: TaskQuery | null = null
  ) {
    super(key);
    this.__entityType = entityType;
    this.__entityId = entityId;
    this.__text = text;
    this.__collapsed = collapsed;
    this.__display = display;
    this.__query = query;
  }

  exportJSON(): SerializedReferenceEmbedNode {
    return {
      ...super.exportJSON(),
      entityType: this.__entityType,
      entityId: this.__entityId,
      text: this.__text,
      collapsed: this.__collapsed,
      display: this.__display,
      ...(this.__query && { query: this.__query }),
      type: "reference-embed",
      version: 2,
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

  getCollapsed(): boolean {
    return this.getLatest().__collapsed;
  }

  setCollapsed(collapsed: boolean): this {
    const writable = this.getWritable();
    writable.__collapsed = collapsed;
    return writable;
  }

  getDisplay(): EmbedDisplay {
    return this.getLatest().__display;
  }

  getQuery(): TaskQuery | null {
    return this.getLatest().__query;
  }

  /** What it shows, changed from its settings. */
  setShown(display: EmbedDisplay, query: TaskQuery | null, text: string): this {
    const writable = this.getWritable();
    writable.__display = display;
    writable.__query = query;
    writable.__text = text;
    return writable;
  }

  /** Drawn as a callout — the same panel, colour and mark. */
  createDOM(config: EditorConfig): HTMLElement {
    const dom = document.createElement("div");
    dom.setAttribute("data-callout", "note");
    if (typeof config.theme.callout === "string") {
      addClassNamesToElement(dom, config.theme.callout);
    }
    return dom;
  }

  updateDOM(): false {
    return false;
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("div");
    element.setAttribute(TYPE_ATTR, this.__entityType);
    element.setAttribute(ID_ATTR, String(this.__entityId));
    if (this.__query || this.__display.mode !== CARD.mode) {
      element.setAttribute(
        CONFIG_ATTR,
        JSON.stringify({ display: this.__display, query: this.__query })
      );
    }
    element.textContent = this.__text;
    return { element };
  }

  /** Reads back what `exportDOM` wrote, so a copied embed pastes live. */
  static importDOM(): DOMConversionMap | null {
    return {
      div: (domNode: HTMLElement) =>
        domNode.hasAttribute(TYPE_ATTR) ? { conversion: $convertEmbedElement, priority: 2 } : null,
    };
  }

  isInline(): false {
    return false;
  }

  isKeyboardSelectable(): true {
    return true;
  }

  decorate(): JSX.Element {
    return (
      <ReferenceEmbed
        entityType={this.__entityType}
        entityId={this.__entityId}
        fallback={this.__text}
        collapsed={this.__collapsed}
        display={this.__display}
        query={this.__query}
        nodeKey={this.getKey()}
      />
    );
  }
}

export function $createReferenceEmbedNode(
  entityType: SearchEntityType,
  entityId: number,
  text: string
): ReferenceEmbedNode {
  return new ReferenceEmbedNode(entityType, entityId, text);
}

/** An embed of the tasks a filter matches, under the label its author gave. */
export function $createTaskQueryEmbedNode(
  query: TaskQuery,
  display: EmbedDisplay,
  text: string
): ReferenceEmbedNode {
  return new ReferenceEmbedNode("task", 0, text, undefined, false, display, query);
}

export function $isReferenceEmbedNode(
  node: LexicalNode | null | undefined
): node is ReferenceEmbedNode {
  return node instanceof ReferenceEmbedNode;
}

/**
 * Put an embed where something inline stood — a `#` link, or the `![[` typed
 * to ask for one. An embed is a block, so it takes the line over when that
 * leaves nothing else on it and goes on the line after when it does; either
 * way the caret lands after it, to keep writing.
 */
export function $placeEmbed(inline: LexicalNode, embed: ReferenceEmbedNode): void {
  const block = inline.getTopLevelElementOrThrow();
  inline.remove();
  const empty =
    $isElementNode(block) &&
    block
      .getChildren()
      .every((child) => $isTextNode(child) && child.getTextContent().trim() === "");
  if (empty) block.replace(embed);
  else block.insertAfter(embed);
  const next = embed.getNextSibling();
  if ($isElementNode(next)) {
    next.selectStart();
    return;
  }
  const paragraph = $createParagraphNode();
  embed.insertAfter(paragraph);
  paragraph.select();
}

/** A `#` link shown in full instead. */
export function $showAsEmbed(link: EntityMentionNode): void {
  $placeEmbed(
    link,
    $createReferenceEmbedNode(link.getEntityType(), link.getEntityId(), link.getTextContent())
  );
}

/** An embed back to a `#` link, on a line of its own. */
export function $showAsLink(embed: ReferenceEmbedNode): void {
  const paragraph = $createParagraphNode().append(
    $createEntityMentionNode(embed.getEntityType(), embed.getEntityId(), embed.getTextContent())
  );
  embed.replace(paragraph);
  paragraph.selectEnd();
}

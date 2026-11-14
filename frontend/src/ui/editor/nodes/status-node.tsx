import {
  $applyNodeReplacement,
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

import { StatusPill } from "@/ui/editor/editor-ui/status-pill";

/** The colours a status can be — Confluence's set, which is also what most
 * people reach for: grey for not started, blue for going, green for done. */
export const STATUS_COLORS = ["neutral", "blue", "green", "yellow", "red", "purple"] as const;
export type StatusColor = (typeof STATUS_COLORS)[number];

export const isStatusColor = (value: unknown): value is StatusColor =>
  typeof value === "string" && (STATUS_COLORS as readonly string[]).includes(value);

export type SerializedStatusNode = Spread<
  {
    /** The word on the pill. Named `text` so search and exports read it. */
    text: string;
    color: StatusColor;
  },
  SerializedLexicalNode
>;

const STATUS_ATTR = "data-lexical-status";

function $convertStatusElement(domNode: HTMLElement): DOMConversionOutput | null {
  const color = domNode.getAttribute(STATUS_ATTR);
  const text = domNode.textContent?.trim() ?? "";
  if (!text) return null;
  return { node: $createStatusNode(text, isStatusColor(color) ? color : "neutral") };
}

/**
 * A status written by hand: a word in a coloured pill — "Done", "Blocked",
 * "Waiting on legal". Unlike a smart chip it reads nothing; it says what
 * somebody set it to, the way a status lozenge does in Confluence.
 */
export class StatusNode extends DecoratorNode<JSX.Element> {
  __text: string;
  __color: StatusColor;

  static getType(): string {
    return "status";
  }

  static clone(node: StatusNode): StatusNode {
    return new StatusNode(node.__text, node.__color, node.__key);
  }

  static importJSON(serialized: SerializedStatusNode): StatusNode {
    return $createStatusNode(
      serialized.text ?? "",
      isStatusColor(serialized.color) ? serialized.color : "neutral"
    );
  }

  exportJSON(): SerializedStatusNode {
    return { type: "status", version: 1, text: this.getText(), color: this.getColor() };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      span: (domNode: HTMLElement) =>
        domNode.hasAttribute(STATUS_ATTR)
          ? { conversion: $convertStatusElement, priority: 2 }
          : null,
    };
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("span");
    element.setAttribute(STATUS_ATTR, this.getColor());
    element.textContent = this.getText();
    return { element };
  }

  constructor(text = "", color: StatusColor = "neutral", key?: NodeKey) {
    super(key);
    this.__text = text;
    this.__color = color;
  }

  createDOM(): HTMLElement {
    return document.createElement("span");
  }

  updateDOM(): false {
    return false;
  }

  isInline(): true {
    return true;
  }

  getTextContent(): string {
    return this.getText();
  }

  getText(): string {
    return this.getLatest().__text;
  }

  getColor(): StatusColor {
    return this.getLatest().__color;
  }

  setStatus(text: string, color: StatusColor): this {
    const writable = this.getWritable();
    writable.__text = text;
    writable.__color = color;
    return writable;
  }

  decorate(): JSX.Element {
    return <StatusPill nodeKey={this.getKey()} text={this.__text} color={this.__color} />;
  }
}

export function $createStatusNode(text = "", color: StatusColor = "neutral"): StatusNode {
  return $applyNodeReplacement(new StatusNode(text, color));
}

export function $isStatusNode(node: LexicalNode | null | undefined): node is StatusNode {
  return node instanceof StatusNode;
}

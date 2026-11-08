import {
  $applyNodeReplacement,
  DecoratorNode,
  type DOMExportOutput,
  type EditorConfig,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import * as React from "react";
import { type JSX, Suspense } from "react";

const ExcalidrawComponent = React.lazy(() => import("../editor-ui/excalidraw-component"));

/** An empty drawing: no elements, nothing set, no pictures. */
export const EMPTY_DRAWING = JSON.stringify({ elements: [], appState: {}, files: {} });

export type SerializedExcalidrawNode = Spread<
  {
    /** The Excalidraw scene, as a JSON string: `{elements, appState, files}`
     * — the same shape a whiteboard file keeps. */
    data: string;
    /** The preview's width in CSS pixels, 0 for as drawn. */
    width: number;
  },
  SerializedLexicalNode
>;

/**
 * A drawing inside a document. The page shows it as a picture; opening it
 * brings up the whiteboard editor on just this drawing, and saving writes the
 * scene back onto the node. It is the whiteboard file's canvas in a
 * block's clothing, so a drawing moves between the two unchanged.
 */
export class ExcalidrawNode extends DecoratorNode<JSX.Element> {
  __data: string;
  __width: number;

  static getType(): string {
    return "excalidraw";
  }

  static clone(node: ExcalidrawNode): ExcalidrawNode {
    return new ExcalidrawNode(node.__data, node.__width, node.__key);
  }

  static importJSON(serialized: SerializedExcalidrawNode): ExcalidrawNode {
    return $createExcalidrawNode(serialized.data || EMPTY_DRAWING, serialized.width ?? 0);
  }

  exportJSON(): SerializedExcalidrawNode {
    return {
      data: this.getData(),
      type: "excalidraw",
      version: 1,
      width: this.getWidth(),
    };
  }

  constructor(data: string = EMPTY_DRAWING, width = 0, key?: NodeKey) {
    super(key);
    this.__data = data;
    this.__width = width;
  }

  createDOM(config: EditorConfig): HTMLElement {
    const span = document.createElement("span");
    const className = config.theme.excalidraw;
    if (typeof className === "string") {
      span.className = className;
    }
    return span;
  }

  updateDOM(): false {
    return false;
  }

  exportDOM(): DOMExportOutput {
    // A drawing has no HTML of its own; copied out of the editor it is a
    // placeholder, and pasted back it is text.
    const element = document.createElement("span");
    element.textContent = "[drawing]";
    return { element };
  }

  getData(): string {
    return this.getLatest().__data;
  }

  setData(data: string): this {
    const writable = this.getWritable();
    writable.__data = data;
    return writable;
  }

  getWidth(): number {
    return this.getLatest().__width;
  }

  setWidth(width: number): this {
    const writable = this.getWritable();
    writable.__width = width;
    return writable;
  }

  decorate(): JSX.Element {
    return (
      <Suspense fallback={null}>
        <ExcalidrawComponent nodeKey={this.getKey()} data={this.__data} width={this.__width} />
      </Suspense>
    );
  }
}

export function $createExcalidrawNode(data: string = EMPTY_DRAWING, width = 0): ExcalidrawNode {
  return $applyNodeReplacement(new ExcalidrawNode(data, width));
}

export function $isExcalidrawNode(node: LexicalNode | null | undefined): node is ExcalidrawNode {
  return node instanceof ExcalidrawNode;
}

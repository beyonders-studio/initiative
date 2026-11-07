import { addClassNamesToElement } from "@lexical/utils";
import {
  $applyNodeReplacement,
  $getNodeByKey,
  type DOMConversionMap,
  type DOMConversionOutput,
  type DOMExportOutput,
  type EditorConfig,
  type ElementDOMSlot,
  ElementNode,
  type LexicalEditor,
  type LexicalNode,
  type LexicalUpdateJSON,
  type NodeKey,
  type SerializedElementNode,
  type Spread,
} from "lexical";

import i18n from "@/i18n";

/** The kinds of callout, each with its own colour and icon. The names are
 * the ones Obsidian writes as `> [!info]`, so a callout survives the trip to
 * markdown and back. */
export const CALLOUT_VARIANTS = ["info", "note", "tip", "success", "warning", "error"] as const;
export type CalloutVariant = (typeof CALLOUT_VARIANTS)[number];

export const isCalloutVariant = (value: unknown): value is CalloutVariant =>
  typeof value === "string" && (CALLOUT_VARIANTS as readonly string[]).includes(value);

/** Other names for the same kinds, as other tools write them. */
const VARIANT_ALIASES: Record<string, CalloutVariant> = {
  abstract: "note",
  summary: "note",
  tldr: "note",
  todo: "info",
  hint: "tip",
  important: "tip",
  check: "success",
  done: "success",
  question: "info",
  help: "info",
  faq: "info",
  caution: "warning",
  attention: "warning",
  failure: "error",
  fail: "error",
  missing: "error",
  danger: "error",
  bug: "error",
  example: "note",
  quote: "note",
  cite: "note",
  panel: "note",
};

/** A callout kind from whatever another tool called it; anything unknown is
 * a plain note rather than a refusal. */
export function calloutVariantFrom(name: string | null | undefined): CalloutVariant {
  const key = (name ?? "").trim().toLowerCase();
  if (isCalloutVariant(key)) {
    return key;
  }
  return VARIANT_ALIASES[key] ?? "note";
}

export type SerializedCalloutNode = Spread<
  {
    variant: CalloutVariant;
    /** Folded to its first line. Absent in anything saved before callouts
     * could fold, which reads as open. */
    collapsed?: boolean;
  },
  SerializedElementNode
>;

const BODY_CLASS = "callout-body";
const TOGGLE_CLASS = "callout-toggle";

/** Mark a callout's element folded or open, and its button to match. */
function showCollapsed(dom: HTMLElement, collapsed: boolean): void {
  dom.toggleAttribute("data-collapsed", collapsed);
  const toggle = dom.querySelector<HTMLElement>(`:scope > .${TOGGLE_CLASS}`);
  if (toggle) {
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute(
      "aria-label",
      i18n.t(collapsed ? "editor:expandCallout" : "editor:collapseCallout")
    );
  }
}

function $convertCalloutElement(domNode: HTMLElement): DOMConversionOutput | null {
  const variant = calloutVariantFrom(domNode.getAttribute("data-callout"));
  return { node: $createCalloutNode(variant) };
}

/**
 * A callout: a coloured panel with an icon, holding ordinary blocks —
 * paragraphs, lists, code — rather than a single run of text the way a quote
 * does. Its children are its body; the icon is decoration the editor draws
 * around them, never text in the document.
 *
 * It folds to its first line, which is where a title goes — an Obsidian
 * callout's title is imported as that line. Folded is part of the document,
 * saved for everyone; a reader who cannot edit folds and opens it for
 * themselves only.
 */
export class CalloutNode extends ElementNode {
  __variant: CalloutVariant;
  __collapsed: boolean;

  static getType(): string {
    return "callout";
  }

  static clone(node: CalloutNode): CalloutNode {
    return new CalloutNode(node.__variant, node.__key, node.__collapsed);
  }

  constructor(variant: CalloutVariant = "info", key?: NodeKey, collapsed = false) {
    super(key);
    this.__variant = variant;
    this.__collapsed = collapsed;
  }

  static importJSON(serialized: SerializedCalloutNode): CalloutNode {
    return $createCalloutNode().updateFromJSON(serialized);
  }

  updateFromJSON(serialized: LexicalUpdateJSON<SerializedCalloutNode>): this {
    return super
      .updateFromJSON(serialized)
      .setVariant(calloutVariantFrom(serialized.variant))
      .setCollapsed(serialized.collapsed === true);
  }

  exportJSON(): SerializedCalloutNode {
    return {
      ...super.exportJSON(),
      type: "callout",
      variant: this.getVariant(),
      collapsed: this.getCollapsed(),
      version: 1,
    };
  }

  static importDOM(): DOMConversionMap | null {
    return {
      div: (domNode: HTMLElement) =>
        domNode.hasAttribute("data-callout")
          ? { conversion: $convertCalloutElement, priority: 2 }
          : null,
    };
  }

  exportDOM(): DOMExportOutput {
    const element = document.createElement("div");
    element.setAttribute("data-callout", this.getVariant());
    return { element };
  }

  createDOM(config: EditorConfig, editor: LexicalEditor): HTMLElement {
    const dom = document.createElement("div");
    dom.setAttribute("data-callout", this.__variant);
    if (typeof config.theme.callout === "string") {
      addClassNamesToElement(dom, config.theme.callout);
    }
    const icon = document.createElement("span");
    icon.className = "callout-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.contentEditable = "false";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = TOGGLE_CLASS;
    toggle.contentEditable = "false";
    // Pressing it leaves the caret where it was.
    toggle.addEventListener("mousedown", (event) => event.preventDefault());
    const key = this.__key;
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const collapsed = !dom.hasAttribute("data-collapsed");
      if (!editor.isEditable()) {
        showCollapsed(dom, collapsed);
        return;
      }
      editor.update(() => {
        const node = $getNodeByKey(key);
        if ($isCalloutNode(node)) node.setCollapsed(collapsed);
      });
    });
    const body = document.createElement("div");
    body.className = BODY_CLASS;
    dom.append(icon, toggle, body);
    showCollapsed(dom, this.__collapsed);
    return dom;
  }

  getDOMSlot(element: HTMLElement): ElementDOMSlot<HTMLElement> {
    const body = element.querySelector<HTMLElement>(`:scope > .${BODY_CLASS}`);
    const slot = super.getDOMSlot(element);
    return body ? slot.withElement(body) : slot;
  }

  updateDOM(prevNode: this, dom: HTMLElement): boolean {
    if (prevNode.__variant !== this.__variant) {
      dom.setAttribute("data-callout", this.__variant);
    }
    if (prevNode.__collapsed !== this.__collapsed) {
      showCollapsed(dom, this.__collapsed);
    }
    return false;
  }

  getVariant(): CalloutVariant {
    return this.getLatest().__variant;
  }

  getCollapsed(): boolean {
    return this.getLatest().__collapsed;
  }

  setCollapsed(collapsed: boolean): this {
    const writable = this.getWritable();
    writable.__collapsed = collapsed;
    return writable;
  }

  setVariant(variant: CalloutVariant): this {
    const writable = this.getWritable();
    writable.__variant = variant;
    return writable;
  }

  isShadowRoot(): boolean {
    return true;
  }

  canBeEmpty(): boolean {
    return false;
  }
}

export function $createCalloutNode(
  variant: CalloutVariant = "info",
  collapsed = false
): CalloutNode {
  return $applyNodeReplacement(new CalloutNode(variant, undefined, collapsed));
}

export function $isCalloutNode(node: LexicalNode | null | undefined): node is CalloutNode {
  return node instanceof CalloutNode;
}

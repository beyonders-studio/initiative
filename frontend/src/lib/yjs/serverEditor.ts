/**
 * The document editor without a page, for the server.
 *
 * Built on its own by `scripts/build-editor-server.mjs` and run in an embedded
 * engine (`backend/app/services/editor_worker.py`), so the server reads and
 * writes a document's Yjs state with the same nodes, in the same shape, as the
 * browser does. It binds a headless editor to a Yjs document the way Lexical
 * documents for a server (`@lexical/yjs` with a provider that does nothing).
 *
 * States cross the boundary as hex, and the caller names the Yjs client a
 * state is written as.
 */
import { buildEditorFromExtensions } from "@lexical/extension";
import { $convertFromMarkdownString } from "@lexical/markdown";
import {
  type Binding,
  createBinding,
  type Provider,
  syncLexicalUpdateToYjs,
  syncYjsChangesToLexical,
} from "@lexical/yjs";
import {
  $createLineBreakNode,
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $isElementNode,
  $isTextNode,
  $parseSerializedNode,
  type ElementNode,
  type LexicalEditor,
  type LexicalNode,
  type SerializedLexicalNode,
} from "lexical";
import {
  applyUpdate,
  Doc,
  encodeStateAsUpdate,
  encodeStateVector,
  type Transaction,
  type YEvent,
  type Text as YText,
} from "yjs";

import { documentExtension } from "@/components/ui/editor/document-extension";
import { MARKDOWN_TRANSFORMERS } from "@/components/ui/editor/extensions/markdown-shortcuts-extension";
import { COLLAB_EXCLUDED_PROPERTIES } from "@/components/ui/editor/nodes/image-node";
import { registerLegacyNodes } from "@/components/ui/editor/nodes/legacy-nodes";

/** The id the browser's `CollaborationPlugin` binds under. */
const ROOT_ID = "main";

const toHex = (bytes: Uint8Array) =>
  Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");

const fromHex = (hex: string) => {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
};

function silentProvider(): Provider {
  const nothing = () => {};
  return {
    awareness: {
      getLocalState: () => null,
      getStates: () => new Map(),
      off: nothing,
      on: nothing,
      setLocalState: nothing,
      setLocalStateField: nothing,
    },
    connect: nothing,
    disconnect: nothing,
    off: nothing,
    on: nothing,
  } as unknown as Provider;
}

function withEditor<T>(clientId: number | null, use: (editor: LexicalEditor, doc: Doc) => T): T {
  const editor = buildEditorFromExtensions(
    // Content the editor cannot read is refused rather than written as an
    // empty document.
    documentExtension({
      collaborative: true,
      editable: false,
      onError: (error) => {
        throw error;
      },
    })
  );
  const doc = new Doc();
  if (clientId !== null) doc.clientID = clientId;
  const provider = silentProvider();
  const binding: Binding = createBinding(
    editor,
    provider,
    ROOT_ID,
    doc,
    new Map([[ROOT_ID, doc]]),
    COLLAB_EXCLUDED_PROPERTIES
  );
  const stopUpdates = editor.registerUpdateListener(
    ({ dirtyElements, dirtyLeaves, editorState, normalizedNodes, prevEditorState, tags }) => {
      if (!tags.has("skip-collab")) {
        syncLexicalUpdateToYjs(
          binding,
          provider,
          prevEditorState,
          editorState,
          dirtyElements,
          dirtyLeaves,
          normalizedNodes,
          tags
        );
      }
    }
  );
  const observer = (events: Array<YEvent<YText>>, transaction: Transaction) => {
    if (transaction.origin !== binding) {
      syncYjsChangesToLexical(binding, provider, events, false);
    }
  };
  binding.root.getSharedType().observeDeep(observer);
  try {
    return use(editor, doc);
  } finally {
    binding.root.getSharedType().unobserveDeep(observer);
    stopUpdates();
    editor.dispose();
  }
}

/** Rewrite the legacy nodes a document holds as current content, as the
 * browser's editor does when it opens one. */
const modernize = (editor: LexicalEditor) => registerLegacyNodes(editor)();

/**
 * A document's Yjs state, from its editor JSON, or with one empty paragraph
 * when it has none — what the browser's editor starts a new document with.
 */
function bootstrap(json: string | null, clientId: number): string {
  return withEditor(clientId, (editor, doc) => {
    if (json === null) {
      editor.update(() => $getRoot().append($createParagraphNode()), { discrete: true });
    } else {
      editor.setEditorState(editor.parseEditorState(json), { tag: "history-merge" });
      modernize(editor);
    }
    return toHex(encodeStateAsUpdate(doc));
  });
}

function load(editor: LexicalEditor, doc: Doc, state: string) {
  applyUpdate(doc, fromHex(state), { isUpdateRemote: true });
  editor.update(() => {}, { discrete: true });
}

/** The editor JSON a Yjs state reads as. Nothing it does is kept. */
function render(state: string): string {
  return withEditor(null, (editor, doc) => {
    load(editor, doc, state);
    modernize(editor);
    return JSON.stringify(editor.getEditorState().toJSON());
  });
}

type Serialized = SerializedLexicalNode & { children?: Serialized[]; text?: string };

/** A node as a comparison sees it: its JSON with keys in order, without
 *  default values, which a parsed node leaves out and a node read from Yjs
 *  spells out, and without `direction`, which the browser works out as it
 *  draws the text and the server, drawing nothing, never does. */
const keyOf = (node: Serialized, without?: "children" | "text") =>
  JSON.stringify(node, (key, value) => {
    if (
      key !== "" &&
      (key === without ||
        key === "direction" ||
        value === 0 ||
        value === "" ||
        value === null ||
        value === false ||
        value === "normal")
    ) {
      return undefined;
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return Object.fromEntries(Object.entries(value).sort(([a], [b]) => (a < b ? -1 : 1)));
    }
    return value;
  });

/** Past this many pairs to compare, the changed middle of a run is matched
 *  by position rather than searched for blocks that moved. */
const MATCH_LIMIT = 1_000_000;

/** Pairs `[i, j]` of equal keys in `was` and `next`, in order, as many as
 *  there can be: the children a change kept, wherever they now sit. The
 *  unchanged ends are paired first, so only what lies between them is
 *  searched. */
function unchangedPairs(was: string[], next: string[]): Array<[number, number]> {
  let head = 0;
  while (head < was.length && head < next.length && was[head] === next[head]) head++;
  let tail = 0;
  while (
    tail < was.length - head &&
    tail < next.length - head &&
    was[was.length - 1 - tail] === next[next.length - 1 - tail]
  ) {
    tail++;
  }
  const pairs: Array<[number, number]> = [];
  for (let k = 0; k < head; k++) pairs.push([k, k]);
  const midWas = was.slice(head, was.length - tail);
  const midNext = next.slice(head, next.length - tail);
  if (midWas.length * midNext.length <= MATCH_LIMIT) {
    const longest = Array.from({ length: midWas.length + 1 }, () =>
      new Array<number>(midNext.length + 1).fill(0)
    );
    for (let i = midWas.length - 1; i >= 0; i--) {
      for (let j = midNext.length - 1; j >= 0; j--) {
        longest[i][j] =
          midWas[i] === midNext[j]
            ? longest[i + 1][j + 1] + 1
            : Math.max(longest[i + 1][j], longest[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < midWas.length && j < midNext.length) {
      if (midWas[i] === midNext[j]) {
        pairs.push([head + i, head + j]);
        i++;
        j++;
      } else if (longest[i + 1][j] >= longest[i][j + 1]) {
        i++;
      } else {
        j++;
      }
    }
  }
  for (let k = tail; k > 0; k--) pairs.push([was.length - k, next.length - k]);
  return pairs;
}

/**
 * Make `parent`'s children, whose JSON is `was`, read as `next`. Children a
 * change kept stay as they are, wherever they now sit. Between them, a run
 * with as many children on each side is reconciled child by child, and any
 * other run is replaced.
 */
function $reconcileChildren(parent: ElementNode, was: Serialized[], next: Serialized[]) {
  const nodes = parent.getChildren();
  const wasKeys = was.map((node) => keyOf(node));
  const nextKeys = next.map((node) => keyOf(node));
  let previous: LexicalNode | null = null;
  const place = (node: LexicalNode) => {
    if (previous) previous.insertAfter(node);
    else {
      const first = parent.getFirstChild();
      if (first) first.insertBefore(node);
      else parent.append(node);
    }
    previous = node;
  };
  const settle = (fromWas: number, toWas: number, fromNext: number, toNext: number) => {
    if (toWas - fromWas === toNext - fromNext) {
      for (let k = 0; k < toWas - fromWas; k++) {
        previous = $reconcile(nodes[fromWas + k], was[fromWas + k], next[fromNext + k]);
      }
      return;
    }
    for (const node of nodes.slice(fromWas, toWas)) node.remove();
    for (const node of next.slice(fromNext, toNext)) place($parseSerializedNode(node));
  };
  let i = 0;
  let j = 0;
  for (const [keptWas, keptNext] of unchangedPairs(wasKeys, nextKeys)) {
    settle(i, keptWas, j, keptNext);
    previous = nodes[keptWas];
    i = keptWas + 1;
    j = keptNext + 1;
  }
  settle(i, was.length, j, next.length);
}

/** Make `node`, whose JSON is `was`, read as `next`: an element of the same
 *  kind keeps itself and reconciles its children, a text of the same kind has
 *  only its changed characters spliced, and anything else is replaced.
 *  Returns the node that now stands where `node` did. */
function $reconcile(node: LexicalNode, was: Serialized, next: Serialized): LexicalNode {
  if (keyOf(was) === keyOf(next)) return node;
  if (
    $isElementNode(node) &&
    Array.isArray(was.children) &&
    Array.isArray(next.children) &&
    keyOf(was, "children") === keyOf(next, "children")
  ) {
    $reconcileChildren(node, was.children, next.children);
    return node;
  }
  if ($isTextNode(node) && keyOf(was, "text") === keyOf(next, "text")) {
    const from = node.getTextContent();
    const to = next.text ?? "";
    let start = 0;
    while (start < from.length && start < to.length && from[start] === to[start]) start++;
    let end = 0;
    while (
      end < from.length - start &&
      end < to.length - start &&
      from[from.length - 1 - end] === to[to.length - 1 - end]
    ) {
      end++;
    }
    node.spliceText(start, from.length - start - end, to.slice(start, to.length - end));
    return node;
  }
  return node.replace($parseSerializedNode(next));
}

/**
 * The Yjs update that makes a state read as `json`, written as the named
 * client. Only what changed is rewritten — down to the characters of a text
 * — so it merges with edits made to the same state elsewhere as a person's
 * own typing would.
 */
function apply(state: string, json: string, clientId: number): string {
  return withEditor(clientId, (editor, doc) => {
    load(editor, doc, state);
    const before = encodeStateVector(doc);
    const was = editor.getEditorState().toJSON().root as Serialized;
    const next = (JSON.parse(json) as { root: Serialized }).root;
    editor.update(() => $reconcileChildren($getRoot(), was.children ?? [], next.children ?? []), {
      discrete: true,
    });
    modernize(editor);
    return toHex(encodeStateAsUpdate(doc, before));
  });
}

/**
 * The editor JSON a text reads as: Markdown through the transformers the
 * editor's own Markdown view uses, or, `plain`, as paragraphs, split at blank
 * lines, with each line kept.
 */
function fromMarkdown(text: string, plain: boolean): string {
  return withEditor(null, (editor) => {
    editor.update(
      () => {
        const root = $getRoot();
        root.clear();
        if (plain) {
          for (const block of text.replace(/\r\n?/g, "\n").split(/\n{2,}/)) {
            const paragraph = $createParagraphNode();
            block.split("\n").forEach((line, index) => {
              if (index > 0) paragraph.append($createLineBreakNode());
              if (line) paragraph.append($createTextNode(line));
            });
            root.append(paragraph);
          }
        } else {
          $convertFromMarkdownString(text, MARKDOWN_TRANSFORMERS);
        }
        if (root.getChildrenSize() === 0) root.append($createParagraphNode());
      },
      { discrete: true }
    );
    modernize(editor);
    return JSON.stringify(editor.getEditorState().toJSON());
  });
}

(globalThis as { serverEditor?: unknown }).serverEditor = {
  apply,
  bootstrap,
  fromMarkdown,
  render,
};

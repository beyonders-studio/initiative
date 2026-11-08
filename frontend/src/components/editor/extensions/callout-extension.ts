import { $isListNode } from "@lexical/list";
import { $findMatchingParent, $insertNodeToNearestRoot, mergeRegister } from "@lexical/utils";
import {
  $createParagraphNode,
  $getNodeByKey,
  $getSelection,
  $isElementNode,
  $isParagraphNode,
  $isRangeSelection,
  $isRootOrShadowRoot,
  COMMAND_PRIORITY_EDITOR,
  COMMAND_PRIORITY_LOW,
  createCommand,
  defineExtension,
  INSERT_PARAGRAPH_COMMAND,
  KEY_ARROW_DOWN_COMMAND,
  KEY_BACKSPACE_COMMAND,
  type LexicalCommand,
  type LexicalNode,
} from "lexical";

import {
  $createCalloutNode,
  $isCalloutNode,
  CalloutNode,
  type CalloutVariant,
} from "@/components/editor/nodes/callout-node";

export const INSERT_CALLOUT_COMMAND: LexicalCommand<CalloutVariant> =
  createCommand("INSERT_CALLOUT_COMMAND");

/** The blocks a selection touches, each as the child of its root or shadow
 * root — what wrapping them in a callout would move. */
function $selectedBlocks(): LexicalNode[] {
  const selection = $getSelection();
  if (!$isRangeSelection(selection)) {
    return [];
  }
  const blocks: LexicalNode[] = [];
  for (const node of selection.getNodes()) {
    const block = $findMatchingParent(node, (candidate) => {
      const parent = candidate.getParent();
      return parent !== null && $isRootOrShadowRoot(parent);
    });
    if (block !== null && !blocks.includes(block)) {
      blocks.push(block);
    }
  }
  return blocks;
}

/** The callout the caret sits in, when it sits at the very start of it. */
function $calloutAtCaretStart(): CalloutNode | null {
  const selection = $getSelection();
  if (!$isRangeSelection(selection) || !selection.isCollapsed() || selection.anchor.offset !== 0) {
    return null;
  }
  const anchor = selection.anchor.getNode();
  const callout = $findMatchingParent(anchor, $isCalloutNode);
  if (!$isCalloutNode(callout)) {
    return null;
  }
  // A list's first item has its own Backspace — it outdents — so a callout
  // opening on a list is left to it.
  const firstChild = callout.getFirstChild();
  if (firstChild === null || $isListNode(firstChild)) {
    return null;
  }
  const first = callout.getFirstDescendant();
  return first !== null && (first.is(anchor) || firstChild.is(anchor)) ? callout : null;
}

/** The folded callout the caret is hidden inside — in any line after the first,
 * which is all a folded callout shows. */
function $foldedAroundCaret(): CalloutNode | null {
  const selection = $getSelection();
  if (!$isRangeSelection(selection)) {
    return null;
  }
  const anchor = selection.anchor.getNode();
  const callout = $findMatchingParent(anchor, $isCalloutNode);
  if (!$isCalloutNode(callout) || !callout.getCollapsed()) {
    return null;
  }
  const first = callout.getFirstChild();
  const line = $findMatchingParent(anchor, (node) => node.getParent()?.is(callout) ?? false);
  return line !== null && first !== null && !line.is(first) ? callout : null;
}

/** Take a callout apart, leaving its blocks where it stood. */
function $unwrap(callout: CalloutNode): void {
  for (const child of callout.getChildren()) {
    callout.insertBefore(child);
  }
  callout.remove();
}

export const CalloutExtension = defineExtension({
  name: "@initiative/callout",
  nodes: [CalloutNode],
  register: (editor) =>
    mergeRegister(
      // Writing where nobody can see it is not writing: a caret that lands in
      // a folded callout's hidden lines — Enter at the end of its first, an
      // arrow key — opens it.
      editor.registerUpdateListener(({ editorState }) => {
        if (!editor.isEditable()) return;
        const key = editorState.read(() => $foldedAroundCaret()?.getKey() ?? null);
        if (key === null) return;
        editor.update(() => {
          const node = $getNodeByKey(key);
          if ($isCalloutNode(node)) node.setCollapsed(false);
        });
      }),
      editor.registerCommand(
        INSERT_CALLOUT_COMMAND,
        (variant) => {
          const blocks = $selectedBlocks().filter(
            (block) => $isElementNode(block) && !$isCalloutNode(block) && !block.isInline()
          );
          const callout = $createCalloutNode(variant);
          if (blocks.length > 0) {
            blocks[0].insertBefore(callout);
            callout.append(...blocks);
            callout.selectEnd();
          } else {
            callout.append($createParagraphNode());
            $insertNodeToNearestRoot(callout);
            callout.selectStart();
          }
          return true;
        },
        COMMAND_PRIORITY_EDITOR
      ),
      // Enter on an empty last line leaves the callout, the way it leaves a
      // list: the line moves out below it.
      editor.registerCommand(
        INSERT_PARAGRAPH_COMMAND,
        () => {
          const selection = $getSelection();
          if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
            return false;
          }
          const block = selection.anchor.getNode();
          const paragraph = $isParagraphNode(block) ? block : block.getParent();
          const callout = paragraph?.getParent();
          if (
            !$isParagraphNode(paragraph) ||
            !$isCalloutNode(callout) ||
            paragraph.getTextContentSize() > 0 ||
            !callout.getLastChild()?.is(paragraph) ||
            callout.getChildrenSize() < 2
          ) {
            return false;
          }
          callout.insertAfter(paragraph);
          paragraph.selectStart();
          return true;
        },
        COMMAND_PRIORITY_LOW
      ),
      // Backspace at the very start takes the callout away and keeps what it
      // said.
      editor.registerCommand(
        KEY_BACKSPACE_COMMAND,
        (event) => {
          const callout = $calloutAtCaretStart();
          if (callout === null) {
            return false;
          }
          event?.preventDefault();
          $unwrap(callout);
          return true;
        },
        COMMAND_PRIORITY_LOW
      ),
      // Arrow down from the end of a callout that ends the document opens a
      // line below it, or there would be no way to write after it.
      editor.registerCommand(
        KEY_ARROW_DOWN_COMMAND,
        () => {
          const selection = $getSelection();
          if (!$isRangeSelection(selection) || !selection.isCollapsed()) {
            return false;
          }
          const callout = $findMatchingParent(selection.anchor.getNode(), $isCalloutNode);
          if (
            !$isCalloutNode(callout) ||
            callout.getNextSibling() !== null ||
            !callout.getLastDescendant()?.is(selection.anchor.getNode())
          ) {
            return false;
          }
          const paragraph = $createParagraphNode();
          callout.insertAfter(paragraph);
          paragraph.selectStart();
          return true;
        },
        COMMAND_PRIORITY_LOW
      )
    ),
});

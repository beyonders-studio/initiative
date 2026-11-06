import { $isLinkNode } from "@lexical/link";
import { $convertFromMarkdownString, type TextMatchTransformer } from "@lexical/markdown";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $findMatchingParent } from "@lexical/utils";
import {
  $createParagraphNode,
  $createRangeSelection,
  $getNodeByKey,
  $getRoot,
  $getSelection,
  $isElementNode,
  $isLineBreakNode,
  $isParagraphNode,
  $isRangeSelection,
  $isTextNode,
  $setSelection,
  COMMAND_PRIORITY_EDITOR,
  createCommand,
  type ElementNode,
  type LexicalCommand,
  type LexicalNode,
  type PointType,
  type RangeSelection,
  type TextFormatType,
} from "lexical";
import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { type AIStreamRequest, readAIStream } from "@/api/aiStream";
import { AIWriteAction, type AIWriteRequest } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { MARKDOWN_TRANSFORMERS } from "@/components/ui/editor/extensions/markdown-shortcuts-extension";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";

/** Ask for writing help with the selection, or, to continue, at the cursor. */
export const AI_WRITE_COMMAND: LexicalCommand<{ action: AIWriteAction; language?: string }> =
  createCommand("AI_WRITE_COMMAND");

/** How much text before the cursor is sent to continue writing. The server
 *  keeps what fits of it, nearest the cursor. */
const CONTINUE_FROM_CHARS = 6000;

/** The inline formatting a rewrite is asked to keep, as markdown marks. */
const MARKS: Array<[TextFormatType, string]> = [
  ["code", "`"],
  ["bold", "**"],
  ["italic", "*"],
  ["strikethrough", "~~"],
];

interface Saved {
  key: string;
  offset: number;
  type: PointType["type"];
}

/** What was asked about, kept to put the answer back where it belongs. */
interface Asked {
  action: AIWriteAction;
  anchor: Saved;
  focus: Saved;
  /** The selection as it was sent, to tell whether it has changed. */
  original: string;
  /** The block the selection ends in, which an answer is inserted below. */
  blockKey: string;
  top: number;
  left: number;
}

const saved = (point: PointType): Saved => ({
  key: point.key,
  offset: point.offset,
  type: point.type,
});

/** The markdown the editor writes inline nodes as: mentions, references and
 *  smart chips, which read back as themselves. */
const INLINE_EXPORTS = MARKDOWN_TRANSFORMERS.filter(
  (transformer): transformer is TextMatchTransformer => transformer.type === "text-match"
);

/** The selection's points, start first. */
const $ends = (selection: RangeSelection): [PointType, PointType] =>
  selection.isBackward()
    ? [selection.focus, selection.anchor]
    : [selection.anchor, selection.focus];

/** The block a node is written in: its paragraph, heading or list item. */
const $blockOf = (node: LexicalNode) =>
  $findMatchingParent(node, (parent) => $isElementNode(parent) && !parent.isInline());

/** The selection as markdown: its text, with the formatting a rewrite keeps
 *  and its mentions and references as they are written. Null when it holds
 *  something markdown cannot carry back, which a rewrite would lose: a node
 *  with no markdown of its own, or more than one block that is not a plain
 *  paragraph (list items, a heading and what follows it). */
const $selectionMarkdown = (selection: RangeSelection): string | null => {
  const [start, end] = $ends(selection);
  let markdown = "";
  const blocks: LexicalNode[] = [];
  for (const node of selection.getNodes()) {
    if ($isElementNode(node)) continue;
    const block = $blockOf(node);
    const last = blocks.at(-1);
    if (block && !block.is(last)) {
      if (last) markdown += "\n\n";
      blocks.push(block);
    }
    if ($isLineBreakNode(node)) {
      markdown += "\n";
      continue;
    }
    if (!$isTextNode(node)) {
      const written = INLINE_EXPORTS.map((transformer) =>
        transformer.export?.(
          node,
          () => "",
          (_node, text) => text
        )
      ).find(Boolean);
      if (!written) return null;
      markdown += written;
      continue;
    }
    let text = node.getTextContent();
    if (end.type === "text" && node.is(end.getNode())) text = text.slice(0, end.offset);
    if (start.type === "text" && node.is(start.getNode())) text = text.slice(start.offset);
    if (!text) continue;
    for (const [format, mark] of MARKS) {
      if (node.hasFormat(format)) text = `${mark}${text}${mark}`;
    }
    const link = node.getParent();
    markdown += $isLinkNode(link) ? `[${text}](${link.getURL()})` : text;
  }
  if (blocks.length > 1 && !blocks.every($isParagraphNode)) return null;
  return markdown;
};

/** The blocks ``markdown`` reads as, ready to place. */
const $markdownBlocks = (markdown: string): LexicalNode[] => {
  const holder = $createParagraphNode();
  $convertFromMarkdownString(markdown, MARKDOWN_TRANSFORMERS, holder, false);
  return holder.getChildren();
};

/** The text of ``block`` from its start to ``point``, or from ``point`` to
 *  its end. */
const $partOf = (block: ElementNode, point: PointType, side: "before" | "after"): string => {
  const range = $createRangeSelection();
  if (side === "before") {
    range.anchor.set(block.getKey(), 0, "element");
    range.focus.set(point.key, point.offset, point.type);
  } else {
    range.anchor.set(point.key, point.offset, point.type);
    range.focus.set(block.getKey(), block.getChildrenSize(), "element");
  }
  return range.getTextContent();
};

/** The text of the blocks before ``block``, nearest last, as far as ``limit``
 *  characters reach. */
const $textBefore = (block: LexicalNode, limit: number): string => {
  const parts: string[] = [];
  let length = 0;
  for (let node = block.getPreviousSibling(); node && length < limit; ) {
    const text = node.getTextContent();
    parts.unshift(text);
    length += text.length + 2;
    node = node.getPreviousSibling();
  }
  return parts.join("\n\n");
};

/**
 * Writing help in the editor: the answer streams into a preview under the
 * selection, and goes into the document only when it is placed. In a document
 * others are editing, a selection that changed while the answer was written is
 * not replaced; the answer can still go below it.
 */
export function AIWritingPlugin({
  anchorElem,
  write,
}: {
  anchorElem: HTMLElement | null;
  /** The request for ``body``, from the generated client. */
  write: (body: AIWriteRequest) => AIStreamRequest;
}) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const [asked, setAsked] = useState<Asked | null>(null);
  const [answer, setAnswer] = useState("");
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reading = useRef<AbortController | null>(null);
  // Kept current for the command, which is registered once.
  const writeRef = useRef(write);
  writeRef.current = write;

  useEffect(() => () => reading.current?.abort(), []);

  useEffect(
    () =>
      editor.registerCommand(
        AI_WRITE_COMMAND,
        ({ action, language }) => {
          // Commands run inside an update, so this is the selection as it is now.
          const asking = (() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return null;
            const continuing = action === AIWriteAction.continue;
            const [start, end] = $ends(selection);
            // The answer goes below where the selection ends, however it was drawn.
            const block = end.getNode().getTopLevelElement();
            const first = start.getNode().getTopLevelElement();
            if (!block || !first) return null;
            const original = continuing ? "" : $selectionMarkdown(selection);
            const around = (...parts: Array<string | undefined>) =>
              parts.filter(Boolean).join("\n\n");
            const body: AIWriteRequest = {
              action,
              language,
              text: original ?? "",
              // The words either side of the selection, or of the cursor to
              // continue from, then the paragraphs about them.
              before: around(
                continuing
                  ? $textBefore(first, CONTINUE_FROM_CHARS)
                  : first.getPreviousSibling()?.getTextContent(),
                $partOf(first, start, "before")
              ),
              after: `${$partOf(block, end, "after")}${
                block.getNextSibling() ? `\n\n${block.getNextSibling()?.getTextContent()}` : ""
              }`,
            };
            return {
              body,
              anchor: saved(selection.anchor),
              focus: saved(selection.focus),
              original,
              blockKey: block.getKey(),
            };
          })();
          if (!asking || !anchorElem) return false;
          const keeps = asking.original !== null;
          const range = window.getSelection()?.rangeCount
            ? window.getSelection()?.getRangeAt(0).getBoundingClientRect()
            : null;
          const frame = anchorElem.getBoundingClientRect();
          reading.current?.abort();
          const controller = new AbortController();
          reading.current = controller;
          setAsked({
            action,
            anchor: asking.anchor,
            focus: asking.focus,
            original: asking.original ?? "",
            blockKey: asking.blockKey,
            top: range ? range.bottom - frame.top + 8 : 0,
            left: range ? Math.max(0, range.left - frame.left) : 0,
          });
          setAnswer("");
          setError(keeps ? null : t("writing.cannotKeep"));
          setWriting(keeps);
          if (!keeps) return true;
          let written = "";
          void readAIStream(writeRef.current(asking.body), controller.signal, (event) => {
            if (event.error) {
              setError(messageForCode(event.error, "editor:writing.error"));
              return;
            }
            written += event.text ?? "";
            setAnswer(written);
          })
            .catch((err: unknown) => {
              if (!controller.signal.aborted) {
                setError(getErrorMessage(err, "editor:writing.error"));
              }
            })
            .finally(() => {
              if (reading.current === controller) setWriting(false);
            });
          return true;
        },
        COMMAND_PRIORITY_EDITOR
      ),
    [editor, anchorElem, t]
  );

  const close = () => {
    reading.current?.abort();
    setAsked(null);
    setAnswer("");
    setError(null);
    setWriting(false);
  };

  /** Put the answer where the selection was, or at the cursor to continue
   *  from. True when that text changed meanwhile, and nothing was put. */
  const putInPlace = (): boolean => {
    if (!asked) return true;
    let changed = false;
    editor.update(() => {
      const selection = $createRangeSelection();
      const anchor = $getNodeByKey(asked.anchor.key);
      const focus = $getNodeByKey(asked.focus.key);
      if (!anchor?.isAttached() || !focus?.isAttached()) {
        changed = true;
        return;
      }
      selection.anchor.set(asked.anchor.key, asked.anchor.offset, asked.anchor.type);
      selection.focus.set(asked.focus.key, asked.focus.offset, asked.focus.type);
      try {
        // Its words, formatting, links and mentions, any of which another
        // writer may have changed.
        changed = $selectionMarkdown(selection) !== asked.original;
      } catch {
        changed = true;
      }
      if (changed) return;
      const blocks = $markdownBlocks(answer);
      // One paragraph goes in where the selection was, inside its block.
      const [only] = blocks;
      const nodes = blocks.length === 1 && $isParagraphNode(only) ? only.getChildren() : blocks;
      $setSelection(selection);
      selection.insertNodes(nodes);
    });
    return changed;
  };

  const replace = () => {
    if (putInPlace()) {
      setError(t("writing.changed"));
    } else {
      close();
    }
  };

  /** A continuation goes at the cursor, or below if its paragraph has gone. */
  const insert = () => {
    if (putInPlace()) {
      insertBelow();
    } else {
      close();
    }
  };

  const insertBelow = () => {
    if (!asked) return;
    editor.update(() => {
      const blocks = $markdownBlocks(answer);
      let below = $getNodeByKey(asked.blockKey);
      if (!below?.isAttached()) below = $getRoot().getLastChild();
      for (const block of blocks) {
        if (below) {
          below.insertAfter(block);
        } else {
          $getRoot().append(block);
        }
        below = block;
      }
      below?.selectEnd();
    });
    close();
  };

  if (!asked || !anchorElem) return null;

  const continuing = asked.action === AIWriteAction.continue;
  return createPortal(
    <div
      role="dialog"
      aria-label={t("writing.preview")}
      className="absolute z-20 w-[min(28rem,100%)] space-y-2 rounded-md border bg-background p-3 shadow-md"
      style={{ top: asked.top, left: asked.left }}
    >
      {answer ? (
        <p className="max-h-64 overflow-y-auto whitespace-pre-wrap text-sm">{answer}</p>
      ) : writing ? (
        <p className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("writing.writing")}
        </p>
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={close}>
          {t("writing.discard")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={continuing ? "default" : "outline"}
          disabled={writing || !answer}
          onClick={continuing ? insert : insertBelow}
        >
          {continuing ? t("writing.insert") : t("writing.insertBelow")}
        </Button>
        {continuing ? null : (
          <Button type="button" size="sm" disabled={writing || !answer} onClick={replace}>
            {t("writing.replace")}
          </Button>
        )}
      </div>
    </div>,
    anchorElem
  );
}

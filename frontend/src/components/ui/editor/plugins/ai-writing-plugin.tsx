import { $isLinkNode } from "@lexical/link";
import { $convertFromMarkdownString } from "@lexical/markdown";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  $createParagraphNode,
  $createRangeSelection,
  $getNodeByKey,
  $getRoot,
  $getSelection,
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
  /** The selection's text as it was sent, to tell whether it has changed. */
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

/** The selection as markdown: its text, with the formatting a rewrite keeps. */
const $selectionMarkdown = (selection: RangeSelection): string => {
  const [start, end] = selection.isBackward()
    ? [selection.focus, selection.anchor]
    : [selection.anchor, selection.focus];
  let markdown = "";
  let block: ElementNode | null = null;
  for (const node of selection.getNodes()) {
    if (!$isTextNode(node)) continue;
    const top = node.getTopLevelElement();
    if (block && top && !top.is(block)) markdown += "\n\n";
    block = top;
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
  return markdown;
};

/** The blocks ``markdown`` reads as, ready to place. */
const $markdownBlocks = (markdown: string): LexicalNode[] => {
  const holder = $createParagraphNode();
  $convertFromMarkdownString(markdown, MARKDOWN_TRANSFORMERS, holder, false);
  return holder.getChildren();
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
            const block = selection.focus.getNode().getTopLevelElement();
            const first = (selection.isBackward() ? selection.focus : selection.anchor)
              .getNode()
              .getTopLevelElement();
            if (!block || !first) return null;
            const body: AIWriteRequest = {
              action,
              language,
              text: continuing ? "" : $selectionMarkdown(selection),
              before: continuing
                ? [$textBefore(block, CONTINUE_FROM_CHARS), block.getTextContent()]
                    .filter(Boolean)
                    .join("\n\n")
                : (first.getPreviousSibling()?.getTextContent() ?? ""),
              after: block.getNextSibling()?.getTextContent() ?? "",
            };
            return {
              body,
              anchor: saved(selection.anchor),
              focus: saved(selection.focus),
              original: selection.getTextContent(),
              blockKey: block.getKey(),
            };
          })();
          if (!asking || !anchorElem) return false;
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
            original: asking.original,
            blockKey: asking.blockKey,
            top: range ? range.bottom - frame.top + 8 : 0,
            left: range ? Math.max(0, range.left - frame.left) : 0,
          });
          setAnswer("");
          setError(null);
          setWriting(true);
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
    [editor, anchorElem]
  );

  const close = () => {
    reading.current?.abort();
    setAsked(null);
    setAnswer("");
    setError(null);
    setWriting(false);
  };

  const replace = () => {
    if (!asked) return;
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
        changed = selection.getTextContent() !== asked.original;
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
    if (changed) {
      setError(t("writing.changed"));
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
      // Continuing from an empty line writes on that line.
      if (
        asked.action === AIWriteAction.continue &&
        $isParagraphNode(below) &&
        below.getTextContent() === "" &&
        blocks.length > 0
      ) {
        const [first, ...rest] = blocks;
        below.replace(first);
        below = first;
        blocks.splice(0, blocks.length, ...rest);
      }
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
          onClick={insertBelow}
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
